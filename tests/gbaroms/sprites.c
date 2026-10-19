/* Sprites: OBJ VRAM holds varied tiles with gaps, BG VRAM a text background (BG0, as
 * BGCNT0 says) to stack them against. testdata.h sets DISPCNT, BGCNT0, the sprites (OBJS:
 * {attr0, attr1, attr2} each, the rest disabled) and the rotation/scaling matrices
 * (MATRICES: {PA, PB, PC, PD} each). In the bitmap modes BG2 shows a mode 3 or 4 picture. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define OAM ((volatile uint16_t *)0x07000000)
#define REG_BGCNT0 REG16(0x04000008)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static const uint16_t objs[][3] = OBJS;
static const int16_t matrices[][4] = MATRICES;

int main(void)
{
    PALETTE[0] = 0x5294;
    for (uint32_t i = 1; i < 512; i++)  /* both palettes */
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x8000; i++) {  /* BG tiles and maps, then OBJ tiles */
        uint32_t bits = mix(i + 1);
        if ((i & 0xF) < 4)  /* the first rows of every tile are partly clear */
            bits &= 0x00F0;
        if (i >= 0x4000 && i < 0x8000)
            bits = mix(i * 5) & 0x0FFF;  /* maps: low tile numbers, no flips, bank 0 */
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t i = 0x8000; i < 0xC000; i++) {
        uint32_t bits = mix(i * 3 + 1);
        if ((i & 0xF) < 4)
            bits &= 0x0F00;
        VRAM[i] = (uint16_t)bits;
    }
    if ((DISPCNT & 7) == 3) {
        for (uint32_t i = 0; i < 240 * 160; i++)
            VRAM[i] = (uint16_t)(i * 37 & 0x7FFF);
    }
    for (int i = 0; i < 128; i++) {
        OAM[i * 4] = 0x0200;  /* disabled */
        OAM[i * 4 + 1] = 0;
        OAM[i * 4 + 2] = 0;
    }
    for (unsigned i = 0; i < sizeof objs / sizeof objs[0]; i++) {
        OAM[i * 4] = objs[i][0];
        OAM[i * 4 + 1] = objs[i][1];
        OAM[i * 4 + 2] = objs[i][2];
    }
    for (unsigned i = 0; i < sizeof matrices / sizeof matrices[0]; i++) {
        for (int k = 0; k < 4; k++)
            OAM[(i * 4 + k) * 4 + 3] = (uint16_t)matrices[i][k];
    }
    REG_BGCNT0 = BGCNT0;
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
