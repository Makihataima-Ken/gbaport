/* VBlankIntrWait with an IRQ handler that leaves IME = 0. The BIOS turns IME on again on
 * every pass of its wait loop, so the next interrupt still arrives. */
#include "testlib.h"

__attribute__((target("arm"), section(".iwram"), noinline)) static void ime_off_handler(void)
{
    REG_IME = 0;
    uint16_t flags = REG_IE & REG_IF;
    if (flags & IRQ_VBLANK)
        irq_count[0]++;
    REG_IF = flags;
    BIOS_IF |= flags;
}

int main(void)
{
    IRQ_VECTOR = (uint32_t)ime_off_handler;
    REG_DISPSTAT = 0x0018;  /* request VBlank and HBlank: HBlanks arrive while waiting */
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    REG_IME = 1;
    bios_vblank_wait();
    bios_vblank_wait();
    expect("two vblank waits with a handler that turns IME off", irq_count[0], 2);
    test_end();
    return 0;
}
