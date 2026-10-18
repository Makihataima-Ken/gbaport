/* Rewriting a running timer's control must not lose an overflow that was already due.
 * Recompiled blocks add their cycles up front, so a write often lands just after one. */
#include "testlib.h"

enum { ENABLE = 0x80, IRQ = 0x40 };

/* Writes the running timer 0's control again (same value) a few times. */
__attribute__((noinline)) static void rewrite_control(uint32_t n)
{
    volatile uint32_t sink = n;
    REG_TM_CNT_H(0) = ENABLE | IRQ;
    sink += n * 3;
    REG_TM_CNT_H(0) = ENABLE | IRQ;
    sink += n * 5;
    REG_TM_CNT_H(0) = ENABLE | IRQ;
}

/* Timer 0 overflow interrupts in one frame, with a period of 256 cycles (1097 a frame). */
static uint32_t overflows_in_a_frame(int rewrite)
{
    bios_vblank_wait();
    REG_TM_CNT_L(0) = (uint16_t)(0x10000 - 256);
    REG_TM_CNT_H(0) = ENABLE | IRQ;
    irq_count[3] = 0;
    uint32_t vblanks = irq_count[0];
    for (uint32_t n = 0; irq_count[0] == vblanks; n++)
        if (rewrite)
            rewrite_control(n);
    REG_TM_CNT_H(0) = 0;
    return irq_count[3];
}

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK | IRQ_TIMER0;
    uint32_t quiet = overflows_in_a_frame(0);
    uint32_t noisy = overflows_in_a_frame(1);
    print("256-cycle timer: %u overflow interrupts in a frame, %u while rewriting its control", quiet, noisy);
    /* 1097.25 a frame; the measured window runs a little past the frame on both ends. */
    check("a frame of 256-cycle overflows", quiet >= 1094 && quiet <= 1104);
    check("rewriting a running timer's control keeps its overflows",
          noisy + 4 >= quiet && noisy <= quiet + 4);
    test_end();
    return 0;
}
