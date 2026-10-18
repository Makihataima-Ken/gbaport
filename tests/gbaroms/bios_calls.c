/* The BIOS calls the runtime has so far: SoftReset, RegisterRamReset, and SWI numbers the
 * BIOS does not have (ignored). Halt, Stop and the interrupt waits are in interrupts.c. */
#include "testlib.h"

#define MARKER MEM32(0x0203FFF0)
#define MAGIC 0x52534554u

static void ram_reset(uint32_t flags)
{
    register uint32_t r0 __asm__("r0") = flags;
    __asm__ volatile("svc #1" : "+r"(r0) :: "r1", "r2", "r3", "memory");
}

int main(void)
{
    /* SoftReset starts the game again from its entry; the first run sets the stage. */
    if (MARKER != MAGIC) {
        MARKER = MAGIC;
        MEM32(0x02000100) = 0xA5A5A5A5;
        MEM32(0x03006000) = 0x87654321;
        MEM32(0x03007E40) = 0x12345678;
        set_cpsr_control(0x9F);  /* interrupts off: the reset turns them on again */
        __asm__ volatile("svc #0");
        print("FAIL SoftReset returned");
    }
    MARKER = 0;
    expect("soft reset keeps ewram", MEM32(0x02000100), 0xA5A5A5A5);
    expect("soft reset keeps iwram below 0x03007E00", MEM32(0x03006000), 0x87654321);
    expect("soft reset clears 0x03007E00-0x03007FFF", MEM32(0x03007E40), 0);
    expect("soft reset: system mode, interrupts on", get_cpsr() & 0xFF, 0x1F);

    MEM32(0x02000100) = 1;
    MEM32(0x03006000) = 2;
    MEM32(0x03007E40) = 3;
    MEM16(0x05000000) = 4;
    MEM16(0x06000000) = 5;
    MEM16(0x07000000) = 6;
    ram_reset(0x1F);
    expect("ram reset clears ewram", MEM32(0x02000100), 0);
    expect("ram reset clears iwram", MEM32(0x03006000), 0);
    expect("ram reset keeps 0x03007E00-0x03007FFF", MEM32(0x03007E40), 3);
    expect("ram reset clears palette", MEM16(0x05000000), 0);
    expect("ram reset clears vram", MEM16(0x06000000), 0);
    expect("ram reset clears oam", MEM16(0x07000000), 0);

    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = 0x0403;
    REG16(0x04000080) = 0x1234;  /* SOUNDCNT_L */
    ram_reset(0x80);
    expect("register reset: forced blank", REG_DISPCNT, 0x0080);
    expect("register reset clears ie", REG_IE, 0);
    expect("register reset keeps sound registers", REG16(0x04000080), 0x1234);
    ram_reset(0x40);
    expect("sound reset clears sound registers", REG16(0x04000080), 0);

    __asm__ volatile("svc #0x2b");
    check("a SWI the BIOS does not have is ignored", 1);

    test_end();
    return 0;
}
