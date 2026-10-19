/* Rotation/scaling backgrounds (modes 1 and 2): VRAM's first 32 KiB holds varied
 * 256-colour tiles with gaps, the second 32 KiB varied one-byte map entries, and BG0 (a
 * text background in mode 1) a tile map of its own. testdata.h sets DISPCNT, BG2CNT and
 * BG3CNT, each background's matrix (PA2..PD2, PA3..PD3) and reference point (X2, Y2, X3,
 * Y3); BG0 uses BGCNT0. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BGCNT(n) REG16(0x04000008 + 2 * (n))
#define REG_BGP(n, i) REG16(0x04000020 + 0x10 * ((n) - 2) + 2 * (i))
#define REG_BGX(n) REG32(0x04000028 + 0x10 * ((n) - 2))
#define REG_BGY(n) REG32(0x0400002C + 0x10 * ((n) - 2))

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

int main(void)
{
    PALETTE[0] = 0x5294;
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x4000; i++) {  /* tiles: 0x0000-0x7FFF, every 8th row clear */
        uint32_t bits = mix(i + 1);
        VRAM[i] = (uint16_t)((i & 0x1C) == 0 ? 0 : bits);
    }
    for (uint32_t i = 0; i < 0x4000; i++)  /* maps: 0x8000-0xFFFF */
        VRAM[0x4000 + i] = (uint16_t)(mix(i * 7 + 3) & 0xFFFF);
    REG_BGCNT(0) = BGCNT0;
    REG_BGCNT(2) = BGCNT2;
    REG_BGCNT(3) = BGCNT3;
    static const int16_t matrix[2][4] = {{PA2, PB2, PC2, PD2}, {PA3, PB3, PC3, PD3}};
    static const int32_t point[2][2] = {{X2, Y2}, {X3, Y3}};
    for (int n = 2; n < 4; n++) {
        for (int i = 0; i < 4; i++)
            REG_BGP(n, i) = (uint16_t)matrix[n - 2][i];
        REG_BGX(n) = (uint32_t)point[n - 2][0];
        REG_BGY(n) = (uint32_t)point[n - 2][1];
    }
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
