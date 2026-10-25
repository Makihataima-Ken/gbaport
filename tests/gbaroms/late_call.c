/* Calls code the test ROM's game.toml does not list (a label in top-level assembly, as in
 * calls.c) through a pointer, 2000 frames in with no key pressed: long after the last key
 * change of any recording of it. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global hidden_late\n"
    "hidden_late:\n"  /* r0 + 1 */
    "    adds r0, r0, #1\n"
    "    bx lr\n");

extern char hidden_late[];
static int (*volatile hook)(int);

int main(void)
{
    for (int frame = 0; frame < 2000; frame++) {
        wait_vcount(160);
        wait_vcount(161);
    }
    hook = (int (*)(int))((uintptr_t)hidden_late | 1);
    expect("code reached long after the last key change", hook(1), 2);
    test_end();
    return 0;
}
