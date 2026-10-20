/* How long the EEPROM is busy after a block is written: cycles from the write's DMA until
 * the chip reads ready, timed with timers 0 and 1 counting cycles together, and the reads
 * it took. Both are drawn like the cycles test's counts. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "EEPROM_V124";

#define EEPROM 0x0D000000u
#define VRAM16 ((volatile uint16_t *)0x06000000)

static uint16_t bits[96];

static uint32_t now(void)
{
    for (;;) {
        uint16_t high = REG_TM_CNT_L(1), low = REG_TM_CNT_L(0);
        if (REG_TM_CNT_L(1) == high)
            return (uint32_t)high << 16 | low;
    }
}

static void draw(int slot, uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
}

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    REG_TM_CNT_H(1) = 0x0084;  /* counts timer 0's overflows */
    REG_TM_CNT_H(0) = 0x0080;
    unsigned n = 0;
    bits[n++] = 1;
    bits[n++] = 0;  /* write */
    for (int b = 0; b < 14; b++)
        bits[n++] = 0;  /* block 0 of the 8 KiB chip */
    for (int b = 0; b < 64; b++)
        bits[n++] = b & 1;
    bits[n++] = 0;
    __asm__ volatile("" ::: "memory");
    uint32_t start = now();
    REG_DMA_SAD(3) = (uint32_t)bits;
    REG_DMA_DAD(3) = EEPROM;
    REG_DMA_CNT(3) = n | 0x80000000u;  /* 16-bit units, immediately */
    uint32_t reads = 1;
    while (!(MEM16(EEPROM) & 1))
        reads++;
    draw(0, now() - start);
    draw(1, reads);
    for (int i = 0; i < 2; i++) {  /* two whole pictures with both counts */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
