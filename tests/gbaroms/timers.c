/* Timers: counting, prescalers, reload, overflow interrupts, count-up cascades, and the
 * frame length measured in timer ticks (280896 cycles a frame). */
#include "testlib.h"

enum { ENABLE = 0x80, IRQ = 0x40, COUNT_UP = 0x04, PRESCALE_64 = 1, PRESCALE_1024 = 3 };

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    REG_TM_CNT_L(0) = 0x1234;
    REG_TM_CNT_H(0) = ENABLE | PRESCALE_1024;
    uint16_t started = REG_TM_CNT_L(0);
    expect("a timer starts at its reload value", started, 0x1234);
    expect("control reads back", REG_TM_CNT_H(0), ENABLE | PRESCALE_1024);
    uint16_t a = REG_TM_CNT_L(0);
    for (volatile int i = 0; i < 2000; i++) {}
    uint16_t b = REG_TM_CNT_L(0);
    check("a running timer counts up", b > a);
    REG_TM_CNT_H(0) = 0;
    a = REG_TM_CNT_L(0);
    for (volatile int i = 0; i < 2000; i++) {}
    expect("a stopped timer holds its count", REG_TM_CNT_L(0), a);

    /* A fast timer (a 16-cycle period) read when its overflow is already due but the
     * scheduler has not run yet still reads inside its period. */
    REG_TM_CNT_L(0) = 0xFFF0;
    REG_TM_CNT_H(0) = ENABLE;
    uint32_t lowest = 0xFFFF;
    for (int i = 0; i < 200; i++) {
        uint16_t value = REG_TM_CNT_L(0);
        if (value < lowest)
            lowest = value;
    }
    REG_TM_CNT_H(0) = 0;
    check("a fast timer never reads below its reload value", lowest >= 0xFFF0);

    /* A frame in 1024-cycle ticks: 280896 / 1024 = 274.3. */
    bios_vblank_wait();
    REG_TM_CNT_L(1) = 0;
    REG_TM_CNT_H(1) = ENABLE | PRESCALE_1024;
    bios_vblank_wait();
    uint16_t ticks = REG_TM_CNT_L(1);
    check("a frame is 274-275 ticks at 1024 cycles", ticks >= 274 && ticks <= 275);
    REG_TM_CNT_H(1) = 0;

    /* Overflow interrupts: a period of 23408 cycles is exactly 12 a frame. */
    REG_IE = IRQ_VBLANK | IRQ_TIMER0;
    bios_vblank_wait();
    REG_TM_CNT_L(0) = (uint16_t)(0x10000 - 23408);
    REG_TM_CNT_H(0) = ENABLE | IRQ;
    irq_count[3] = 0;
    for (int i = 0; i < 5; i++)
        bios_vblank_wait();
    uint32_t overflows = irq_count[3];
    check("12 overflow interrupts a frame", overflows >= 59 && overflows <= 61);
    REG_TM_CNT_H(0) = 0;

    /* Count-up: timer 3 counts timer 2's overflows (every 256 cycles: 1097.25 a frame). */
    REG_TM_CNT_L(2) = 0xFF00;
    REG_TM_CNT_L(3) = 0;
    REG_TM_CNT_H(3) = ENABLE | COUNT_UP;
    bios_vblank_wait();
    REG_TM_CNT_H(2) = ENABLE;
    uint16_t c0 = REG_TM_CNT_L(3);
    bios_vblank_wait();
    uint16_t c1 = REG_TM_CNT_L(3);
    REG_TM_CNT_H(2) = 0;
    uint16_t c2 = REG_TM_CNT_L(3);
    check("count-up timer counts overflows", (uint16_t)(c1 - c0) >= 1096 && (uint16_t)(c1 - c0) <= 1098);
    for (volatile int i = 0; i < 2000; i++) {}
    expect("a count-up timer stands still without overflows", REG_TM_CNT_L(3), c2);

    /* A count-up timer that overflows reloads and requests its own interrupt. */
    REG_IE = IRQ_VBLANK | (IRQ_TIMER0 << 3);
    REG_TM_CNT_L(3) = 0xFFF0;  /* 16 overflows of timer 2 */
    REG_TM_CNT_H(3) = 0;
    REG_TM_CNT_H(3) = ENABLE | COUNT_UP | IRQ;
    irq_count[6] = 0;
    REG_TM_CNT_H(2) = ENABLE;
    for (volatile int i = 0; i < 4000; i++) {}
    REG_TM_CNT_H(2) = 0;
    check("cascade overflow interrupt", irq_count[6] >= 1);
    check("cascade reloads", REG_TM_CNT_L(3) >= 0xFFF0);

    test_end();
    return 0;
}
