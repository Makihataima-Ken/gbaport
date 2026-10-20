/* Halts until a press of A wakes it through the keypad interrupt, with no VBlank interrupt
 * to end the halt at a frame's end, then shows a colour that changes every frame, so each
 * picture tells which frame it is. */
#include "testlib.h"

#define BACKDROP MEM16(0x05000000)

int main(void)
{
    REG_DISPCNT = 0;  /* mode 0, no layers: the whole picture is the backdrop */
    irq_init();
    REG_KEYCNT = 0x4001;  /* an interrupt when A is pressed */
    REG_IE = IRQ_KEYPAD;
    bios_halt();
    for (unsigned frame = 0;; frame++) {
        wait_vcount(160);
        BACKDROP = frame & 0x7FFF;
        wait_vcount(161);
    }
}
