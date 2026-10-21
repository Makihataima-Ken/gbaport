/* host_sdl.c - run a recompiled game in a window (SDL3).
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--input FILE]
 *              [--registers] [--screenshot PATH] [--audio PATH] [--hashes PATH]
 *              [--scale N] [--fast]
 *
 * Keyboard: arrows, X = A, Z = B, A = L, S = R, Enter = Start, Backspace = Select. A
 * gamepad works too: its right face button is A, the bottom one B. The game runs at the
 * GBA's 59.73 frames a second (--fast: as fast as it can); the window scales the picture
 * by whole steps (--scale: the starting size in GBA screens, 3 by default). Closing the
 * window ends the run with exit status 0. While the game is stopped (the BIOS Stop call)
 * the screen is dark and a key press wakes it, if the game asked for that; the save is
 * stored as it stops, since nothing changes it until then. In a run limited by --frames,
 * a Stop that no scripted press wakes ends the run instead. The other options and exit
 * statuses are those of host_headless.c.
 *
 * The sound plays on the default sound device: an SDL audio stream takes the GBA's
 * samples (32768 a second) and converts them to the device's rate. About three frames'
 * worth wait in it; when the device's clock and the frame pacing drift apart, the stream
 * plays up to 1% faster or slower to keep it so. Without a sound device the game runs
 * silent (one warning); with --fast it runs silent too.
 *
 * On a phone (Android) the picture fills the screen, held sideways, as large as it fits,
 * and the GBA's buttons are drawn over it (touch.c lays them out and follows the fingers
 * on them) until a gamepad's button is pressed; touching the screen brings them back.
 * The ROM is the app's asset game.gba and the save file lives in the app's own storage.
 * The save is stored when the app goes to the background (Android may kill it there at
 * any time) and when it closes, besides once a second while it changes, so it survives
 * the app being killed; in the background the game is paused. Everything the game and the
 * runtime print goes to the system log (logcat, tag "gbaport"), with the frame rate and
 * how much of each frame's time the game took every ten seconds; a run that ends with an
 * error shows it before the app closes. The options come from the app's intent
 * (GameActivity.java). */
#include <stdio.h>
#include <string.h>

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include "host_common.h"

#if defined(SDL_PLATFORM_ANDROID)
#define MOBILE 1
#include <android/log.h>
#include <pthread.h>
#include <unistd.h>

#include "touch.h"
#else
#define MOBILE 0
#endif

#define FRAME_NS 16742706u  /* 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns */

static HostOptions options;
static GbaRuntime rt;
static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static SDL_Gamepad *gamepad;
static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
static int closed;
static Uint64 pace_start, paced;
static SDL_AudioStream *sound;  /* NULL: no sound */

enum { SOUND_TARGET = 3 * 549 };  /* samples to keep queued: about three frames */

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

#if MOBILE
static const char *const BUTTON_NAMES[TOUCH_BUTTONS] = {"A", "B", "SELECT", "START", "R", "L"};
static const uint16_t BUTTON_KEYS[TOUCH_BUTTONS] = {1u << 0, 1u << 1, 1u << 2, 1u << 3, 1u << 8, 1u << 9};
static TouchState touch;
static int touch_hidden;       /* a gamepad is in use: the drawn buttons are out of the way */
static int screen_w, screen_h;  /* in pixels */
static Uint64 awake, busy, report_start;  /* for the frame rate report */
static unsigned report_frames;

/* stdout and stderr go nowhere on Android: a thread passes their lines to logcat. */
static void *forward_output(void *pipe_end)
{
    FILE *output = fdopen((int)(intptr_t)pipe_end, "r");
    char line[1024];
    while (output && fgets(line, sizeof line, output)) {
        line[strcspn(line, "\n")] = 0;
        __android_log_write(ANDROID_LOG_INFO, "gbaport", line);
    }
    return NULL;
}

