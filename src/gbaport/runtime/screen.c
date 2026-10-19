/* screen.c - the picture the host shows, until the scanline renderer (Plan 5) replaces it.
 *
 * Only the bitmap modes are drawn, on BG2 without scaling, rotation or effects: mode 3
 * (240x160, 15-bit colour), mode 4 (240x160, palette indices, two pages) and mode 5
 * (160x128, 15-bit colour, two pages). Everything else shows the backdrop colour (palette
 * entry 0); forced blank shows white. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

static uint32_t rgb(uint32_t color)  /* GBA 0BBBBBGGGGGRRRRR to 0x00RRGGBB */
{
    uint32_t r = color & 31, g = (color >> 5) & 31, b = (color >> 10) & 31;
    r = (r << 3) | (r >> 2);
    g = (g << 3) | (g >> 2);
    b = (b << 3) | (b >> 2);
    return r << 16 | g << 8 | b;
}

static uint32_t get16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }

void gba_screen(const GbaRuntime *rt, uint32_t *pixels)
{
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    uint32_t mode = control & 7, page = control & 0x10 ? 0xA000u : 0;
    uint32_t backdrop = rgb(get16(rt->palette));
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++) {
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint32_t color = backdrop;
            if (control & 0x80) {
                color = 0xFFFFFF;  /* forced blank */
            } else if (control & 0x400) {  /* BG2 on */
                if (mode == 3) {
                    color = rgb(get16(rt->vram + (y * 240 + x) * 2));
                } else if (mode == 4) {
                    uint8_t index = rt->vram[page + y * 240 + x];
                    if (index)
                        color = rgb(get16(rt->palette + index * 2));
                } else if (mode == 5 && x < 160 && y < 128) {
                    color = rgb(get16(rt->vram + page + (y * 160 + x) * 2));
                }
            }
            pixels[y * GBA_SCREEN_WIDTH + x] = color;
        }
    }
}
