/* render.c - the GBA's picture, drawn one scanline at a time.
 *
 * gba_render_line(rt, y) draws line y into rt->screen when the line's HDraw ends, before
 * the HBlank interrupt and HBlank DMA (as mGBA does), from the registers, VRAM and palette
 * as they are then: a game that changes them between lines gets its raster effects. Each
 * enabled background is drawn into a line of its own; then every pixel takes the colour
 * of the topmost background there (the lower priority number; between equals, the lower
 * background number), or the backdrop, palette entry 0. Forced blank draws white.
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
 * an internal reference point: BGxX/BGxY at the start of every frame and whenever the game
 * writes them, moved by (PB, PD) after every line drawn while the background is on. Along
 * a line, each pixel moves it by (PA, PC). */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define CLEAR 0x8000u  /* no colour here: what is below shows through */

enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT };

typedef struct {
    uint16_t bg[4][W];  /* each background's colours on this line, or CLEAR */
} Layers;

static uint16_t color_at(const uint8_t *memory, uint32_t offset)
{
    return (uint16_t)((memory[offset] | memory[offset + 1] << 8) & 0x7FFF);
}

/* BGxX or BGxY (offset of its low half): a signed 28-bit 20.8 fixed-point value. */
static int32_t reference(const GbaRuntime *rt, uint32_t offset)
{
    uint32_t value = IO(rt, offset) | (uint32_t)IO(rt, offset + 2) << 16;
    return (int32_t)(value << 4) >> 4;
}

void gba_render_frame_start(GbaRuntime *rt)
{
    for (int n = 0; n < 2; n++) {
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
    }
}

void gba_render_reference_write(GbaRuntime *rt, uint32_t offset)
{
    int n = offset >= 0x38;  /* BG3 */
    if ((offset & 0xF) < 0xC)
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
    else
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
}

/* Modes 3-5: BG2 is a bitmap, walked like the rotation/scaling backgrounds. */
static void bitmap_line(const GbaRuntime *rt, uint16_t *out, uint32_t mode)
{
    int32_t x = rt->affine_x[0], y = rt->affine_y[0];
    int32_t dx = (int16_t)IO(rt, 0x20), dy = (int16_t)IO(rt, 0x24);  /* PA, PC */
    uint32_t page = IO(rt, GBA_REG_DISPCNT) & 0x10 ? 0xA000 : 0;
    int width = mode == 5 ? 160 : 240, height = mode == 5 ? 128 : 160;
    for (int i = 0; i < W; i++, x += dx, y += dy) {
        int tx = x >> 8, ty = y >> 8;
        out[i] = CLEAR;
        if (x < 0 || y < 0 || tx >= width || ty >= height)
            continue;
        if (mode == 3) {
            out[i] = color_at(rt->vram, (uint32_t)(ty * 240 + tx) * 2);
        } else if (mode == 4) {
            uint8_t index = rt->vram[page + (uint32_t)(ty * 240 + tx)];
            if (index)
                out[i] = color_at(rt->palette, index * 2u);
        } else {
            out[i] = color_at(rt->vram, page + (uint32_t)(ty * 160 + tx) * 2);
        }
    }
}

/* Every pixel: the topmost background with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned enabled, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    for (int x = 0; x < W; x++) {
        row[x] = backdrop;
        int found = 0;
        for (unsigned priority = 0; priority < 4 && !found; priority++) {
            for (int n = 0; n < 4 && !found; n++) {
                if ((enabled & (1u << n)) && (IO(rt, 0x08 + 2 * n) & 3) == priority &&
                    layers->bg[n][x] != CLEAR) {
                    row[x] = layers->bg[n][x];
                    found = 1;
                }
            }
        }
    }
}

void gba_render_line(GbaRuntime *rt, int y)
{
    uint16_t *row = rt->screen[y];
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    uint32_t mode = control & 7;
    if (control & 0x80) {  /* forced blank */
        for (int x = 0; x < W; x++)
            row[x] = 0x7FFF;
        return;
    }
    static Layers layers;
    unsigned enabled = 0;
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
        bitmap_line(rt, layers.bg[2], mode);
        enabled |= 1u << 2;
    }
    compose(rt, &layers, enabled, row);
    for (int n = 0; n < 2; n++) {
        if (mode != 0 && (control & (0x400u << n))) {
            rt->affine_x[n] += (int16_t)IO(rt, 0x22 + 0x10 * n);  /* PB */
            rt->affine_y[n] += (int16_t)IO(rt, 0x26 + 0x10 * n);  /* PD */
        }
    }
}
