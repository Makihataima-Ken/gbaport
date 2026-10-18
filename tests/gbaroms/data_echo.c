/* Prints a value from testdata.h, which the Python test writes. */
#include "testlib.h"
#include "testdata.h"

int main(void)
{
    print("%s", ECHO);
    test_end();
    return 0;
}
