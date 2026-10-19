/* A bitmap mode picture through BG2's rotation/scaling: testdata.h sets DISPCNT, the
 * matrix (PA, PB, PC, PD) and the reference point (X, Y). With WAVE set, an HBlank
 * interrupt moves the reference point's X on every line, a raster effect; with RESTART
 * set, it writes BG2Y halfway down the screen, which restarts the walk from there. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BG2PA REG16(0x04000020)
#define REG_BG2PB REG16(0x04000022)
#define REG_BG2PC REG16(0x04000024)
#define REG_BG2PD REG16(0x04000026)
#define REG_BG2X REG32(0x04000028)
#define REG_BG2Y REG32(0x0400002C)

__attribute__((target("arm"))) static void on_hblank(void)
{
    uint32_t next = REG_VCOUNT + 1;
    if (next == 228)
        next = 0;
    if (WAVE && next < 160)
        REG_BG2X = (uint32_t)(X + (int32_t)((next * 37) & 63) * 64 - 32 * 64);
    if (RESTART && next == 80)
        REG_BG2Y = (uint32_t)Y;
    REG_IF = IRQ_HBLANK;
}

int main(void)
{
    PALETTE[0] = 0x7C00;  /* the backdrop: blue */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(i * 0x0421 & 0x7FFF);
    for (uint32_t y = 0; y < 160; y++) {
        for (uint32_t x = 0; x < 240; x += 2) {
            if ((DISPCNT & 7) == 3) {
                VRAM[y * 240 + x] = (uint16_t)((x & 31) | (y & 31) << 5 | ((x ^ y) & 16) << 6);
                VRAM[y * 240 + x + 1] = (uint16_t)(((x + 1) & 31) | (y & 31) << 5);
            } else if ((DISPCNT & 7) == 4) {
                VRAM[(y * 240 + x) / 2] = (uint16_t)(((x + y) & 255) | ((x * y + 1) & 255) << 8);
            } else if (x < 160 && y < 128) {
                VRAM[y * 160 + x] = (uint16_t)((x ^ y) & 0x7FFF);
                VRAM[y * 160 + x + 1] = (uint16_t)(((x + 1) * 3 ^ y) & 0x7FFF);
            }
        }
    }
    REG_BG2PA = (uint16_t)PA;
    REG_BG2PB = (uint16_t)PB;
    REG_BG2PC = (uint16_t)PC;
    REG_BG2PD = (uint16_t)PD;
    REG_BG2X = (uint32_t)X;
    REG_BG2Y = (uint32_t)Y;
    IRQ_VECTOR = (uint32_t)on_hblank;
    REG_DISPSTAT = WAVE || RESTART ? 0x10 : 0;  /* HBlank interrupt */
    REG_IE = IRQ_HBLANK;
    REG_IME = 1;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_halt();
}