static void output_to_log(void)
{
    int ends[2];
    pthread_t thread;
    if (pipe(ends) != 0)
        return;
    dup2(ends[1], 1);
    dup2(ends[1], 2);
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
    if (pthread_create(&thread, NULL, forward_output, (void *)(intptr_t)ends[0]) == 0)
        pthread_detach(thread);
}

/* The screen's size and safe area (clear of notches and system bars) in pixels. */
static void lay_out(void)
{
    SDL_GetWindowSizeInPixels(window, &screen_w, &screen_h);
    float density = SDL_GetWindowPixelDensity(window);
    SDL_Rect safe;
    if (!SDL_GetWindowSafeArea(window, &safe) || safe.w <= 0 || safe.h <= 0)
        safe = (SDL_Rect){0, 0, (int)(screen_w / density), (int)(screen_h / density)};
    touch_layout(&touch.layout, (float)screen_w, (float)screen_h,
                 (TouchBox){safe.x * density, safe.y * density, safe.w * density, safe.h * density});
    const TouchLayout *l = &touch.layout;  /* in the log, for tests that touch the screen */
    printf("touch layout: screen %dx%d, D-pad at %.0f,%.0f radius %.0f", screen_w, screen_h,
           l->pad_x, l->pad_y, l->pad_radius);
    for (int b = 0; b < TOUCH_BUTTONS; b++)
        printf(", %s at %.0f,%.0f", BUTTON_NAMES[b], l->buttons[b].x + l->buttons[b].w / 2,
               l->buttons[b].y + l->buttons[b].h / 2);
    printf("\n");
}

static void fill_circle(float x, float y, float radius)
{
    enum { SIDES = 40 };
    SDL_FColor colour;
    SDL_GetRenderDrawColorFloat(renderer, &colour.r, &colour.g, &colour.b, &colour.a);
    SDL_Vertex corners[SIDES + 1] = {{{x, y}, colour, {0, 0}}};
    int triangles[3 * SIDES];
    for (int i = 0; i < SIDES; i++) {
        float angle = (float)i * 2 * SDL_PI_F / SIDES;
        corners[i + 1] = (SDL_Vertex){{x + radius * SDL_cosf(angle), y + radius * SDL_sinf(angle)},
                                      colour, {0, 0}};
        triangles[3 * i] = 0;
        triangles[3 * i + 1] = 1 + i;
        triangles[3 * i + 2] = 1 + (i + 1) % SIDES;
    }
    SDL_RenderGeometry(renderer, NULL, corners, SIDES + 1, triangles, 3 * SIDES);
}

/* `text` in SDL's 8x8 font, `size` pixels tall, centred on (x, y). */
static void label(const char *text, float x, float y, float size)
{
    float scale = size / 8;
    SDL_SetRenderScale(renderer, scale, scale);
    SDL_RenderDebugText(renderer, (x - 4 * (float)strlen(text) * scale) / scale,
                        (y - 4 * scale) / scale, text);
    SDL_SetRenderScale(renderer, 1, 1);
}

static void shade(int pressed)
{
    SDL_SetRenderDrawColor(renderer, 255, 255, 255, pressed ? 110 : 45);
}

/* The buttons, see-through, brighter where `keys` holds them. */
static void draw_buttons(uint16_t keys)
{
    const TouchLayout *l = &touch.layout;
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
    float r = l->pad_radius, arm = r / 3;
    shade(0);
    fill_circle(l->pad_x, l->pad_y, r);
    SDL_FRect arms[4] = {  /* right, left, up, down: GBA key bits 4 to 7 */
        {l->pad_x + arm / 2, l->pad_y - arm / 2, r - arm / 2, arm},
        {l->pad_x - r, l->pad_y - arm / 2, r - arm / 2, arm},
        {l->pad_x - arm / 2, l->pad_y - r, arm, r - arm / 2},
        {l->pad_x - arm / 2, l->pad_y + arm / 2, arm, r - arm / 2},
    };
    for (int d = 0; d < 4; d++) {
        shade(keys >> (4 + d) & 1);
        SDL_RenderFillRect(renderer, &arms[d]);
    }
    for (int b = 0; b < TOUCH_BUTTONS; b++) {
        TouchBox box = l->buttons[b];
        float x = box.x + box.w / 2, y = box.y + box.h / 2;
        shade((keys & BUTTON_KEYS[b]) != 0);
        if (b == TOUCH_A || b == TOUCH_B) {
            fill_circle(x, y, box.w / 2.8f);  /* the circle in its box (touch.c's A_B_REACH) */
            label(BUTTON_NAMES[b], x, y, box.h * 0.3f);
        } else {
            SDL_RenderFillRect(renderer, &(SDL_FRect){box.x, box.y, box.w, box.h});
            label(BUTTON_NAMES[b], x, y, box.h * 0.35f);
        }
    }
}

