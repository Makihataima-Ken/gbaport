/* DMA: immediate copies and fills, address control, word counts, the end interrupt, and
 * VBlank and HBlank transfers with repeat. */
#include "testlib.h"

enum {
    ENABLE = 0x8000, IRQ = 0x4000, WORDS = 0x0400, REPEAT = 0x0200,
    AT_VBLANK = 0x1000, AT_HBLANK = 0x2000,
    DST_DEC = 0x0020, DST_FIXED = 0x0040, DST_RELOAD = 0x0060, SRC_FIXED = 0x0100,
};

#define EW16(i) MEM16(0x02010000 + 2 * (i))

static void start(int n, uint32_t src, uint32_t dst, uint32_t count, uint32_t control)
{
    REG_DMA_SAD(n) = src;
    REG_DMA_DAD(n) = dst;
    REG_DMA_CNT(n) = count | (control << 16);
}

static void clear(uint32_t halfwords)
{
    for (uint32_t i = 0; i < halfwords; i++)
        EW16(i) = 0;
}

static uint32_t count_value(uint16_t value, uint32_t limit)
{
    uint32_t n = 0;
    while (n < limit && EW16(n) == value)
        n++;
    return n;
}

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    for (int i = 0; i < 16; i++)
        MEM32(0x02000000 + 4 * i) = 0x01010101u * (uint32_t)i;
    start(3, 0x02000000, 0x03004000, 16, ENABLE | WORDS);
    int same = 1;
    for (int i = 0; i < 16; i++)
        same &= MEM32(0x03004000 + 4 * i) == 0x01010101u * (uint32_t)i;
    check("immediate 32-bit copy", same);
    expect("an immediate transfer clears its enable bit", REG_DMA_CNT_H(3) & ENABLE, 0);

    MEM16(0x02000100) = 0xBEEF;
    clear(8);
    start(3, 0x02000100, 0x02010000, 8, ENABLE | SRC_FIXED);
    expect("fixed source fills", count_value(0xBEEF, 9), 8);

    MEM16(0x02000200) = 1, MEM16(0x02000202) = 2, MEM16(0x02000204) = 3;
    clear(3);
    start(3, 0x02000200, 0x02010004, 3, ENABLE | DST_DEC);
    expect("decrementing destination reverses", EW16(0) << 8 | EW16(1) << 4 | EW16(2), 0x321);

    MEM16(0x02000300) = 0x7777;
    clear(0x4001);
    start(0, 0x02000300, 0x02010000, 0, ENABLE | SRC_FIXED);  /* count 0: 0x4000 units */
    expect("word count 0 means 0x4000 on DMA0", count_value(0x7777, 0x4001), 0x4000);

    REG_IE = IRQ_VBLANK | (IRQ_DMA0 << 3);
    irq_count[11] = 0;
    start(3, 0x02000300, 0x02010000, 4, ENABLE | IRQ);
    for (volatile int i = 0; i < 10; i++) {}
    expect("end-of-transfer interrupt", irq_count[11], 1);
    REG_IE = IRQ_VBLANK;

    /* VBlank DMA with repeat: one halfword each VBlank; the destination keeps counting. */
    MEM16(0x02000400) = 0xABCD;
    clear(8);
    bios_vblank_wait();
    start(1, 0x02000400, 0x02010000, 1, ENABLE | REPEAT | AT_VBLANK | SRC_FIXED);
    for (int i = 0; i < 4; i++)
        bios_vblank_wait();
    REG_DMA_CNT_H(1) = 0;
    expect("vblank dma runs once a vblank", count_value(0xABCD, 8), 4);

    /* Reloading the destination: every VBlank writes the same two halfwords. */
    clear(8);
    MEM16(0x02000400) = 0x1111;
    start(1, 0x02000400, 0x02010000, 2, ENABLE | REPEAT | AT_VBLANK | SRC_FIXED | DST_RELOAD);
    for (int i = 0; i < 3; i++)
        bios_vblank_wait();
    REG_DMA_CNT_H(1) = 0;
    expect("destination reload rewrites the same place", count_value(0x1111, 8), 2);

    /* HBlank DMA: once a visible line, 160 a frame. */
    MEM16(0x02000400) = 0x2222;
    clear(240);
    bios_vblank_wait();
    start(2, 0x02000400, 0x02010000, 1, ENABLE | REPEAT | AT_HBLANK | SRC_FIXED);
    bios_vblank_wait();
    REG_DMA_CNT_H(2) = 0;
    expect("hblank dma runs in the 160 visible lines", count_value(0x2222, 240), 160);

    test_end();
    return 0;
}
