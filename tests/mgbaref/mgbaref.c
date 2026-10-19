/* mgbaref.c - run a ROM in mGBA and write its picture: the renderer tests' reference.
 *
 *     mgbaref ROM FRAMES OUT
 *
 * Runs FRAMES frames from power-on (mGBA's own BIOS replacement, no BIOS file) and writes
 * the last picture to OUT as 240x160 little-endian 16-bit GBA colours (0BBBBBGGGGGRRRRR),
 * the form the runtime's tests compare in. mGBA is built with 16-bit colour, so it works
 * in GBA colours throughout, blending in 5 bits per channel like the GBA (its partial
 * darkening rounds differently; test_render_effects.py checks that one against GBATEK's
 * formula). mGBA's own messages are dropped. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/gba/core.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
#error "mgbaref needs mGBA built with 16-bit BGR555 colour (CMakeLists.txt sets COLOR_16_BIT)"
#endif

static void quiet(struct mLogger *logger, int category, enum mLogLevel level, const char *format,
                  va_list args)
{
    (void)logger, (void)category, (void)level, (void)format, (void)args;
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s ROM FRAMES OUT\n", argv[0]);
        return 2;
    }
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
    if (!mCoreLoadFile(core, argv[1])) {
        fprintf(stderr, "error: mGBA cannot load %s\n", argv[1]);
        return 2;
    }
    core->reset(core);
    long frames = strtol(argv[2], NULL, 10);
    for (long i = 0; i < frames; i++)
        core->runFrame(core);
    FILE *out = fopen(argv[3], "wb");
    if (!out) {
        fprintf(stderr, "error: cannot write %s\n", argv[3]);
        return 3;
    }
    for (unsigned i = 0; i < width * height; i++) {
        fputc(pixels[i] & 0xFF, out);
        fputc((pixels[i] >> 8) & 0x7F, out);
    }
    fclose(out);
    core->deinit(core);
    return 0;
}
