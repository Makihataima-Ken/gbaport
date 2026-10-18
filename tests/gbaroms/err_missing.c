/* Calls an address where the recompiler found no code. */
#include "testlib.h"

int main(void)
{
    print("before");
    ((void (*)(void))0x08100001)();
    print("after");
    test_end();
    return 0;
}
