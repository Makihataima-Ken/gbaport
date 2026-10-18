/* The BIOS's decompressors on streams that biosref's compressors made (testdata.h): each
 * must give back the original bytes and write nothing past them. The Wram variants
 * decompress into EWRAM, the Vram ones (which must write halfwords) into BG VRAM. */
#include "testlib.h"
#include "testdata.h"

#define EWRAM_OUT 0x02020000u
#define VRAM_OUT 0x06000000u

typedef void (*Call)(const uint8_t *packed, uint32_t dst);

static void lz_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x11, in, o); }
static void lz_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x12, in, o); }
static void huffman(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x13, in, o); }
static void rl_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x14, in, o); }
static void rl_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x15, in, o); }
static void diff8_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x16, in, o); }
static void diff8_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x17, in, o); }
static void diff16(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x18, in, o); }

static void run(const char *name, Call call, const Packed *cases, unsigned count, uint32_t dst)
{
    for (unsigned i = 0; i < count; i++) {
        const Packed *c = &cases[i];
        for (uint32_t k = 0; k < c->size + 4; k += 2)
            MEM16(dst + k) = 0xA5A5;
        call(c->packed, dst);
        for (uint32_t k = 0; k < c->size; k++)
            if (MEM8(dst + k) != c->plain[k]) {
                mismatch(name, i, k, MEM8(dst + k), c->plain[k]);
                break;
            }
        if (MEM16(dst + c->size + 2) != 0xA5A5)
            mismatch(name, i, c->size, MEM16(dst + c->size + 2), 0xA5A5);
    }
    check(name, mismatches() == 0);
}

int main(void)
{
    REG_DISPCNT = 0;  /* tile mode: 0x06000000 is BG VRAM */
    run("LZ77UnCompWram", lz_wram, lz_cases, LZ_COUNT, EWRAM_OUT);
    run("LZ77UnCompVram", lz_vram, lz_cases, LZ_COUNT, VRAM_OUT);
    run("HuffUnComp 8-bit", huffman, huff8_cases, HUFF8_COUNT, EWRAM_OUT);
    run("HuffUnComp 4-bit", huffman, huff4_cases, HUFF4_COUNT, EWRAM_OUT);
    run("RLUnCompWram", rl_wram, rl_cases, RL_COUNT, EWRAM_OUT);
    run("RLUnCompVram", rl_vram, rl_cases, RL_COUNT, VRAM_OUT);
    run("Diff8bitUnFilterWram", diff8_wram, diff8_cases, DIFF8_COUNT, EWRAM_OUT);
    run("Diff8bitUnFilterVram", diff8_vram, diff8_cases, DIFF8_COUNT, VRAM_OUT);
    run("Diff16bitUnFilter", diff16, diff16_cases, DIFF16_COUNT, VRAM_OUT);
    test_end();
    return 0;
}
