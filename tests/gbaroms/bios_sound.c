/* Calls the BIOS sound driver (SoundDriverMain), which the runtime ignores until sound
 * arrives: the game goes on. */
#include "testlib.h"

int main(void)
{
    print("before");
    __asm__ volatile("svc #0x1c" ::: "r0", "r1", "r2", "r3", "memory");
    print("after");
    test_end();
    return 0;
}
