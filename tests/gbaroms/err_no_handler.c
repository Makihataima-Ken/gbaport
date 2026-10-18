/* Enables the VBlank interrupt without setting a handler at 0x03007FFC. */
#include "testlib.h"

int main(void)
{
    print("before");
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    REG_IME = 1;
    for (;;) {}
    return 0;
}
