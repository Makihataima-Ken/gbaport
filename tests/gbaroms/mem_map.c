/* The memory map: mirrors, byte-write rules, ROM open bus, BIOS reads, I/O register rules.
 * Expected values are GBATEK's. */
#include "testlib.h"

int main(void)
{
    /* The BIOS area reads as the last opcode the BIOS fetched: 0xE129F000 after start-up,
     * 0xE3A02004 after a BIOS call (here RegisterRamReset with nothing selected). */
    expect("bios read after start-up", MEM32(0x00000000), 0xE129F000);
    __asm__ volatile("movs r0, #0\n svc #1" ::: "r0", "r1", "r2", "r3", "memory");
    expect("bios read after a SWI", MEM32(0x00000100), 0xE3A02004);
    expect("bios halfword read", MEM16(0x00000002), 0xE3A0);

    MEM32(0x02000010) = 0x11223344;
    expect("ewram mirror (256 KiB)", MEM32(0x02040010), 0x11223344);
    expect("ewram mirror (end of page)", MEM32(0x02FC0010), 0x11223344);
    MEM32(0x03000100) = 0x55667788;
    expect("iwram mirror (32 KiB)", MEM32(0x03008100), 0x55667788);
    MEM32(0x03007FF0) = 0xCAFEF00D;
    expect("iwram top mirror (0x03FFFFxx)", MEM32(0x03FFFFF0), 0xCAFEF00D);

    MEM8(0x05000003) = 0x12;
    expect("palette byte write fills the halfword", MEM16(0x05000002), 0x1212);
    expect("palette mirror", MEM16(0x05000402), 0x1212);

    REG_DISPCNT = 0;  /* tile mode: BG VRAM is 0x06000000-0x0600FFFF */
    MEM8(0x06000001) = 0x34;
    expect("bg vram byte write fills the halfword", MEM16(0x06000000), 0x3434);
    MEM16(0x06010000) = 0xAAAA;
    MEM8(0x06010000) = 0x55;
    expect("obj vram ignores byte writes", MEM16(0x06010000), 0xAAAA);
    REG_DISPCNT = 3;  /* bitmap mode: BG VRAM reaches 0x06013FFF */
    MEM8(0x06010000) = 0x55;
    expect("bitmap mode bg vram takes bytes", MEM16(0x06010000), 0x5555);
    MEM16(0x06014000) = 0xBBBB;
    MEM8(0x06014000) = 0x66;
    expect("bitmap mode obj vram ignores bytes", MEM16(0x06014000), 0xBBBB);
    REG_DISPCNT = 0x80;
    expect("vram mirror of obj vram (0x06018000)", MEM16(0x06018000), 0x5555);
    expect("vram mirror (128 KiB)", MEM16(0x06020000), 0x3434);

    MEM16(0x07000010) = 0x1357;
    MEM8(0x07000010) = 0x99;
    expect("oam ignores byte writes", MEM16(0x07000010), 0x1357);
    expect("oam mirror", MEM16(0x07000410), 0x1357);

    uint32_t first = MEM32(0x08000000);
    expect("rom starts with the entry branch", first >> 24, 0xEA);
    expect("rom mirror (wait state 1)", MEM32(0x0A000000), first);
    expect("rom mirror (wait state 2)", MEM32(0x0C000000), first);
    MEM16(0x08000000) = 0;
    expect("rom ignores writes", MEM32(0x08000000), first);
    expect("open bus past the rom (halfword)", MEM16(0x08FFFFF0), 0xFFF8);
    expect("open bus past the rom (word)", MEM32(0x08FFFFF0), 0xFFF9FFF8);
    expect("open bus past the rom (byte)", MEM8(0x08FFFFF3), 0xFF);
    expect("unmapped region reads 0", MEM32(0x01000000), 0);

    expect("keyinput: no keys pressed", REG_KEYINPUT, 0x03FF);
    expect("keyinput low byte", MEM8(0x04000130), 0xFF);
    expect("keyinput high byte", MEM8(0x04000131), 0x03);
    REG_IE = 0xFFFF;
    expect("ie has 14 bits", REG_IE, 0x3FFF);
    MEM8(0x04000200) = 0x01;
    expect("byte write to ie keeps the other byte", REG_IE, 0x3F01);
    REG_IE = 0;
    REG_IME = 0xFFFF;
    expect("ime has 1 bit", REG_IME, 1);
    REG_IME = 0;
    REG_WAITCNT = 0xFFFF;
    expect("waitcnt bit 15 reads 0", REG_WAITCNT, 0x7FFF);
    REG_WAITCNT = 0;
    REG_DMA_SAD(3) = 0x02000000;
    expect("dma source is write-only", REG_DMA_SAD(3), 0);
    REG16(0x04000008) = 0x1F83;  /* BG0CNT reads back */
    expect("32-bit read of two registers", REG32(0x04000008), 0x00001F83);

    REG_DISPSTAT = 0xFFFF;
    expect("dispstat: writable bits and lyc", REG_DISPSTAT & 0xFF38, 0xFF38);
    REG_DISPSTAT = 0;
    uint16_t line = REG_VCOUNT;
    REG16(0x04000006) = 0x50;
    check("vcount is read-only", REG_VCOUNT < 228 && (REG_VCOUNT == line || REG_VCOUNT == line + 1));

    /* IF: a request stays until written back as 1. Enable the VBlank request but not IE. */
    REG_DISPSTAT = 0x0008;
    wait_vcount(161);
    expect("vblank requested in IF", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IF = 0;
    expect("writing 0 to IF keeps the request", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IF = IRQ_VBLANK;
    expect("writing 1 to IF clears it", REG_IF & IRQ_VBLANK, 0);
    REG_DISPSTAT = 0;

    test_end();
    return 0;
}
