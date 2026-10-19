/* Draws a known picture for the screen tests, then waits for VBlanks until the run ends.
 * testdata.h sets DISPCNT; test_screen.py works out the expected picture by the same
 * formulas. Only the page DISPCNT shows is drawn. Mode 4 pixels are written in pairs, as
 * byte writes to VRAM would repeat the byte. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    PALETTE[0] = 0x7C00;  /* the backdrop: blue */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(i * 0x0421 & 0x7FFF);
    uint32_t page = DISPCNT & 0x10 ? 0xA000 / 2 : 0;
    for (uint32_t y = 0; y < 160; y++) {
        for (uint32_t x = 0; x < 240; x += 2) {
            if ((DISPCNT & 7) == 3) {
                VRAM[y * 240 + x] = (uint16_t)((x & 31) | (y & 31) << 5);
                VRAM[y * 240 + x + 1] = (uint16_t)(((x + 1) & 31) | (y & 31) << 5);
            } else if ((DISPCNT & 7) == 4) {
                VRAM[page + (y * 240 + x) / 2] = (uint16_t)(((x + y) & 255) | ((x + 1 + y) & 255) << 8);
            } else if (x < 160 && y < 128) {
                VRAM[page + y * 160 + x] = (uint16_t)((x ^ y) & 0x7FFF);
                VRAM[page + y * 160 + x + 1] = (uint16_t)(((x + 1) ^ y) & 0x7FFF);
            }
        }
    }
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
