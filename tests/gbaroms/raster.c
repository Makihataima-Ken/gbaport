/* Raster effects: a picture that changes between lines. Like scene.c, VRAM holds varied
 * tiles and maps; BG0 and BG2 show them. HBlank DMA copies a table of values into TARGET
 * line after line (BG0HOFS: a wave; palette entry 0, the backdrop: stripes of colour),
 * restarted by the VBlank interrupt; with SPLIT set, a
 * VCOUNT interrupt at line 80 switches DISPCNT from mode 0 to mode 1, so BG2 turns from a
 * text background into a rotation/scaling one halfway down. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static uint16_t wave[160];

static void restart_dma(void)
{
    REG_DMA_CNT_H(0) = 0;
    REG_DMA_SAD(0) = (uint32_t)&wave[1];  /* line 0 shows the value set at VBlank */
    REG_DMA_DAD(0) = TARGET;
    REG_DMA_CNT(0) = 1 | (0x8000u | 0x2000u | 0x0200u | 0x0040u) << 16;  /* on, HBlank, repeat, fixed */
}

__attribute__((target("arm"))) static void on_interrupt(void)
{
    uint16_t flags = REG_IF;
    if (flags & IRQ_VBLANK) {
        REG16(TARGET) = wave[0];
        restart_dma();
        REG_DISPCNT = DISPCNT;
    }
    if (flags & IRQ_VCOUNT)
        REG_DISPCNT = (uint16_t)((DISPCNT & ~7) | 1);
    REG_IF = flags;
}

int main(void)
{
    for (uint32_t i = 0; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i + 11) & 0x7FFF);
    for (uint32_t i = 0; i < 0x8000; i++) {
        uint32_t bits = mix(i + 1);
        if (i >= 0x4000)
            bits &= 0xFC7F;  /* map entries: tiles below 128 */
        else if ((i & 0xF) < 4)
            bits &= 0x0F0F;
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t y = 0; y < 160; y++)
        wave[y] = (uint16_t)((y * 7) & 31);
    REG16(0x04000008) = 0x1000 | 1;  /* BG0: screen block 16, priority 1 */
    REG16(0x0400000C) = 0x1404;      /* BG2: char block 1, screen block 20 */
    REG16(0x04000020) = 0xC0;        /* BG2's matrix, used in mode 1 */
    REG16(0x04000026) = 0xC0;
    IRQ_VECTOR = (uint32_t)on_interrupt;
    REG_DISPSTAT = (uint16_t)(0x08 | (SPLIT ? 0x20 | 80 << 8 : 0));
    REG_IE = (uint16_t)(IRQ_VBLANK | (SPLIT ? IRQ_VCOUNT : 0));
    REG_IME = 1;
    restart_dma();
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_halt();
}
