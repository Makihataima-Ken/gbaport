/* How much an HBlank interrupt slows the CPU: the iterations of a busy loop from line 20 to
 * line 60, without and with the counting IRQ handler running at every HBlank, and how many
 * interrupts it took, drawn like the cycles test's counts. */
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
    irq_init();
    draw(0, loops_from_20_to_60());
    wait_vcount(0);
    REG_DISPSTAT = 0x0010;  /* HBlank interrupts */
    REG_IE = IRQ_HBLANK;
    wait_vcount(19);
    uint32_t before = irq_count[1];
    draw(1, loops_from_20_to_60());
    draw(2, irq_count[1] - before);
    REG_IE = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with every count */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
