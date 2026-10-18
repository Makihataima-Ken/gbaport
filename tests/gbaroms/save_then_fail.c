/* Writes the save, then runs into code the recompiler did not find: the save written
 * before the error must still reach the save file. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

int main(void)
{
    MEM8(0x0E000040) = 0x42;
    ((void (*)(void))0x08100001)();
    return 0;
}
