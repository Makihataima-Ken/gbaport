/* The smallest test ROM: one log line, one check, then Stop. */
#include "testlib.h"

int main(void)
{
    print("hello from the GBA");
    expect("arithmetic", 6u * 7u, 42u);
    test_end();
    return 0;
}
