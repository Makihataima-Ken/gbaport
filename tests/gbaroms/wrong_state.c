/* A Thumb call to a `bx pc` veneer that game.toml lists as ARM code, as the sweep can guess
 * one (its alias is an ARM function symbol): the call must run the veneer in Thumb state,
 * where `bx pc` goes on in the ARM code after it. Run as ARM code, its first word
 * (0x00004778, andeq r4, r0, r8, ror r7) would change r4, since Z is set at the call. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .align 2\n"
    "    .thumb\n"
    "veneer:\n"                  /* r0 + 1, through ARM code */
    "    bx pc\n"
    "    .hword 0\n"
    "    .arm\n"
    "    add r0, r0, #1\n"
    "    bx lr\n"
    "    .global veneer_as_arm\n"
    "    .type veneer_as_arm, %function\n"
    "    .set veneer_as_arm, veneer\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global caller\n"
    "    .thumb_func\n"
    "    .type caller, %function\n"
    "caller:\n"                  /* veneer(r0) + 7, with Z set at the call */
    "    push {r4, lr}\n"
    "    movs r4, #7\n"
    "    cmp r4, r4\n"
    "    bl veneer\n"
    "    adds r0, r0, r4\n"
    "    pop {r4}\n"
    "    pop {r1}\n"
    "    bx r1\n");

int caller(int x);

int main(void)
{
    expect("a Thumb call to code game.toml lists as ARM", caller(1), 9);
    test_end();
    return 0;
}
