/* decode.h - ARMv4T instructions decoded as gbaport's analysis decodes them (isa/arm.py,
 * isa/thumb.py): Thumb instructions become the equivalent ARM operation, and anything
 * outside ARMv4T is GBA_OP_UNDEFINED. The interpreter (interp.c) runs what this gives. */
#ifndef GBA_DECODE_H
#define GBA_DECODE_H

#include <stdint.h>

typedef enum {
    /* the ARM data-processing opcodes, in their field's order */
    GBA_OP_AND, GBA_OP_EOR, GBA_OP_SUB, GBA_OP_RSB, GBA_OP_ADD, GBA_OP_ADC, GBA_OP_SBC,
    GBA_OP_RSC, GBA_OP_TST, GBA_OP_TEQ, GBA_OP_CMP, GBA_OP_CMN, GBA_OP_ORR, GBA_OP_MOV,
    GBA_OP_BIC, GBA_OP_MVN,
    GBA_OP_MUL, GBA_OP_MLA, GBA_OP_UMULL, GBA_OP_UMLAL, GBA_OP_SMULL, GBA_OP_SMLAL,
    GBA_OP_LDR, GBA_OP_STR, GBA_OP_LDRB, GBA_OP_STRB, GBA_OP_LDRH, GBA_OP_STRH,
    GBA_OP_LDRSB, GBA_OP_LDRSH, GBA_OP_LDM, GBA_OP_STM, GBA_OP_SWP, GBA_OP_SWPB,
    GBA_OP_B, GBA_OP_BL, GBA_OP_BX, GBA_OP_SWI, GBA_OP_MRS, GBA_OP_MSR, GBA_OP_BL_HI,
    GBA_OP_BL_LO, GBA_OP_UNDEFINED,
} GbaOp;

enum { GBA_COND_AL = 0xE };
enum { GBA_SHIFT_NONE, GBA_SHIFT_LSL, GBA_SHIFT_LSR, GBA_SHIFT_ASR, GBA_SHIFT_ROR, GBA_SHIFT_RRX };
#define GBA_NO_REG (-1)

typedef struct GbaInsn {
    uint32_t addr, raw;
    uint32_t imm;            /* valid when has_imm */
    uint32_t target;         /* valid when has_target: a branch's or PC-relative access's address */
    uint16_t reglist;        /* LDM/STM: bit n = register n */
    uint8_t op, cond, size, thumb;
    uint8_t s, pre, up, writeback, user, spsr, psr_mask, imm_rot;
    uint8_t has_imm, has_target;
    uint8_t shift_kind, shift_amount;  /* GBA_SHIFT_*, immediate amount (LSR/ASR #32 kept) */
    int8_t shift_reg;                  /* register holding the amount, or GBA_NO_REG */
    int8_t rd, rn, rm, rs, rd_hi;      /* GBA_NO_REG when the instruction has none */
} GbaInsn;

void gba_decode_arm(uint32_t word, uint32_t addr, GbaInsn *out);
/* next is the following halfword (a BL prefix pairs with a suffix into one 4-byte BL), or
 * -1 when there is none. */
void gba_decode_thumb(uint32_t halfword, uint32_t addr, int32_t next, GbaInsn *out);

#endif
