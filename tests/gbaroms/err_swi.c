/* Calls a BIOS function the runtime does not have yet (Div). */
#include "testlib.h"

int main(void)
{
    print("before");
    __asm__ volatile("svc #6" ::: "r0", "r1", "r2", "r3");
    print("after");
    test_end();
    return 0;
}
