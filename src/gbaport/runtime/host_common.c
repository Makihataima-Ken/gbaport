/* host_common.c - the parts of a host that do not depend on a window.
 *
 * The save chip's contents live in a file (default: the ROM's path with .sav): loaded at
 * the start, stored once a second while they change and again at the end. With --audio
 * PATH the sound goes to a WAV file too (16-bit stereo, 32768 samples a second). Scripted key
 * presses (--press FRAME:KEYS) let tests and recordings drive the game: KEYS are names
 * joined with '+' (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or "none", held from
 * the FRAME-th VBlank on. An input file (--input FILE, gbaport/inputs.py) holds any number
 * of them, a "FRAME KEYS" line each. While the game is stopped, time does not pass, so the
 * next scripted press comes at once. With --hashes PATH each frame's picture hash goes to
 * a text file, a line a frame, the same gbaport-mgba writes (`gbaport verify` compares
 * them). */
#define _CRT_SECURE_NO_WARNINGS
#include "host_common.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#pragma comment(lib, "shell32.lib")
#endif

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

/* Paths are UTF-8. Windows hands programs their arguments in UTF-16 and opens files by
 * UTF-16 names, so there the arguments are converted and files opened through the wide
 * functions: any file name works, not just those of the ANSI code page. */
#ifdef _WIN32
static char *utf8(const wchar_t *text)
{
    int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL);
    char *out = malloc(size > 0 ? (size_t)size : 1);
    if (out && WideCharToMultiByte(CP_UTF8, 0, text, -1, out, size, NULL, NULL) <= 0)
        out[0] = 0;
    return out;
}

static wchar_t *wide(const char *text)
{
    int size = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
    wchar_t *out = malloc((size > 0 ? (size_t)size : 1) * sizeof *out);
    if (out && MultiByteToWideChar(CP_UTF8, 0, text, -1, out, size) <= 0)
        out[0] = 0;
    return out;
}

static FILE *open_file(const char *path, const char *mode)
{
    wchar_t *name = wide(path), *how = wide(mode);
    FILE *f = name && how ? _wfopen(name, how) : NULL;
    free(name);
    free(how);
    return f;
}

static void remove_file(const char *path)
{
    wchar_t *name = wide(path);
    if (name)
        _wremove(name);
    free(name);
}

/* The command line as UTF-8 (kept until the program ends: options point into it). */
static char **utf8_arguments(int *argc, char **argv)
{
    int count;
    wchar_t **wargs = CommandLineToArgvW(GetCommandLineW(), &count);
    char **args = wargs ? malloc((size_t)(count + 1) * sizeof *args) : NULL;
    if (!args)
        return argv;
    for (int i = 0; i < count; i++)
        args[i] = utf8(wargs[i]);
    args[count] = NULL;
    LocalFree(wargs);
    *argc = count;
    return args;
}
#else
#define open_file fopen
#define remove_file remove
#endif

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = open_file(path, "rb");
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
    wchar_t *source = wide(from), *target = wide(to);
    int moved = source && target &&
                MoveFileExW(source, target, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    free(source);
    free(target);
    return moved ? 0 : -1;
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
    FILE *f = open_file(temp, "wb");
    int ok = f && fwrite(data, 1, size, f) == size;
    if (f)
        ok = fclose(f) == 0 && ok;
    if (ok && replace_file(temp, o->save_path) == 0) {
        gba_save_stored(rt);
        return;
    }
    if (f)
        remove_file(temp);
    fprintf(stderr, "warning: cannot write the save file %s\n", o->save_path);
}

/* A WAV file's 44-byte header for `samples` 16-bit stereo samples. */
static void wav_header(uint8_t *header, uint32_t samples)
{
    uint32_t data = samples * 4;
    uint32_t fields[][2] = {  /* offset, little-endian 32-bit value */
        {4, 36 + data}, {16, 16}, {20, 1 | 2u << 16}, {24, GBA_SOUND_RATE},
        {28, GBA_SOUND_RATE * 4}, {32, 4 | 16u << 16}, {40, data},
    };
    memcpy(header, "RIFF....WAVEfmt ....................data....", 44);
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        for (int b = 0; b < 4; b++)
            header[fields[i][0] + b] = (uint8_t)(fields[i][1] >> (8 * b));
}

