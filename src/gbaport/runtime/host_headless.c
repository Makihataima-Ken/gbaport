/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N] [--save PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * The save chip's contents live in PATH (default: the ROM's path with .sav): loaded at the
 * start, stored once a second while they change and again at the end.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
 * file, 3 a runtime error (for example code the recompiler did not find), 4 the frame
 * limit was reached. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gba_runtime.h"

static unsigned long frame_limit;
static char save_path[1024];

static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(length > 0 ? (size_t)length : 1);
    if (data && length > 0 && fread(data, 1, (size_t)length, f) != (size_t)length) {
        free(data);
        data = NULL;
    }
    fclose(f);
    *size = length > 0 ? (uint32_t)length : 0;
    return data;
}

/* Writes the save next to its file, then puts it in place, so a crash cannot leave half. */
static void store_save(GbaRuntime *rt)
{
    uint32_t size;
    uint8_t *data = gba_save_data(rt, &size);
    if (!gba_save_dirty(rt) || size == 0)
        return;
    char temp[sizeof save_path + 4];
    snprintf(temp, sizeof temp, "%s.new", save_path);
    FILE *f = fopen(temp, "wb");
    int ok = f && fwrite(data, 1, size, f) == size;
    if (f)
        ok = fclose(f) == 0 && ok;
    remove(save_path);
    if (ok && rename(temp, save_path) == 0)
        gba_save_stored(rt);
    else
        fprintf(stderr, "warning: cannot write the save file %s\n", save_path);
}

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    if (rt->frames % 60 == 0)
        store_save(rt);
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

static void default_save_path(const char *rom_path)
{
    snprintf(save_path, sizeof save_path, "%s", rom_path);
    char *dot = strrchr(save_path, '.');
    char *slash = strrchr(save_path, '/'), *backslash = strrchr(save_path, '\\');
    if (dot && dot > slash && dot > backslash && strlen(save_path) + 4 < sizeof save_path)
        strcpy(dot, ".sav");
    else
        snprintf(save_path, sizeof save_path, "%s.sav", rom_path);
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    int bad = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc)
            frame_limit = strtoul(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--save") == 0 && i + 1 < argc)
            snprintf(save_path, sizeof save_path, "%s", argv[++i]);
        else if (!rom_path && argv[i][0] != '-')
            rom_path = argv[i];
        else
            bad = 1;
    }
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH]\n", argv[0]);
        return 2;
    }
    if (!save_path[0])
        default_save_path(rom_path);
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
    uint32_t save_size;
    uint8_t *save = read_file(save_path, &save_size);
    if (save && gba_save_load(&rt, save, save_size) != 0) {
        fprintf(stderr, "error: %s: %s (the file was left as it is)\n", save_path, rt.error);
        return 2;
    }
    free(save);
    GbaEnd end = gba_run(&rt);
    store_save(&rt);
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt.error);
    else if (end == GBA_END_HOST)
        fprintf(stderr, "stopped after %lu frames\n", frame_limit);
    return (int)end;
}
