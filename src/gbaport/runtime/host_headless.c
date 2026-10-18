/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Exit status: 0 the game executed Stop, 2 bad arguments or the wrong ROM, 3 a runtime
 * error (for example code the recompiler did not find), 4 the frame limit was reached. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gba_runtime.h"

static unsigned long frame_limit;

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    if (frame_limit && rt->frames >= frame_limit)
        gba_end(rt, GBA_END_HOST);
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

static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = length > 0 ? malloc((size_t)length) : NULL;
    if (data && fread(data, 1, (size_t)length, f) != (size_t)length) {
        free(data);
        data = NULL;
    }
    fclose(f);
    *size = (uint32_t)length;
    return data;
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    int bad = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc)
            frame_limit = strtoul(argv[++i], NULL, 10);
        else if (!rom_path && argv[i][0] != '-')
            rom_path = argv[i];
        else
            bad = 1;
    }
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N]\n", argv[0]);
        return 2;
    }
    uint32_t size;
    uint8_t *rom = read_file(rom_path, &size);
    if (!rom) {
        fprintf(stderr, "error: cannot read %s\n", rom_path);
        return 2;
    }
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, NULL};
    if (gba_init(&rt, rom, size, &host) != 0) {
        fprintf(stderr, "error: %s\n", rt.error);
        return 2;
    }
    GbaEnd end = gba_run(&rt);
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt.error);
    else if (end == GBA_END_HOST)
        fprintf(stderr, "stopped after %lu frames\n", frame_limit);
    return (int)end;
}
