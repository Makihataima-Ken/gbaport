/* host_common.c - the parts of a host that do not depend on a window.
 *
 * The save chip's contents live in a file (default: the ROM's path with .sav): loaded at
 * the start, stored once a second while they change and again at the end. Scripted key
 * presses (--press FRAME:KEYS) let tests and recordings drive the game: KEYS are names
 * joined with '+' (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or "none", held from
 * the FRAME-th VBlank on. While the game is stopped, time does not pass, so the next
 * scripted press comes at once. */
#define _CRT_SECURE_NO_WARNINGS
#include "host_common.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
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
        errno = EIO;
    }
    fclose(f);
    *size = length > 0 ? (uint32_t)length : 0;
    return data;
}

/* Puts `from` in the place of `to` in one step; `to` stays as it was if that fails. */
static int replace_file(const char *from, const char *to)
{
#ifdef _WIN32
    return MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) ? 0 : -1;
#else
    return rename(from, to);
#endif
}

/* Writes the save next to its file, then puts it in place: a crash or a failed write
 * leaves the previous save as it was. */
static void store_save(HostOptions *o, GbaRuntime *rt)
{
    uint32_t size;
    uint8_t *data = gba_save_data(rt, &size);
    if (!gba_save_dirty(rt) || size == 0)
        return;
    char temp[sizeof o->save_path + 4];
    snprintf(temp, sizeof temp, "%s.new", o->save_path);
    FILE *f = fopen(temp, "wb");
    int ok = f && fwrite(data, 1, size, f) == size;
    if (f)
        ok = fclose(f) == 0 && ok;
    if (ok && replace_file(temp, o->save_path) == 0) {
        gba_save_stored(rt);
        return;
    }
    if (f)
        remove(temp);
    fprintf(stderr, "warning: cannot write the save file %s\n", o->save_path);
}

static void default_save_path(HostOptions *o)
{
    char *path = o->save_path;
    size_t size = sizeof o->save_path;
    snprintf(path, size, "%s", o->rom_path);
    char *dot = strrchr(path, '.');
    char *slash = strrchr(path, '/'), *backslash = strrchr(path, '\\');
    if (dot && dot > slash && dot > backslash && strlen(path) + 4 < size)
        strcpy(dot, ".sav");
    else
        snprintf(path, size, "%s.sav", o->rom_path);
}

/* "FRAME:KEYS" into a press; returns 0, or -1 when it is not one. */
static int parse_press(const char *text, HostPress *press)
{
    char *end;
    press->frame = strtoul(text, &end, 10);
    if (end == text || *end != ':')
        return -1;
    press->keys = 0;
    const char *name = end + 1;
    if (strcmp(name, "none") == 0)
        return 0;
    while (*name) {
        size_t length = strcspn(name, "+");
        int found = -1;
        for (int k = 0; k < 10; k++)
            if (strlen(KEY_NAMES[k]) == length && strncmp(name, KEY_NAMES[k], length) == 0)
                found = k;
        if (found < 0)
            return -1;
        press->keys |= (uint16_t)(1u << found);
        name += length;
        if (*name == '+')
            name++;
    }
    return press->keys ? 0 : -1;
}

int host_parse(HostOptions *o, int argc, char **argv)
{
    int bad = 0;
    o->scale = 3;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i], *value = i + 1 < argc ? argv[i + 1] : NULL;
        if (strcmp(arg, "--frames") == 0 && value) {
            o->frame_limit = strtoul(value, NULL, 10);
            i++;
        } else if (strcmp(arg, "--save") == 0 && value) {
            snprintf(o->save_path, sizeof o->save_path, "%s", value);
            i++;
        } else if (strcmp(arg, "--press") == 0 && value) {
            HostPress *press = &o->presses[o->press_count];
            if (o->press_count == HOST_MAX_PRESSES || parse_press(value, press) != 0 ||
                (o->press_count && press->frame < press[-1].frame))
                bad = 1;
            else
                o->press_count++;
            i++;
        } else if (strcmp(arg, "--screenshot") == 0 && value) {
            o->screenshot = value;
            i++;
        } else if (strcmp(arg, "--registers") == 0) {
            o->registers = 1;
        } else if (o->window && strcmp(arg, "--scale") == 0 && value) {
            o->scale = atoi(value);
            bad |= o->scale < 1 || o->scale > 16;
            i++;
        } else if (o->window && strcmp(arg, "--fast") == 0) {
            o->fast = 1;
        } else if (!o->rom_path && arg[0] != '-') {
            o->rom_path = arg;
        } else {
            bad = 1;
        }
    }
    if (!o->rom_path || bad) {
        fprintf(stderr,
                "usage: %s ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... "
                "[--registers] [--screenshot PATH]%s\n",
                argv[0], o->window ? " [--scale N] [--fast]" : "");
        return 2;
    }
    if (!o->save_path[0])
        default_save_path(o);
    return 0;
}

