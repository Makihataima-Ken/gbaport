/* The BIOS's memory calls: CpuSet and CpuFastSet (checked here), BitUnPack, ObjAffineSet
 * and BgAffineSet (against biosref, through testdata.h). */
#include "testlib.h"
#include "testdata.h"

#define SRC ((volatile uint8_t *)0x02000000)
#define DST ((volatile uint8_t *)0x02010000)

static void fill_pattern(uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes; i++) {
        SRC[i] = (uint8_t)(i * 7 + 3);
        DST[i] = 0;
    }
}

static int same(uint32_t from, uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes; i++)
        if (DST[i] != SRC[from + i])
            return 0;
    return 1;
}

static int all(uint32_t start, uint32_t bytes, uint8_t value)
{
    for (uint32_t i = start; i < start + bytes; i++)
        if (DST[i] != value)
            return 0;
    return 1;
}

int main(void)
{
    uint32_t in[4] = {0}, out[4];

    fill_pattern(64);
    in[0] = 0x02000000, in[1] = 0x02010000, in[2] = 10;  /* ten halfwords */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet copies halfwords", same(0, 20) && all(20, 4, 0));
    fill_pattern(64);
    in[2] = 5 | (1u << 26);  /* five words */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet copies words", same(0, 20) && all(20, 4, 0));
    fill_pattern(64);
    MEM16(0x02000000) = 0xBEEF;
    in[2] = 6 | (1u << 24);  /* fill six halfwords */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet fills halfwords", MEM16(0x02010000) == 0xBEEF && MEM16(0x0201000A) == 0xBEEF &&
                                     MEM16(0x0201000C) == 0);
    fill_pattern(64);
    in[0] = 0x02000003, in[1] = 0x02010002, in[2] = 2 | (1u << 26);
    BIOS_CALL(0x0B, in, out);
    check("CpuSet aligns word addresses down", same(0, 8) && all(8, 4, 0));
    fill_pattern(64);
    in[0] = 0x00000100, in[1] = 0x02010000, in[2] = 4;
    BIOS_CALL(0x0B, in, out);
    check("CpuSet will not read the BIOS", all(0, 16, 0));

    fill_pattern(64);
    in[0] = 0x02000000, in[1] = 0x02010000, in[2] = 5;  /* rounded up to 8 words */
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet copies blocks of 8 words", same(0, 32) && all(32, 4, 0));
    fill_pattern(64);
    MEM32(0x02000000) = 0x12345678;
    in[2] = 8 | (1u << 24);
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet fills", MEM32(0x02010000) == 0x12345678 && MEM32(0x0201001C) == 0x12345678 &&
                              MEM32(0x02010020) == 0);
    fill_pattern(64);
    in[0] = 0x00000000, in[2] = 8;
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet will not read the BIOS", all(0, 32, 0));

    static uint32_t words[64] __attribute__((aligned(4)));
    for (unsigned i = 0; i < UNPACK_COUNT; i++) {
        const UnpackCase *c = &unpack_cases[i];
        for (unsigned k = 0; k < 64; k++)
            words[k] = 0;
        in[0] = (uint32_t)c->data, in[1] = (uint32_t)words, in[2] = (uint32_t)&c->info;
        BIOS_CALL(0x10, in, out);
        for (unsigned k = 0; k < c->count; k++)
            if (words[k] != c->words[k])
                mismatch("BitUnPack", i, k, words[k], c->words[k]);
    }
    check("BitUnPack", mismatches() == 0);

    static int16_t matrix[4 * 4];
    for (unsigned i = 0; i < OBJ_COUNT; i++) {
        const int16_t *c = obj_cases[i];
        int16_t source[4] = {c[0], c[1], c[2], 0};
        in[0] = (uint32_t)source, in[1] = (uint32_t)matrix, in[2] = 1, in[3] = 2;
        BIOS_CALL(0x0F, in, out);
        for (unsigned k = 0; k < 4; k++)
            if (matrix[k] != c[3 + k])
                mismatch("ObjAffineSet", i, k, (uint16_t)matrix[k], (uint16_t)c[3 + k]);
    }
    check("ObjAffineSet", mismatches() == 0);
    {
        int16_t source[8] = {0x100, 0x100, 0x4000, 0, 0x200, 0x80, 0, 0};
        in[0] = (uint32_t)source, in[1] = 0x07000006, in[2] = 2, in[3] = 8;  /* into OAM */
        BIOS_CALL(0x0F, in, out);
        check("ObjAffineSet writes OAM with a stride of 8",
              MEM16(0x07000006) == 0 && MEM16(0x0700000E) == 0xFF00 && MEM16(0x07000016) == 0x100 &&
              MEM16(0x0700001E) == 0 && MEM16(0x07000026) == 0x200 && MEM16(0x0700003E) == 0x80);
    }

    static int32_t bg[4];
    for (unsigned i = 0; i < BG_COUNT; i++) {
        const BgCase *c = &bg_cases[i];
        in[0] = (uint32_t)&c->source, in[1] = (uint32_t)bg, in[2] = 1;
        BIOS_CALL(0x0E, in, out);
        const int16_t *m = (const int16_t *)bg;
        for (unsigned k = 0; k < 4; k++)
            if (m[k] != c->want_matrix[k])
                mismatch("BgAffineSet", i, k, (uint16_t)m[k], (uint16_t)c->want_matrix[k]);
        if (bg[2] != c->want_x || bg[3] != c->want_y)
            mismatch("BgAffineSet start", i, 0, (uint32_t)bg[2], (uint32_t)c->want_x);
    }
    check("BgAffineSet", mismatches() == 0);

    test_end();
    return 0;
}
