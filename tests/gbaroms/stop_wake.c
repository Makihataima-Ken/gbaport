/* Stop sleeps until a key the game asked for (KEYCNT with its interrupt bit, IE) is
 * pressed. The test presses START from frame 30; the clocks stand still while the game
 * is stopped, so the press arrives at once and the screen has not moved on. A key held
 * already wakes it at once; with no press, nothing wakes it and the run ends at the Stop. */
#include "testlib.h"

int main(void)
{
    irq_init();
    REG_IE = IRQ_KEYPAD;
    REG_KEYCNT = 0x4000 | KEY_START;
    print("stopping");
    uint32_t before = REG_VCOUNT;
    __asm__ volatile("svc #3" ::: "r0", "r1", "r2", "r3", "memory");
    uint32_t after = REG_VCOUNT;
    print("woke");
    check("the keypad interrupt woke it", irq_count[12] >= 1);
    expect("start reads as held", REG_KEYINPUT & KEY_START, 0);
    uint32_t lines = after >= before ? after - before : after + 228 - before;
    check("the screen did not move on while stopped", lines < 2);
    REG_KEYCNT = 0;  /* START is still held: it would wake the last Stop at once */
    test_end();
    return 0;
}