int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host)
{
    uint32_t size;
    o->rom = read_file(o->rom_path, &size);
    if (!o->rom) {
        fprintf(stderr, "error: cannot read %s\n", o->rom_path);
        return 2;
    }
    if (gba_init(rt, o->rom, size, host) != 0) {
        fprintf(stderr, "error: %s\n", rt->error);
        return 2;
    }
    uint32_t save_size;
    uint8_t *save = read_file(o->save_path, &save_size);
    if (!save && errno != ENOENT) {
        fprintf(stderr, "error: cannot read the save file %s (it was left as it is)\n", o->save_path);
        return 2;
    }
    if (save && gba_save_load(rt, save, save_size) != 0) {
        fprintf(stderr, "error: %s: %s (the file was left as it is)\n", o->save_path, rt->error);
        return 2;
    }
    free(save);
    while (o->next_press < o->press_count && o->presses[o->next_press].frame == 0)
        o->script_keys = o->presses[o->next_press++].keys;
    gba_set_keys(rt, o->script_keys);
    return 0;
}

void host_frame(HostOptions *o, GbaRuntime *rt)
{
    while (o->next_press < o->press_count && o->presses[o->next_press].frame <= rt->frames)
        o->script_keys = o->presses[o->next_press++].keys;
    if (rt->frames % 60 == 0)
        store_save(o, rt);
    if (o->frame_limit && rt->frames >= o->frame_limit)
        gba_end(rt, GBA_END_HOST);
}

int host_script_wake(HostOptions *o)
{
    if (o->next_press == o->press_count)
        return 0;
    o->script_keys = o->presses[o->next_press++].keys;
    return 1;
}

int host_finish(HostOptions *o, GbaRuntime *rt, GbaEnd end)
{
    store_save(o, rt);
    if (o->registers) {
        GbaCtx *ctx = &rt->cpu;
        fprintf(stderr, "registers");
        for (int i = 0; i < 15; i++)
            fprintf(stderr, " r%d=%08x", i, (unsigned)ctx->r[i]);
        fprintf(stderr, " cpsr=%08x\n", (unsigned)gba_cpsr(ctx));
    }
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt->error);
    else if (end == GBA_END_HOST && o->frame_limit && rt->frames >= o->frame_limit)
        fprintf(stderr, "stopped after %lu frames\n", o->frame_limit);
    return (int)end;
}

int host_write_bmp(const char *path, const uint32_t *pixels)
{
    enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT, ROW = W * 3, DATA = ROW * H };
    uint8_t header[54] = {'B', 'M'};
    uint32_t fields[][2] = {  /* offset, value: little-endian 32-bit fields */
        {2, 54 + DATA}, {10, 54}, {14, 40}, {18, W}, {22, H}, {34, DATA},
    };
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        for (int b = 0; b < 4; b++)
            header[fields[i][0] + b] = (uint8_t)(fields[i][1] >> (8 * b));
    header[26] = 1;   /* planes */
    header[28] = 24;  /* bits per pixel */
    FILE *f = fopen(path, "wb");
    if (!f)
        return -1;
    fwrite(header, 1, sizeof header, f);
    for (int y = H - 1; y >= 0; y--) {  /* bottom row first */
        uint8_t row[ROW];
        for (int x = 0; x < W; x++) {
            uint32_t c = pixels[y * W + x];
            row[x * 3] = (uint8_t)c;
            row[x * 3 + 1] = (uint8_t)(c >> 8);
            row[x * 3 + 2] = (uint8_t)(c >> 16);
        }
        fwrite(row, 1, ROW, f);
    }
    return fclose(f) == 0 ? 0 : -1;
}