/* Every 600 frames (ten seconds): how many frames a second came, and how long the game
 * took a frame (the rest of the frame's time goes to waiting for the next one). `waited`
 * is when this frame's wait began; `awake`, when the last one ended. */
static void report_rate(Uint64 waited)
{
    if (awake)
        busy += waited - awake;
    if (report_frames == 0)
        report_start = waited;
    if (++report_frames == 601) {
        double seconds = (double)(waited - report_start) / 1e9;
        printf("%.2f frames a second; the game took %.1f ms a frame\n", 600 / seconds,
               (double)busy / 600 / 1e6);
        report_frames = 1;
        report_start = waited;
        busy = 0;
    }
}
#endif

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
#if MOBILE
    const SDL_TouchFingerEvent *finger = &event->tfinger;  /* x and y: 0 to 1 across the screen */
    switch (event->type) {
    case SDL_EVENT_FINGER_DOWN:
        touch_down(&touch, finger->fingerID, finger->x * screen_w, finger->y * screen_h);
        touch_hidden = 0;
        break;
    case SDL_EVENT_FINGER_MOTION:
        touch_move(&touch, finger->fingerID, finger->x * screen_w, finger->y * screen_h);
        break;
    case SDL_EVENT_FINGER_UP:
    case SDL_EVENT_FINGER_CANCELED:
        touch_up(&touch, finger->fingerID);
        break;
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
        touch_hidden = 1;
        break;
    case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
    case SDL_EVENT_WINDOW_SAFE_AREA_CHANGED:
        lay_out();
        break;
    default:
        break;
    }
#endif
}

#if MOBILE
/* The app's comings and goings. SDL passes them to watchers only, as they happen, on the
 * game's thread (the one pumping the events); in the background the next pump waits
 * until the app comes back, so the game is paused. */
static bool on_app_event(void *user, SDL_Event *event)
{
    (void)user;
    switch (event->type) {
    case SDL_EVENT_WILL_ENTER_BACKGROUND:  /* Android may kill the app from now on */
    case SDL_EVENT_TERMINATING:
        host_store_save(&options, &rt);
        touch.count = 0;  /* the fingers on the screen now will not come up here */
        break;
    case SDL_EVENT_DID_ENTER_FOREGROUND:
        paced = 0;  /* the clocks stood still: do not rush to catch up */
        awake = 0;
        report_frames = 0;
        break;
    default:
        break;
    }
    return true;
}
#endif

/* The keys held on the keyboard, the gamepad, the touch screen and in the script. */
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
#if MOBILE
    keys |= touch_keys(&touch);
#endif
    return keys;
}

