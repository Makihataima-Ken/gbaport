/* SRAM: the 8-bit bus, its mirrors, and a signature that must survive into the next run.
 * The library ID string is how gbaport tells the game has SRAM. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";
static const char signature[8] = "GBAPORT";

#define SRAM ((volatile uint8_t *)0x0E000000)

int main(void)
{
    if (SRAM[0x100] == 0xFF) {
        for (int i = 0; i < 8; i++)
            SRAM[0x100 + i] = (uint8_t)signature[i];
        print("WROTE save");
    } else {
        int same = 1;
        for (int i = 0; i < 8; i++)
            same &= SRAM[0x100 + i] == (uint8_t)signature[i];
        check("the save survived", same);
    }

    expect("a blank byte reads 0xFF", SRAM[0x7FFF], 0xFF);
    SRAM[0x10] = 0x5A;
    expect("sram keeps a byte", SRAM[0x10], 0x5A);
    expect("16-bit reads repeat the byte", MEM16(0x0E000010), 0x5A5A);
    expect("32-bit reads repeat the byte", MEM32(0x0E000010), 0x5A5A5A5A);
    expect("sram mirror (32 KiB)", MEM8(0x0E008010), 0x5A);
    expect("sram mirror (0x0F000000)", MEM8(0x0F000010), 0x5A);
    MEM16(0x0E000020) = 0x1234;
    expect("16-bit writes store the low byte", SRAM[0x20], 0x34);
    test_end();
    return 0;
}
