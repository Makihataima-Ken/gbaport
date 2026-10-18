/* SoftReset called from an interrupt handler, the way games check the reset key combo in
 * their VBlank handler: the game starts again in system mode. */
#include "testlib.h"

#define MARKER MEM32(0x0203FFF0)
#define MAGIC 0x49525152u

__attribute__((target("arm"), section(".iwram"), noinline)) static void resetting_handler(void)
{
    REG_IF = REG_IE & REG_IF;
    if (MARKER != MAGIC) {
        MARKER = MAGIC;
        __asm__ volatile("svc #0");
    }
}

int main(void)
{
    if (MARKER == MAGIC) {
        REG_IME = 0;  /* SoftReset cleared the IRQ vector; I/O registers kept their values */
        MARKER = 0;
        expect("soft reset from an interrupt handler: system mode", get_cpsr() & 0xFF, 0x1F);
        expect("the reset cleared the IRQ vector", IRQ_VECTOR, 0);
        test_end();
    }
    IRQ_VECTOR = (uint32_t)resetting_handler;
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    REG_IME = 1;
    for (;;) {}
    return 0;
}
