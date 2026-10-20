/* Calls discovery cannot follow: through a function pointer kept in RAM, to code the test
 * ROM's game.toml does not list (labels in top-level assembly are not ELF functions), in
 * Thumb and in ARM state, and one only a press of A leads to. Clang calls a pointer
 * through a `bx rN` veneer. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global hidden_thumb\n"
    "hidden_thumb:\n"            /* r0 * 3 */
    "    lsls r1, r0, #1\n"
    "    adds r0, r0, r1\n"
    "    bx lr\n"
    "    .global hidden_pressed\n"
    "hidden_pressed:\n"          /* r0 + 1 */
    "    adds r0, r0, #1\n"
    "    bx lr\n"
    "    .arm\n"
    "    .align 2\n"
    "    .global hidden_arm\n"
    "hidden_arm:\n"              /* r0 + 100 */
    "    add r0, r0, #100\n"
    "    bx lr\n"
    "    .thumb\n");

extern char hidden_thumb[], hidden_pressed[], hidden_arm[];
static int (*volatile hook)(int);

int main(void)
{
    hook = (int (*)(int))((uintptr_t)hidden_thumb | 1);
    expect("thumb code through a pointer", hook(5), 15);
    hook = (int (*)(int))(uintptr_t)hidden_arm;
    expect("arm code through a pointer", hook(5), 105);
    for (int frame = 0; frame < 20; frame++) {
        wait_vcount(160);
        if (~REG_KEYINPUT & 1) {  /* A */
            hook = (int (*)(int))((uintptr_t)hidden_pressed | 1);
            expect("code a press of A leads to", hook(5), 6);
            break;
        }
        wait_vcount(161);
    }
    test_end();
    return 0;
}
