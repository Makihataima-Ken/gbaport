/* How much an HBlank DMA slows the CPU: the iterations of a busy loop from line 20 to line
 * 60, without and with DMA 0 copying 4 words at every HBlank, drawn like the cycles test's
 * counts. */
#include "testlib.h"

#define VRAM16 ((volatile uint16_t *)0x06000000)
#define EWRAM_WORDS ((volatile uint32_t *)0x02000000)

static uint32_t iwram_words[8] __attribute__((section(".iwram.data")));

static void draw(int slot, uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
}

static uint32_t loops_from_20_to_60(void)
{
    uint32_t loops = 0;
    wait_vcount(20);
    while (REG_VCOUNT != 60)
        loops++;
    return loops;
}

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    draw(0, loops_from_20_to_60());
    wait_vcount(0);
    REG_DMA_SAD(0) = (uint32_t)EWRAM_WORDS;
    REG_DMA_DAD(0) = (uint32_t)iwram_words;
    REG_DMA_CNT(0) = 4 | 0x80000000u | 0x26000000u | 0x00600000u;  /* HBlank, repeat, 32-bit, reload */
    draw(1, loops_from_20_to_60());
    REG_DMA_CNT_H(0) = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with both counts */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
