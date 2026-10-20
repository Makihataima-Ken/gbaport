/* What the sound registers read back: SOUNDCNT_X's bits 0-3 say which PSG channels play
 * (a length that runs out clears its bit), the write-only parts of the square registers
 * (lengths, frequencies, restart) read 0, and writes while the sound is off are ignored. */
#include "testlib.h"

#define SOUND1CNT_H REG16(0x04000062)
#define SOUND1CNT_X REG16(0x04000064)
#define SOUND2CNT_L REG16(0x04000068)
#define SOUND2CNT_H REG16(0x0400006C)
#define SOUNDCNT_L REG16(0x04000080)
#define SOUNDCNT_X REG16(0x04000084)

static void wait_frames(int n)
{
    for (int i = 0; i < n; i++) {
        while (REG_VCOUNT == 160)
            ;
        while (REG_VCOUNT != 160)
            ;
    }
}

int main(void)
{
    SOUNDCNT_L = 0x1234;
    expect("off: SOUNDCNT_L ignores writes", SOUNDCNT_L, 0);
    SOUNDCNT_X = 0x0080;
    expect("on, nothing playing", SOUNDCNT_X, 0x0080);
    SOUND1CNT_H = 0xF03E;          /* volume 15, length 64 - 62 = 2 steps */
    SOUND1CNT_X = 0xC000 | 0x700;  /* restart, stop at the end of the length */
    SOUND2CNT_L = 0xA080;
    SOUND2CNT_H = 0x8000 | 0x600;  /* restart, no stop */
    expect("both play", SOUNDCNT_X, 0x0083);
    expect("SOUND1CNT_H reads duty and envelope", SOUND1CNT_H, 0xF000);
    expect("SOUND1CNT_X reads stop only", SOUND1CNT_X, 0x4000);
    expect("SOUND2CNT_H reads stop only", SOUND2CNT_H, 0x0000);
    wait_frames(2);
    expect("channel 1's length ran out", SOUNDCNT_X, 0x0082);
    SOUNDCNT_X = 0;
    expect("off: nothing plays", SOUNDCNT_X, 0);
    expect("off: the square registers are cleared", SOUND2CNT_L, 0);
    test_end();
    return 0;
}
