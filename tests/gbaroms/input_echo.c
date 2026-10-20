/* Shows the keys held: at each VBlank the backdrop colour becomes KEYINPUT's pressed bits
 * (a held key sets its bit), so the next picture tells which keys the game saw. */
#include "testlib.h"

#define BACKDROP MEM16(0x05000000)

int main(void)
{
    REG_DISPCNT = 0;  /* mode 0, no layers: the whole picture is the backdrop */
    for (unsigned frame = 0;; frame++) {
        wait_vcount(160);
        /* Bit 15 does not show, but a colour that changes has mGBA draw every line again:
         * it keeps lines nothing has changed for (the start-up picture's white ones). */
        BACKDROP = (~REG_KEYINPUT & 0x3FF) | (~frame & 1) << 15;
        wait_vcount(161);
    }
}
