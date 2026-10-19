/* screen.c - the picture for the host: the renderer's GBA colours as 0x00RRGGBB. */
#include "gba_runtime.h"

void gba_screen(const GbaRuntime *rt, uint32_t *pixels)
{
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++) {
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint32_t color = rt->screen[y][x];
            uint32_t r = color & 31, g = (color >> 5) & 31, b = (color >> 10) & 31;
            r = (r << 3) | (r >> 2);  /* five bits widened to eight */
            g = (g << 3) | (g >> 2);
            b = (b << 3) | (b >> 2);
            pixels[y * GBA_SCREEN_WIDTH + x] = r << 16 | g << 8 | b;
        }
    }
}
