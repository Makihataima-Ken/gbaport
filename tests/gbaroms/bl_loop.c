/* A bl used as a jump in a loop: calls that never return, as some games make. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global spin_calls\n"
    "    .thumb_func\n"
    "    .type spin_calls, %function\n"
    "spin_calls:\n"
    "    bl spin_calls\n");

void spin_calls(void);

int main(void)
{
    spin_calls();
    return 0;
}
