/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--input FILE]
 *              [--registers] [--screenshot PATH] [--audio PATH] [--hashes PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Keys come only from --press and --input (host_common.c). --registers prints the CPU
 * registers when the run ends; --screenshot writes the last picture as a BMP file; --audio
 * writes the sound as a WAV file; --hashes writes each frame's picture hash.
 * Exit status: 0 the game executed Stop and no scripted press was left to wake it, 2 bad
 * arguments, the wrong ROM or an unusable save file, 3 a runtime error (for example code
 * the recompiler did not find), 4 the frame limit was reached. */
#include <stdio.h>

#include "host_common.h"

static HostOptions options;

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    host_frame(&options, rt);
    gba_set_keys(rt, options.script_keys);
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

static int on_stopped(GbaRuntime *rt, void *user)
{
    (void)user;
    if (!host_script_wake(&options))
        return 0;
    gba_set_keys(rt, options.script_keys);
    return 1;
}

int main(int argc, char **argv)
{
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
    int status = host_parse(&options, argc, argv);
    if (status == 0)
        status = host_open(&options, &rt, &host);
    if (status != 0)
        return status;
    GbaEnd end = gba_run(&rt);
    if (options.screenshot) {
        static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
        gba_screen(&rt, pixels);
        if (host_write_bmp(options.screenshot, pixels) != 0)
            fprintf(stderr, "warning: cannot write %s\n", options.screenshot);
    }
    return host_finish(&options, &rt, end);
}
