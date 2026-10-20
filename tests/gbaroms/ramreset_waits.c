/* The wait states after RegisterRamReset resets the registers: the BIOS writes WAITCNT = 0
 * like the others, so code in the cartridge runs at the power-on waits again. The
 * iterations of a busy loop from line 20 to line 60 with fast waits, then after the reset,
 * and WAITCNT after it, drawn like the cycles test's counts. */
#include "testlib.h"

#define VRAM16 ((volatile uint16_t *)0x06000000)

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
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    REG_WAITCNT = 0x4317;  /* 3/1 waits, the prefetch buffer on */
    draw(0, loops_from_20_to_60());
    uint32_t in[4] = {0x80}, out[4];
    BIOS_CALL(1, in, out);  /* RegisterRamReset: the registers only */
    REG_DISPCNT = 0x0403;   /* (the reset blanked the screen) */
    draw(1, loops_from_20_to_60());
    draw(2, REG_WAITCNT);
    for (int i = 0; i < 2; i++) {  /* two whole pictures with every count */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
