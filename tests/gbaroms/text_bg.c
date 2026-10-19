/* Text backgrounds: VRAM's first 32 KiB holds varied tiles (with gaps that let layers
 * below show through) and the second 32 KiB varied map entries (tiles, flips, palette
 * banks). testdata.h sets DISPCNT and, for each background, BGnCNT, HOFSn and VOFSn, so a
 * scene picks sizes, colour depths, bases, scrolling and priorities. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BGCNT(n) REG16(0x04000008 + 2 * (n))
#define REG_BGHOFS(n) REG16(0x04000010 + 4 * (n))
#define REG_BGVOFS(n) REG16(0x04000012 + 4 * (n))

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

int main(void)
{
    PALETTE[0] = 0x5294;  /* the backdrop: grey */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x4000; i++) {  /* tiles: 0x0000-0x7FFF */
        uint32_t bits = mix(i + 1);
        if ((i & 0xF) < 3)  /* the first rows of every tile are partly clear */
            bits &= 0x0F0F;
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t i = 0; i < 0x4000; i++)  /* maps: 0x8000-0xFFFF */
        VRAM[0x4000 + i] = (uint16_t)(mix(i * 7 + 3) & 0xFFFF);
    static const uint16_t control[4] = {BGCNT0, BGCNT1, BGCNT2, BGCNT3};
    static const uint16_t hofs[4] = {HOFS0, HOFS1, HOFS2, HOFS3};
    static const uint16_t vofs[4] = {VOFS0, VOFS1, VOFS2, VOFS3};
    for (int n = 0; n < 4; n++) {
        REG_BGCNT(n) = control[n];
        REG_BGHOFS(n) = hofs[n];
        REG_BGVOFS(n) = vofs[n];
    }
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
