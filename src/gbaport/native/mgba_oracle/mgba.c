/* mgba.c - run a ROM in mGBA: the reference the tests and `gbaport verify` compare with.
 *
 *     gbaport-mgba ROM --frames N [--input FILE] [--picture PATH] [--sound PATH]
 *                  [--hashes PATH]
 *
 * Runs N frames from power-on (mGBA's own BIOS replacement, no BIOS file), holding the keys
 * an input file names (gbaport/inputs.py: "FRAME KEYS" lines, held from the FRAME-th VBlank
 * on). Then:
 * - --picture writes the last picture as 240x160 little-endian 16-bit GBA colours
 *   (0BBBBBGGGGGRRRRR), the form the runtime's tests compare in;
 * - --sound writes every sample mGBA mixes (32768 a second, before it resamples them for
 *   playback) as little-endian 16-bit left and right values;
 * - --hashes writes one line a frame: the picture's 64-bit FNV-1a hash (over its colours
 *   as two bytes each, low byte first), as 16 hex digits, the same the hosts write.
 * mGBA is built with 16-bit colour, so it works in GBA colours throughout, blending in 5
 * bits per channel like the GBA (its partial darkening rounds differently;
 * test_render_effects.py checks that one against GBATEK's formula). mGBA's own messages
 * are dropped. Exit status: 0, or 2 for a bad command line or input file, 3 when mGBA
 * cannot start or a file cannot be read or written. Paths are UTF-8, as in the hosts:
 * Windows hands programs their arguments in UTF-16, so there they are converted, and
 * files are opened by their UTF-16 names (mGBA opens the ROM that way itself). */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>

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
#endif

#include <mgba/core/core.h>
#include <mgba/core/interface.h>
#include <mgba/core/log.h>
#include <mgba/gba/core.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
#error "gbaport-mgba needs mGBA built with 16-bit BGR555 colour (CMakeLists.txt sets COLOR_16_BIT)"
#endif

static FILE *sound;

static void record(struct mAVStream *stream, int16_t left, int16_t right)
{
    (void)stream;
    unsigned char bytes[4] = {left & 0xFF, (left >> 8) & 0xFF, right & 0xFF, (right >> 8) & 0xFF};
    fwrite(bytes, 1, sizeof bytes, sound);
}

static void quiet(struct mLogger *logger, int category, enum mLogLevel level, const char *format,
                  va_list args)
{
    (void)logger, (void)category, (void)level, (void)format, (void)args;
}

/* ---- input files ------------------------------------------------------------------- */

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

typedef struct {
    long frame;
    uint32_t keys;
} Press;

static Press *presses;
static size_t press_count;

/* "A+START" or "none" into KEYINPUT bits; -1 when a name is not a key. */
static long key_bits(const char *names)
{
    if (strcmp(names, "none") == 0)
        return 0;
    long keys = 0;
    while (*names) {
        size_t n = strcspn(names, "+");
        int found = -1;
        for (int i = 0; i < 10; i++)
            if (strlen(KEY_NAMES[i]) == n && strncmp(names, KEY_NAMES[i], n) == 0)
                found = i;
        if (found < 0)
            return -1;
        keys |= 1L << found;
        names += n + (names[n] == '+');
    }
    return keys;
}

static int load_input(const char *path)
{
    FILE *f = open_file(path, "rb");
    if (!f) {
        fprintf(stderr, "error: cannot read %s\n", path);
        return 3;
    }
    char line[256];
    for (int number = 1; fgets(line, sizeof line, f); number++) {
        if (number == 1 && strncmp(line, "\xEF\xBB\xBF", 3) == 0)
            memmove(line, line + 3, strlen(line + 3) + 1);  /* a UTF-8 byte order mark */
        line[strcspn(line, "#\r\n")] = 0;
        char names[200];
        long frame;
        int fields = sscanf(line, "%ld %199s", &frame, names);
        if (fields <= 0)
            continue;  /* a blank line or a comment */
        long keys = fields == 2 ? key_bits(names) : -1;
        if (keys < 0 || frame < 0 || (press_count && frame < presses[press_count - 1].frame)) {
            fprintf(stderr, "error: %s, line %d: expected 'FRAME KEYS', frames in order\n",
                    path, number);
            fclose(f);
            return 2;
        }
        presses = realloc(presses, (press_count + 1) * sizeof *presses);
        presses[press_count++] = (Press){frame, (uint32_t)keys};
    }
    fclose(f);
    return 0;
}