static void present(void)
{
    SDL_UpdateTexture(texture, NULL, pixels, GBA_SCREEN_WIDTH * 4);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
#if MOBILE
    TouchBox s = touch.layout.screen;
    SDL_RenderTexture(renderer, texture, NULL, &(SDL_FRect){s.x, s.y, s.w, s.h});
    if (!touch_hidden)
        draw_buttons(touch_keys(&touch));
#else
    SDL_RenderTexture(renderer, texture, NULL, NULL);
#endif
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

/* The frame's samples (host_frame put them in options.sound) go to the sound device. */
static void play_sound(void)
{
    if (!sound)
        return;
    SDL_PutAudioStreamData(sound, options.sound, (int)(options.sound_count * sizeof options.sound[0]));
    int queued = SDL_GetAudioStreamQueued(sound) / (int)sizeof options.sound[0];
    SDL_SetAudioStreamFrequencyRatio(sound, (float)host_sound_speed(queued, SOUND_TARGET));
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
#if MOBILE
    Uint64 waited = SDL_GetTicksNS();
    pace();
    report_rate(waited);
    awake = SDL_GetTicksNS();
#else
    pace();
#endif
    host_frame(&options, rt);
    play_sound();
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
    host_store_save(&options, rt);  /* nothing changes it until a key wakes the game */
    uint16_t before = held_keys();
    while (!closed) {
        SDL_Event event;
        if (SDL_WaitEventTimeout(&event, 100))
            handle(&event);
#if MOBILE
        present();  /* the buttons light up under the fingers */
        SDL_RenderPresent(renderer);
#endif
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
#if MOBILE
    if (!SDL_CreateWindowAndRenderer(title, 0, 0, SDL_WINDOW_FULLSCREEN, &window, &renderer)) {
#else
    int w = GBA_SCREEN_WIDTH * options.scale, h = GBA_SCREEN_HEIGHT * options.scale;
    if (!SDL_CreateWindowAndRenderer(title, w, h, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
#endif
        fprintf(stderr, "error: cannot open a window: %s\n", SDL_GetError());
        return -1;
    }
#if !MOBILE
    SDL_SetRenderLogicalPresentation(renderer, GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT,
                                     SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
#endif
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING,
                                GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT);
    if (!texture) {
        fprintf(stderr, "error: cannot make the screen texture: %s\n", SDL_GetError());
        return -1;
    }
#if MOBILE
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_PIXELART);  /* any size, still crisp */
    lay_out();
    SDL_AddEventWatch(on_app_event, NULL);
#else
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
#endif
    return 0;
}

/* The default sound device, at its own rate, fed by a stream that converts the GBA's. */
static void open_sound(void)
{
    if (options.fast)
        return;
    const SDL_AudioSpec gba = {SDL_AUDIO_S16, 2, GBA_SOUND_RATE};
    SDL_AudioDeviceID device = 0;
    if (SDL_InitSubSystem(SDL_INIT_AUDIO))
        device = SDL_OpenAudioDevice(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, NULL);
    if (device)
        sound = SDL_CreateAudioStream(&gba, NULL);
    if (sound && SDL_BindAudioStream(device, sound))
        return;
    fprintf(stderr, "warning: no sound: %s\n", SDL_GetError());
    SDL_DestroyAudioStream(sound);
    sound = NULL;
    if (device)
        SDL_CloseAudioDevice(device);
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
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
    options.window = 1;
#if MOBILE
    output_to_log();
    char *storage = SDL_GetPrefPath("gbaport", "game");  /* the app's own storage */
    if (storage)  /* the default save file; --save still names another */
        snprintf(options.save_path, sizeof options.save_path, "%sgame.sav", storage);
    SDL_free(storage);
#endif
    int status = host_parse(&options, argc, argv);
#if MOBILE
    if (status == 0) {  /* the ROM is one of the app's assets, which only SDL can read */
        size_t size = 0;
        options.rom = SDL_LoadFile(options.rom_path, &size);
        options.rom_size = (uint32_t)size;
    }
#endif
    if (status == 0)
        status = host_open(&options, &rt, &host);
    if (status != 0)
        return status;
    if (open_window() != 0)
        return 2;
    open_sound();
    GbaEnd end = gba_run(&rt);
    if (options.screenshot)
        screenshot();
    status = host_finish(&options, &rt, end);
#if MOBILE
    if (end == GBA_END_ERROR)  /* the app closes when main returns: say why first */
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "gbaport", rt.error, window);
#endif
    SDL_DestroyAudioStream(sound);
    SDL_Quit();
    return closed ? 0 : status;
}