static void write_sound(HostOptions *o)
{
    FILE *f = o->audio_file;
    for (uint32_t i = 0; f && i < o->sound_count; i++) {
        uint8_t bytes[4] = {(uint8_t)o->sound[i][0], (uint8_t)(o->sound[i][0] >> 8),
                            (uint8_t)o->sound[i][1], (uint8_t)(o->sound[i][1] >> 8)};
        fwrite(bytes, 1, sizeof bytes, f);
    }
    o->audio_samples += o->sound_count;
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

/* "FRAME:KEYS" (separator ':') or "FRAME KEYS" (' ') into a press; returns 0, or -1 when
 * it is not one. */
static int parse_press(const char *text, char separator, HostPress *press)
{
    char *end;
    press->frame = strtoul(text, &end, 10);
    if (end == text || *end != separator || *text == '-')
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

/* Adds a press after the others; -1 when it comes before the last one. */
static int add_press(HostOptions *o, HostPress press)
{
    if (o->press_count && press.frame < o->presses[o->press_count - 1].frame)
        return -1;
    if (o->press_count == o->press_capacity) {
        o->press_capacity = o->press_capacity ? 2 * o->press_capacity : 64;
        o->presses = realloc(o->presses, (size_t)o->press_capacity * sizeof *o->presses);
    }
    o->presses[o->press_count++] = press;
    return 0;
}

/* The presses of an input file; returns 0, or -1 after printing what is wrong. */
static int load_input(HostOptions *o, const char *path)
{
    FILE *f = open_file(path, "rb");
    if (!f) {
        fprintf(stderr, "error: cannot read %s\n", path);
        return -1;
    }
    char line[256];
    int ok = 1;
    for (int number = 1; ok && fgets(line, sizeof line, f); number++) {
        if (number == 1 && strncmp(line, "\xEF\xBB\xBF", 3) == 0)
            memmove(line, line + 3, strlen(line + 3) + 1);  /* a UTF-8 byte order mark */
        line[strcspn(line, "#\r\n")] = 0;
        char *start = line + strspn(line, " \t"), *stop = start + strlen(start);
        while (stop > start && (stop[-1] == ' ' || stop[-1] == '\t'))
            *--stop = 0;
        if (!*start)
            continue;  /* a blank line or a comment */
        char *gap = start + strcspn(start, " \t");
        if (*gap) {  /* "FRAME   KEYS": one separator */
            char *keys = gap + strspn(gap, " \t");
            memmove(gap + 1, keys, strlen(keys) + 1);
            *gap = ' ';
        }
        HostPress press;
        ok = parse_press(start, ' ', &press) == 0 && add_press(o, press) == 0;
        if (!ok)
            fprintf(stderr, "error: %s, line %d: expected 'FRAME KEYS', frames in order\n",
                    path, number);
    }
    fclose(f);
    return ok ? 0 : -1;
}

int host_parse(HostOptions *o, int argc, char **argv)
{
    int bad = 0;
#ifdef _WIN32
    argv = utf8_arguments(&argc, argv);
#endif
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
            HostPress press;
            if (parse_press(value, ':', &press) != 0 || add_press(o, press) != 0)
                bad = 1;
            i++;
        } else if (strcmp(arg, "--input") == 0 && value) {
            if (load_input(o, value) != 0)
                return 2;
            i++;
        } else if (strcmp(arg, "--hashes") == 0 && value) {
            o->hashes = value;
            i++;
        } else if (strcmp(arg, "--screenshot") == 0 && value) {
            o->screenshot = value;
            i++;
        } else if (strcmp(arg, "--audio") == 0 && value) {
            o->audio = value;
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
                "[--input FILE] [--registers] [--screenshot PATH] [--audio PATH] "
                "[--hashes PATH]%s\n",
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
    if (o->audio) {
        uint8_t header[44];
        wav_header(header, 0);
        FILE *f = open_file(o->audio, "wb");
        if (!f || fwrite(header, 1, sizeof header, f) != sizeof header) {
            fprintf(stderr, "error: cannot write %s\n", o->audio);
            return 2;
        }
        o->audio_file = f;
    }
    if (o->hashes) {
        o->hashes_file = open_file(o->hashes, "wb");
        if (!o->hashes_file) {
            fprintf(stderr, "error: cannot write %s\n", o->hashes);
            return 2;
        }
    }
    while (o->next_press < o->press_count && o->presses[o->next_press].frame == 0)
        o->script_keys = o->presses[o->next_press++].keys;
    gba_set_keys(rt, o->script_keys);
    return 0;
}

uint64_t host_picture_hash(const GbaRuntime *rt)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++)
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint16_t colour = rt->screen[y][x];
            h = (h ^ (colour & 0xFF)) * 0x100000001B3ull;
            h = (h ^ ((colour >> 8) & 0x7F)) * 0x100000001B3ull;
        }
    return h;
}

void host_frame(HostOptions *o, GbaRuntime *rt)
{
    o->sound_count = gba_audio_take(rt, o->sound, GBA_SOUND_BUFFER);
    write_sound(o);
    if (o->hashes_file)
        fprintf(o->hashes_file, "%016llx\n", (unsigned long long)host_picture_hash(rt));
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
    FILE *f = o->audio_file;
    if (f) {
        o->sound_count = gba_audio_take(rt, o->sound, GBA_SOUND_BUFFER);
        write_sound(o);
        uint8_t header[44];
        wav_header(header, o->audio_samples);
        if (fseek(f, 0, SEEK_SET) != 0 || fwrite(header, 1, sizeof header, f) != sizeof header ||
            fclose(f) != 0)
            fprintf(stderr, "warning: cannot finish the sound file %s\n", o->audio);
        o->audio_file = NULL;
    }
    if (o->hashes_file && fclose(o->hashes_file) != 0)
        fprintf(stderr, "warning: cannot finish %s\n", o->hashes);
    o->hashes_file = NULL;
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

double host_sound_speed(double queued, double target)
{
    double error = (queued - target) / target;
    error = error < -1 ? -1 : error > 1 ? 1 : error;
    return 1.0 + 0.01 * error;  /* at most 1% off: too little to hear as a change of pitch */
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
    FILE *f = open_file(path, "wb");
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