/* ---- pictures ---------------------------------------------------------------------- */

static uint64_t picture_hash(const color_t *pixels, unsigned count)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (unsigned i = 0; i < count; i++) {
        h = (h ^ (pixels[i] & 0xFF)) * 0x100000001B3ull;
        h = (h ^ ((pixels[i] >> 8) & 0x7F)) * 0x100000001B3ull;
    }
    return h;
}

static FILE *open_out(const char *path)
{
    FILE *f = path ? open_file(path, "wb") : NULL;
    if (path && !f)
        fprintf(stderr, "error: cannot write %s\n", path);
    return f;
}

int main(int argc, char **argv)
{
    const char *rom = NULL, *input = NULL, *picture = NULL, *sound_path = NULL, *hashes_path = NULL;
    long frames = -1;
#ifdef _WIN32
    argv = utf8_arguments(&argc, argv);
#endif
    for (int i = 1; i < argc; i++) {
        const char *value = i + 1 < argc ? argv[i + 1] : NULL;
        if (strcmp(argv[i], "--frames") == 0 && value)
            frames = strtol(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--input") == 0 && value)
            input = argv[++i];
        else if (strcmp(argv[i], "--picture") == 0 && value)
            picture = argv[++i];
        else if (strcmp(argv[i], "--sound") == 0 && value)
            sound_path = argv[++i];
        else if (strcmp(argv[i], "--hashes") == 0 && value)
            hashes_path = argv[++i];
        else if (!rom && argv[i][0] != '-')
            rom = argv[i];
        else
            rom = NULL, i = argc;
    }
    if (!rom || frames < 0) {
        fprintf(stderr, "usage: %s ROM --frames N [--input FILE] [--picture PATH] [--sound PATH] "
                "[--hashes PATH]\n", argv[0]);
        return 2;
    }
    int status = input ? load_input(input) : 0;
    if (status)
        return status;
    static struct mLogger logger = {quiet, NULL};
    mLogSetDefaultLogger(&logger);
    struct mCore *core = GBACoreCreate();
    if (!core || !core->init(core)) {
        fprintf(stderr, "error: cannot start mGBA's core\n");
        return 3;
    }
    mCoreInitConfig(core, NULL);
    unsigned width, height;
    core->desiredVideoDimensions(core, &width, &height);
    color_t *pixels = calloc((size_t)width * height, sizeof *pixels);
    core->setVideoBuffer(core, pixels, width);
    if (!mCoreLoadFile(core, rom)) {
        fprintf(stderr, "error: mGBA cannot load %s\n", rom);
        return 3;
    }
    static struct mAVStream stream = {.postAudioFrame = record};
    FILE *hashes = open_out(hashes_path);
    sound = open_out(sound_path);
    if ((sound_path && !sound) || (hashes_path && !hashes))
        return 3;
    if (sound)
        core->setAVStream(core, &stream);
    core->reset(core);
    size_t next = 0;
    uint32_t keys = 0;
    for (long i = 0; i < frames; i++) {
        while (next < press_count && presses[next].frame <= i)
            keys = presses[next++].keys;
        core->setKeys(core, keys);
        core->runFrame(core);
        if (hashes)
            fprintf(hashes, "%016llx\n", (unsigned long long)picture_hash(pixels, width * height));
    }
    if (hashes)
        fclose(hashes);
    if (sound)
        fclose(sound);
    FILE *out = open_out(picture);
    if (picture && !out)
        return 3;
    if (out) {
        for (unsigned i = 0; i < width * height; i++) {
            fputc(pixels[i] & 0xFF, out);
            fputc((pixels[i] >> 8) & 0x7F, out);
        }
        fclose(out);
    }
    core->deinit(core);
    return 0;
}
