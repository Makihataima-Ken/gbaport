/* HardReset starts the game as if switched off and on: RAM and I/O registers are cleared,
 * only the save chip keeps its contents (here SRAM holds the progress across the reset). */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

#define SRAM ((volatile uint8_t *)0x0E000000)
#define MARKER MEM32(0x02000100)

int main(void)
{
    if (SRAM[0] != 1) {
        SRAM[0] = 1;
        MARKER = 0x48524553;
        REG_IE = IRQ_VBLANK;
        __asm__ volatile("svc #0x26" ::: "memory");
        print("FAIL HardReset returned");
    }
    SRAM[0] = 0xFF;
    expect("hard reset clears ewram", MARKER, 0);
    expect("hard reset clears the i/o registers", REG_IE, 0);
    expect("hard reset starts in system mode", get_cpsr() & 0xFF, 0x1F);
    test_end();
    return 0;
}
