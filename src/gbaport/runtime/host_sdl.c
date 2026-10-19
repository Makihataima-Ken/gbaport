/* host_sdl.c - run a recompiled game in a window (SDL3).
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--registers]
 *              [--screenshot PATH] [--scale N] [--fast]
 *
 * Keyboard: arrows, X = A, Z = B, A = L, S = R, Enter = Start, Backspace = Select. A
 * gamepad works too: its right face button is A, the bottom one B. The game runs at the
 * GBA's 59.73 frames a second (--fast: as fast as it can); the window scales the picture
 * by whole steps (--scale: the starting size in GBA screens, 3 by default). Closing the
 * window ends the run with exit status 0. While the game is stopped (the BIOS Stop call)
 * the screen is dark and a key press wakes it, if the game asked for that; in a run
 * limited by --frames, a Stop that no scripted press wakes ends the run instead. The other
 * options and exit statuses are those of host_headless.c. */
#include <stdio.h>
#include <string.h>

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include "host_common.h"

#define FRAME_NS 16742706u  /* 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns */

static HostOptions options;
static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static SDL_Gamepad *gamepad;
static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
static int closed;
static Uint64 pace_start, paced;

static const SDL_Scancode KEYBOARD[10] = {
    SDL_SCANCODE_X, SDL_SCANCODE_Z, SDL_SCANCODE_BACKSPACE, SDL_SCANCODE_RETURN,
    SDL_SCANCODE_RIGHT, SDL_SCANCODE_LEFT, SDL_SCANCODE_UP, SDL_SCANCODE_DOWN,
    SDL_SCANCODE_S, SDL_SCANCODE_A,
};
static const SDL_GamepadButton BUTTONS[10] = {
    SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_BACK,
    SDL_GAMEPAD_BUTTON_START, SDL_GAMEPAD_BUTTON_DPAD_RIGHT, SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN,
    SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,
};

static void handle(const SDL_Event *event)
{
    if (event->type == SDL_EVENT_QUIT)
        closed = 1;
    else if (event->type == SDL_EVENT_GAMEPAD_ADDED && !gamepad)
        gamepad = SDL_OpenGamepad(event->gdevice.which);
    else if (event->type == SDL_EVENT_GAMEPAD_REMOVED && gamepad &&
             SDL_GetGamepadID(gamepad) == event->gdevice.which) {
        SDL_CloseGamepad(gamepad);
        gamepad = NULL;
    }
}

/* The keys held on the keyboard, the gamepad and in the script. */
static uint16_t held_keys(void)
{
    const bool *keyboard = SDL_GetKeyboardState(NULL);
    uint16_t keys = options.script_keys;
    for (int k = 0; k < 10; k++) {
        if (keyboard[KEYBOARD[k]] || (gamepad && SDL_GetGamepadButton(gamepad, BUTTONS[k])))
            keys |= (uint16_t)(1u << k);
    }
    if (gamepad) {  /* the left stick works as the D-pad */
        Sint16 x = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTX);
        Sint16 y = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTY);
        keys |= (uint16_t)((x > 16000) << 4 | (x < -16000) << 5 | (y < -16000) << 6 | (y > 16000) << 7);
    }
    return keys;
}

static void present(void)
{
    SDL_UpdateTexture(texture, NULL, pixels, GBA_SCREEN_WIDTH * 4);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    SDL_RenderTexture(renderer, texture, NULL, NULL);
}

/* Waits until this frame's time has come; after falling behind by more than a few
 * frames (a slow machine, a dragged window) it starts counting again instead of rushing. */
static void pace(void)
{
    if (options.fast)
        return;
    Uint64 now = SDL_GetTicksNS();
    if (paced == 0)
        pace_start = now;
    paced++;
    Uint64 due = pace_start + paced * FRAME_NS + paced * 153u / 512u;
    if (now < due)
        SDL_DelayPrecise(due - now);
    else if (now - due > 4ull * FRAME_NS)
        paced = 0;
}

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    SDL_Event event;
    while (SDL_PollEvent(&event))
        handle(&event);
    if (closed)
        gba_end(rt, GBA_END_HOST);
    gba_screen(rt, pixels);
    present();
    SDL_RenderPresent(renderer);
    pace();
    host_frame(&options, rt);
    gba_set_keys(rt, held_keys());
}

static void on_log(GbaRuntime *rt, int level, const char *text, void *user)
{
    (void)rt, (void)level, (void)user;
    printf("%s\n", text);
    fflush(stdout);
}

static void on_diag(GbaRuntime *rt, const char *text, void *user)
{
    (void)rt, (void)user;
    fprintf(stderr, "warning: %s\n", text);
}

/* Stopped: a dark screen until the keys change (or the script presses some). */
static int on_stopped(GbaRuntime *rt, void *user)
{
    (void)user;
    memset(pixels, 0, sizeof pixels);
    present();
    SDL_RenderPresent(renderer);
    if (host_script_wake(&options)) {
        gba_set_keys(rt, held_keys());
        return 1;
    }
    if (options.frame_limit)  /* a run limited by --frames is scripted: end it, as headless */
        return 0;
    uint16_t before = held_keys();
    while (!closed) {
        SDL_Event event;
        if (SDL_WaitEventTimeout(&event, 100))
            handle(&event);
        if (held_keys() != before) {
            gba_set_keys(rt, held_keys());
            paced = 0;  /* the clocks stood still: do not rush to catch up */
            return 1;
        }
    }
    gba_end(rt, GBA_END_HOST);
    return 0;
}

static int open_window(void)
{
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "error: cannot start SDL: %s\n", SDL_GetError());
        return -1;
    }
    char title[64] = "gbaport";
    if (options.rom) {  /* the cartridge's title, 12 characters at 0xA0 */
        char name[13] = {0};
        memcpy(name, options.rom + 0xA0, 12);
        snprintf(title, sizeof title, "%s - gbaport", name);
    }
    int w = GBA_SCREEN_WIDTH * options.scale, h = GBA_SCREEN_HEIGHT * options.scale;
    if (!SDL_CreateWindowAndRenderer(title, w, h, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
        fprintf(stderr, "error: cannot open a window: %s\n", SDL_GetError());
        return -1;
    }
    SDL_SetRenderLogicalPresentation(renderer, GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT,
                                     SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING,
                                GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT);
    if (!texture) {
        fprintf(stderr, "error: cannot make the screen texture: %s\n", SDL_GetError());
        return -1;
    }
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
    return 0;
}

/* The window's picture, as the last frame left it, into a BMP file. */
static void screenshot(void)
{
    present();
    SDL_Surface *shot = SDL_RenderReadPixels(renderer, NULL);
    if (!shot || !SDL_SaveBMP(shot, options.screenshot))
        fprintf(stderr, "warning: cannot write %s: %s\n", options.screenshot, SDL_GetError());
    SDL_DestroySurface(shot);
}

int main(int argc, char **argv)
{
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
    options.window = 1;
    int status = host_parse(&options, argc, argv);
    if (status == 0)
        status = host_open(&options, &rt, &host);
    if (status != 0)
        return status;
    if (open_window() != 0)
        return 2;
    GbaEnd end = gba_run(&rt);
    if (options.screenshot)
        screenshot();
    status = host_finish(&options, &rt, end);
    SDL_Quit();
    return closed ? 0 : status;
}
