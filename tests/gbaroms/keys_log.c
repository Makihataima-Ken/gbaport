/* Prints the keys held whenever they change ("KEYS A+RIGHT", "KEYS none"), for tests
 * that press keys from outside the game (a touch screen, a gamepad). Never ends. */
#include "testlib.h"

static const char *const NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

int main(void)
{
    uint32_t last = 0;
    print("KEYS none");
    for (;;) {
        wait_vcount(160);
        uint32_t keys = ~REG_KEYINPUT & 0x3FF;
        if (keys != last) {
            char text[64];  /* no initializer: that would call memset, which ROMs lack */
            int length = 0;
            for (int k = 0; k < 10; k++) {
                if (!(keys >> k & 1))
                    continue;
                if (length)
                    text[length++] = '+';
                for (const char *c = NAMES[k]; *c; c++)
                    text[length++] = *c;
            }
            text[length] = 0;
            print("KEYS %s", length ? text : "none");
            last = keys;
        }
        wait_vcount(161);
    }
}
