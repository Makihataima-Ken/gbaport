/* decodehost.c - runtime/decode.c's view of instructions, for tests/runtime/test_decode.py.
 *
 * Reads lines from stdin and prints one line of decoded fields per line:
 *     arm WORD ADDR
 *     thumb HALFWORD ADDR NEXT     NEXT is the following halfword, or - for none
 * (numbers in hex). The fields: op cond size raw s rd rn rm rs rd_hi imm target imm_rot
 * shift pre up writeback user reglist spsr psr_mask, with - for a field the instruction
 * does not have, and shift as kind/amount/register. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <string.h>

#include "decode.h"

static const char *const OPS[] = {
    "and", "eor", "sub", "rsb", "add", "adc", "sbc", "rsc", "tst", "teq", "cmp", "cmn", "orr",
    "mov", "bic", "mvn", "mul", "mla", "umull", "umlal", "smull", "smlal", "ldr", "str", "ldrb",
    "strb", "ldrh", "strh", "ldrsb", "ldrsh", "ldm", "stm", "swp", "swpb", "b", "bl", "bx", "swi",
    "mrs", "msr", "bl_hi", "bl_lo", "undefined",
};
static const char *const SHIFTS[] = {"-", "lsl", "lsr", "asr", "ror", "rrx"};

static void reg(int8_t r)
{
    if (r == GBA_NO_REG) printf(" -");
    else printf(" %d", r);
}

int main(void)
{
    char line[128], kind[16], next[16];
    unsigned a, b;
    while (fgets(line, sizeof line, stdin)) {
        GbaInsn i;
        if (sscanf(line, "%15s %x %x %15s", kind, &a, &b, next) >= 3 && strcmp(kind, "arm") == 0) {
            gba_decode_arm(a, b, &i);
        } else if (strcmp(kind, "thumb") == 0) {
            unsigned n;
            gba_decode_thumb(a, b, sscanf(next, "%x", &n) == 1 ? (int32_t)n : -1, &i);
        } else {
            fprintf(stderr, "decodehost: bad line %s", line);
            return 2;
        }
        printf("%s %u %u %08x %u", OPS[i.op], i.cond, i.size, (unsigned)i.raw, i.s);
        reg(i.rd); reg(i.rn); reg(i.rm); reg(i.rs); reg(i.rd_hi);
        if (i.has_imm) printf(" %08x", (unsigned)i.imm); else printf(" -");
        if (i.has_target) printf(" %08x", (unsigned)i.target); else printf(" -");
        printf(" %u", i.imm_rot);
        if (i.shift_kind == GBA_SHIFT_NONE) printf(" -");
        else if (i.shift_reg == GBA_NO_REG) printf(" %s/%u/-", SHIFTS[i.shift_kind], i.shift_amount);
        else printf(" %s/%u/%d", SHIFTS[i.shift_kind], i.shift_amount, i.shift_reg);
        printf(" %u %u %u %u %04x %u %u\n", i.pre, i.up, i.writeback, i.user, i.reglist, i.spsr,
               i.psr_mask);
    }
    return 0;
}
