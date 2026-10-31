/* decode.c - the ARM and Thumb decoders, field for field as isa/arm.py and isa/thumb.py. */
#include <string.h>

#include "decode.h"

#define BIT(w, n) (((w) >> (n)) & 1u)
#define FIELD(w, hi, lo) (((w) >> (lo)) & ((1u << ((hi) - (lo) + 1)) - 1u))

static uint32_t ror32(uint32_t v, uint32_t n)
{
    n &= 31;
    return n ? (v >> n) | (v << (32 - n)) : v;
}

static uint32_t sign_extend(uint32_t v, int bits)
{
    uint32_t m = 1u << (bits - 1);
    return (v ^ m) - m;
}

static void start(GbaInsn *out, uint32_t raw, uint32_t addr, int thumb)
{
    memset(out, 0, sizeof *out);
    out->addr = addr;
    out->raw = raw;
    out->thumb = (uint8_t)thumb;
    out->size = thumb ? 2 : 4;
    out->cond = GBA_COND_AL;
    out->pre = out->up = 1;
    out->rd = out->rn = out->rm = out->rs = out->rd_hi = out->shift_reg = GBA_NO_REG;
}

static void set_imm(GbaInsn *out, uint32_t imm) { out->imm = imm; out->has_imm = 1; }
static void set_target(GbaInsn *out, uint32_t t) { out->target = t; out->has_target = 1; }

/* Shift.from_imm_field: LSL #0 is no shift, ROR #0 is RRX, LSR/ASR #0 mean #32. */
static void imm_shift(GbaInsn *out, uint32_t kind, uint32_t amount)
{
    if (amount == 0) {
        if (kind == 0) return;
        if (kind == 3) { out->shift_kind = GBA_SHIFT_RRX; return; }
        out->shift_kind = (uint8_t)(GBA_SHIFT_LSL + kind);
        out->shift_amount = 32;
        return;
    }
    out->shift_kind = (uint8_t)(GBA_SHIFT_LSL + kind);
    out->shift_amount = (uint8_t)amount;
}

static int is_compare(int op) { return op >= GBA_OP_TST && op <= GBA_OP_CMN; }
static int is_move(int op) { return op == GBA_OP_MOV || op == GBA_OP_MVN; }

/* ---- ARM -------------------------------------------------------------------------------- */

static void dp_registers(uint32_t w, GbaInsn *out)
{
    out->s = (uint8_t)BIT(w, 20);
    if (!is_compare(out->op)) out->rd = (int8_t)FIELD(w, 15, 12);
    if (!is_move(out->op)) out->rn = (int8_t)FIELD(w, 19, 16);
}

static void transfer_fields(uint32_t w, GbaInsn *out)
{
    out->rd = (int8_t)FIELD(w, 15, 12);
    out->rn = (int8_t)FIELD(w, 19, 16);
    out->pre = (uint8_t)BIT(w, 24);
    out->up = (uint8_t)BIT(w, 23);
    out->writeback = (uint8_t)(BIT(w, 21) || !out->pre);
}

static void literal_target(GbaInsn *out)
{
    if (out->rn != 15 || !out->pre || out->writeback) return;
    set_target(out, out->addr + 8 + (out->up ? out->imm : 0u - out->imm));
}

static void arm_group0(uint32_t w, GbaInsn *out)
{
    if ((w & 0x0FFFFFF0u) == 0x012FFF10u) {
        out->op = GBA_OP_BX;
        out->rm = (int8_t)(w & 0xF);
        return;
    }
    if ((w & 0x0FC000F0u) == 0x00000090u) {
        int accumulate = (int)BIT(w, 21);
        out->op = accumulate ? GBA_OP_MLA : GBA_OP_MUL;
        out->s = (uint8_t)BIT(w, 20);
        out->rd = (int8_t)FIELD(w, 19, 16);
        if (accumulate) out->rn = (int8_t)FIELD(w, 15, 12);
        out->rs = (int8_t)FIELD(w, 11, 8);
        out->rm = (int8_t)(w & 0xF);
        return;
    }
    if ((w & 0x0F8000F0u) == 0x00800090u) {
        static const uint8_t ops[2][2] = {{GBA_OP_UMULL, GBA_OP_UMLAL}, {GBA_OP_SMULL, GBA_OP_SMLAL}};
        out->op = ops[BIT(w, 22)][BIT(w, 21)];
        out->s = (uint8_t)BIT(w, 20);
        out->rd_hi = (int8_t)FIELD(w, 19, 16);
        out->rd = (int8_t)FIELD(w, 15, 12);
        out->rs = (int8_t)FIELD(w, 11, 8);
        out->rm = (int8_t)(w & 0xF);
        return;
    }
    if ((w & 0x0FB00FF0u) == 0x01000090u) {
        out->op = BIT(w, 22) ? GBA_OP_SWPB : GBA_OP_SWP;
        out->rn = (int8_t)FIELD(w, 19, 16);
        out->rd = (int8_t)FIELD(w, 15, 12);
        out->rm = (int8_t)(w & 0xF);
        return;
    }
    if ((w & 0x90u) == 0x90u) {
        if ((w & 0x60u) == 0) {
            out->op = GBA_OP_UNDEFINED;  /* unallocated multiply space */
            return;
        }
        uint32_t sh = FIELD(w, 6, 5), load = BIT(w, 20);
        int op = -1;
        if (!load && sh == 1) op = GBA_OP_STRH;
        else if (load && sh == 1) op = GBA_OP_LDRH;
        else if (load && sh == 2) op = GBA_OP_LDRSB;
        else if (load && sh == 3) op = GBA_OP_LDRSH;
        int post_writeback = !BIT(w, 24) && BIT(w, 21), immediate = (int)BIT(w, 22);
        if (op < 0 || post_writeback || (!immediate && FIELD(w, 11, 8))) {
            out->op = GBA_OP_UNDEFINED;  /* LDRD/STRD, post-index writeback, SBZ bits */
            return;
        }
        out->op = (uint8_t)op;
        transfer_fields(w, out);
        if (immediate) {
            set_imm(out, (FIELD(w, 11, 8) << 4) | (w & 0xF));
            literal_target(out);
        } else {
            out->rm = (int8_t)(w & 0xF);
        }
        return;
    }
    if ((w & 0x0FBF0FFFu) == 0x010F0000u) {
        out->op = GBA_OP_MRS;
        out->rd = (int8_t)FIELD(w, 15, 12);
        out->spsr = (uint8_t)BIT(w, 22);
        return;
    }
    if ((w & 0x0FB0FFF0u) == 0x0120F000u) {
        out->op = GBA_OP_MSR;
        out->spsr = (uint8_t)BIT(w, 22);
        out->psr_mask = (uint8_t)FIELD(w, 19, 16);
        out->rm = (int8_t)(w & 0xF);
        return;
    }
    if ((w & 0x01900000u) == 0x01000000u) {
        out->op = GBA_OP_UNDEFINED;  /* ARMv5+ miscellaneous space */
        return;
    }
    out->op = (uint8_t)FIELD(w, 24, 21);
    if (BIT(w, 4)) {
        out->shift_kind = (uint8_t)(GBA_SHIFT_LSL + FIELD(w, 6, 5));
        out->shift_reg = (int8_t)FIELD(w, 11, 8);
    } else {
        imm_shift(out, FIELD(w, 6, 5), FIELD(w, 11, 7));
    }
    out->rm = (int8_t)(w & 0xF);
    dp_registers(w, out);
}

static void arm_group1(uint32_t w, GbaInsn *out)
{
    uint32_t rot = FIELD(w, 11, 8), value = ror32(w & 0xFF, rot * 2);
    if ((w & 0x0FB0F000u) == 0x0320F000u) {
        out->op = GBA_OP_MSR;
        out->spsr = (uint8_t)BIT(w, 22);
        out->psr_mask = (uint8_t)FIELD(w, 19, 16);
        set_imm(out, value);
        out->imm_rot = (uint8_t)rot;
        return;
    }
    if ((w & 0x01900000u) == 0x01000000u) {
        out->op = GBA_OP_UNDEFINED;  /* MOVW/MOVT (ARMv6T2) */
        return;
    }
    out->op = (uint8_t)FIELD(w, 24, 21);
    set_imm(out, value);
    out->imm_rot = (uint8_t)rot;
    dp_registers(w, out);
}

static void arm_single(uint32_t w, GbaInsn *out)
{
    int register_offset = (int)BIT(w, 25);
    if (register_offset && BIT(w, 4)) {
        out->op = GBA_OP_UNDEFINED;  /* ARMv6 media space */
        return;
    }
    transfer_fields(w, out);
    out->user = (uint8_t)(!BIT(w, 24) && BIT(w, 21));
    static const uint8_t ops[2][2] = {{GBA_OP_STR, GBA_OP_STRB}, {GBA_OP_LDR, GBA_OP_LDRB}};
    out->op = ops[BIT(w, 20)][BIT(w, 22)];
    if (register_offset) {
        out->rm = (int8_t)(w & 0xF);
        imm_shift(out, FIELD(w, 6, 5), FIELD(w, 11, 7));
    } else {
        set_imm(out, w & 0xFFF);
        literal_target(out);
    }
}

static void arm_block(uint32_t w, GbaInsn *out)
{
    int load = (int)BIT(w, 20);
    out->op = load ? GBA_OP_LDM : GBA_OP_STM;
    out->rn = (int8_t)FIELD(w, 19, 16);
    out->pre = (uint8_t)BIT(w, 24);
    out->up = (uint8_t)BIT(w, 23);
    out->user = (uint8_t)BIT(w, 22);
    out->reglist = (uint16_t)(w & 0xFFFF);
    out->writeback = (uint8_t)(BIT(w, 21) && !(load && (out->reglist >> out->rn) & 1));
}

void gba_decode_arm(uint32_t w, uint32_t addr, GbaInsn *out)
{
    start(out, w, addr, 0);
    if (w >> 28 == 0xF) {
        out->op = GBA_OP_UNDEFINED;
        return;
    }
    out->cond = (uint8_t)(w >> 28);
    switch (FIELD(w, 27, 25)) {
    case 0: arm_group0(w, out); return;
    case 1: arm_group1(w, out); return;
    case 2: case 3: arm_single(w, out); return;
    case 4: arm_block(w, out); return;
    case 5:
        out->op = BIT(w, 24) ? GBA_OP_BL : GBA_OP_B;
        set_target(out, addr + 8 + (sign_extend(w & 0xFFFFFF, 24) << 2));
        return;
    default:
        out->op = (FIELD(w, 27, 25) == 7 && BIT(w, 24)) ? GBA_OP_SWI : GBA_OP_UNDEFINED;
        if (out->op == GBA_OP_SWI) set_imm(out, w & 0xFFFFFF);
        return;
    }
}

/* ---- Thumb ------------------------------------------------------------------------------ */

#define LO(hw, shift) ((int8_t)(((hw) >> (shift)) & 7))

static void undefined(GbaInsn *out, uint32_t hw, uint32_t addr)
{
    start(out, hw, addr, 1);
    out->op = GBA_OP_UNDEFINED;
}

static uint32_t aligned_pc_target(uint32_t addr, uint32_t imm) { return ((addr + 4) & ~3u) + imm; }

void gba_decode_thumb(uint32_t hw, uint32_t addr, int32_t next, GbaInsn *out)
{
    start(out, hw, addr, 1);
    uint32_t top = hw >> 13;
    if (top == 0) {
        if (((hw >> 11) & 3) == 3) {  /* format 2: ADD/SUB Rd, Rs, Rn|#imm3 */
            out->op = hw & 0x0200 ? GBA_OP_SUB : GBA_OP_ADD;
            out->s = 1;
            out->rd = LO(hw, 0);
            out->rn = LO(hw, 3);
            if (hw & 0x0400) set_imm(out, (hw >> 6) & 7);
            else out->rm = LO(hw, 6);
        } else {  /* format 1: LSL/LSR/ASR Rd, Rs, #imm5 */
            out->op = GBA_OP_MOV;
            out->s = 1;
            out->rd = LO(hw, 0);
            out->rm = LO(hw, 3);
            imm_shift(out, (hw >> 11) & 3, (hw >> 6) & 0x1F);
        }
        return;
    }
    if (top == 1) {  /* format 3: MOV/CMP/ADD/SUB Rd, #imm8 */
        static const uint8_t ops[4] = {GBA_OP_MOV, GBA_OP_CMP, GBA_OP_ADD, GBA_OP_SUB};
        out->op = ops[(hw >> 11) & 3];
        int8_t reg = LO(hw, 8);
        if (out->op == GBA_OP_MOV) out->rd = reg;
        else if (out->op == GBA_OP_CMP) out->rn = reg;
        else out->rd = out->rn = reg;
        out->s = 1;
        set_imm(out, hw & 0xFF);
        return;
    }
    if (top == 2) {
        if ((hw >> 10) == 0x10) {  /* format 4: ALU operations */
            uint32_t alu = (hw >> 6) & 0xF;
            int8_t rs = LO(hw, 3), rd = LO(hw, 0);
            out->s = 1;
            switch (alu) {
            case 0: case 1: case 5: case 6: case 12: case 14: {
                static const uint8_t ops[16] = {
                    [0] = GBA_OP_AND, [1] = GBA_OP_EOR, [5] = GBA_OP_ADC, [6] = GBA_OP_SBC,
                    [12] = GBA_OP_ORR, [14] = GBA_OP_BIC};
                out->op = ops[alu];
                out->rd = out->rn = rd;
                out->rm = rs;
                return;
            }
            case 2: case 3: case 4: case 7: {
                static const uint8_t kinds[8] = {
                    [2] = GBA_SHIFT_LSL, [3] = GBA_SHIFT_LSR, [4] = GBA_SHIFT_ASR, [7] = GBA_SHIFT_ROR};
                out->op = GBA_OP_MOV;
                out->rd = out->rm = rd;
                out->shift_kind = kinds[alu];
                out->shift_reg = rs;
                return;
            }
            case 8: case 10: case 11:
                out->op = alu == 8 ? GBA_OP_TST : alu == 10 ? GBA_OP_CMP : GBA_OP_CMN;
                out->rn = rd;
                out->rm = rs;
                return;
            case 9:  /* NEG Rd, Rs == RSBS Rd, Rs, #0 */
                out->op = GBA_OP_RSB;
                out->rd = rd;
                out->rn = rs;
                set_imm(out, 0);
                return;
            case 13:  /* MUL Rd, Rs == MULS Rd, Rs, Rd */
                out->op = GBA_OP_MUL;
                out->rd = rd;
                out->rm = rs;
                out->rs = rd;
                return;
            default:  /* 15: MVN */
                out->op = GBA_OP_MVN;
                out->rd = rd;
                out->rm = rs;
                return;
            }
        }
        if ((hw >> 10) == 0x11) {  /* format 5: hi-register operations, BX */
            uint32_t op_bits = (hw >> 8) & 3;
            int8_t rd = (int8_t)(LO(hw, 0) | ((hw >> 4) & 8)), rm = (int8_t)(LO(hw, 3) | ((hw >> 3) & 8));
            if (op_bits == 0) {
                out->op = GBA_OP_ADD;
                out->rd = out->rn = rd;
                out->rm = rm;
            } else if (op_bits == 1) {
                out->op = GBA_OP_CMP;
                out->s = 1;
                out->rn = rd;
                out->rm = rm;
            } else if (op_bits == 2) {
                out->op = GBA_OP_MOV;
                out->rd = rd;
                out->rm = rm;
            } else if (hw & 0x0080) {
                undefined(out, hw, addr);  /* BLX (ARMv5) */
            } else {
                out->op = GBA_OP_BX;
                out->rm = rm;
            }
            return;
        }
        if ((hw >> 11) == 0x09) {  /* format 6: LDR Rd, [PC, #imm] */
            out->op = GBA_OP_LDR;
            out->rd = LO(hw, 8);
            out->rn = 15;
            set_imm(out, (hw & 0xFF) * 4);
            set_target(out, aligned_pc_target(addr, out->imm));
            return;
        }
        if (hw & 0x0200) {  /* format 8: STRH/LDSB/LDRH/LDSH Rd, [Rb, Ro] */
            static const uint8_t ops[4] = {GBA_OP_STRH, GBA_OP_LDRSB, GBA_OP_LDRH, GBA_OP_LDRSH};
            out->op = ops[(hw >> 10) & 3];
        } else {  /* format 7: STR/STRB/LDR/LDRB Rd, [Rb, Ro] */
            static const uint8_t ops[4] = {GBA_OP_STR, GBA_OP_STRB, GBA_OP_LDR, GBA_OP_LDRB};
            out->op = ops[(hw >> 10) & 3];
        }
        out->rd = LO(hw, 0);
        out->rn = LO(hw, 3);
        out->rm = LO(hw, 6);
        return;
    }
    if (top == 3) {  /* format 9: LDR/STR{B} Rd, [Rb, #imm5] */
        int byte = (hw & 0x1000) != 0, load = (hw & 0x0800) != 0;
        static const uint8_t ops[2][2] = {{GBA_OP_STR, GBA_OP_LDR}, {GBA_OP_STRB, GBA_OP_LDRB}};
        uint32_t offset = (hw >> 6) & 0x1F;
        out->op = ops[byte][load];
        out->rd = LO(hw, 0);
        out->rn = LO(hw, 3);
        set_imm(out, byte ? offset : offset * 4);
        return;
    }
    if (top == 4) {
        out->rd = LO(hw, hw & 0x1000 ? 8 : 0);
        out->op = hw & 0x0800 ? (hw & 0x1000 ? GBA_OP_LDR : GBA_OP_LDRH)
                              : (hw & 0x1000 ? GBA_OP_STR : GBA_OP_STRH);
        if (hw & 0x1000) {  /* format 11: LDR/STR Rd, [SP, #imm8] */
            out->rn = 13;
            set_imm(out, (hw & 0xFF) * 4);
        } else {  /* format 10: LDRH/STRH Rd, [Rb, #imm5] */
            out->rn = LO(hw, 3);
            set_imm(out, ((hw >> 6) & 0x1F) * 2);
        }
        return;
    }
    if (top == 5) {
        if (!(hw & 0x1000)) {  /* format 12: ADD Rd, SP|PC, #imm8 */
            out->op = GBA_OP_ADD;
            out->rd = LO(hw, 8);
            set_imm(out, (hw & 0xFF) * 4);
            if (hw & 0x0800) {
                out->rn = 13;
            } else {
                out->rn = 15;
                set_target(out, aligned_pc_target(addr, out->imm));
            }
            return;
        }
        if ((hw & 0xFF00) == 0xB000) {  /* format 13: ADD/SUB SP, #imm7 */
            out->op = hw & 0x80 ? GBA_OP_SUB : GBA_OP_ADD;
            out->rd = out->rn = 13;
            set_imm(out, (hw & 0x7F) * 4);
            return;
        }
        if ((hw & 0xF600) == 0xB400) {  /* format 14: PUSH/POP */
            uint16_t regs = (uint16_t)(hw & 0xFF);
            out->rn = 13;
            out->writeback = 1;
            if (hw & 0x0800) {
                out->op = GBA_OP_LDM;
                if (hw & 0x0100) regs |= 1u << 15;
                out->pre = 0;
                out->up = 1;
            } else {
                out->op = GBA_OP_STM;
                if (hw & 0x0100) regs |= 1u << 14;
                out->pre = 1;
                out->up = 0;
            }
            out->reglist = regs;
            return;
        }
        undefined(out, hw, addr);
        return;
    }
    if (top == 6) {
        if (!(hw & 0x1000)) {  /* format 15: LDMIA/STMIA Rb!, {Rlist} */
            int8_t rb = LO(hw, 8);
            int load = (hw & 0x0800) != 0;
            out->op = load ? GBA_OP_LDM : GBA_OP_STM;
            out->rn = rb;
            out->pre = 0;
            out->up = 1;
            out->reglist = (uint16_t)(hw & 0xFF);
            out->writeback = (uint8_t)!(load && (out->reglist >> rb) & 1);
            return;
        }
        uint32_t cond = (hw >> 8) & 0xF;  /* format 16/17: B{cond} / SWI */
        if (cond == 0xF) {
            out->op = GBA_OP_SWI;
            set_imm(out, hw & 0xFF);
            return;
        }
        if (cond == 0xE) {
            undefined(out, hw, addr);
            return;
        }
        out->op = GBA_OP_B;
        out->cond = (uint8_t)cond;
        set_target(out, addr + 4 + sign_extend(hw & 0xFF, 8) * 2);
        return;
    }
    uint32_t kind = (hw >> 11) & 3;  /* format 18/19: B / BL */
    if (kind == 0) {
        out->op = GBA_OP_B;
        set_target(out, addr + 4 + sign_extend(hw & 0x7FF, 11) * 2);
    } else if (kind == 1) {
        undefined(out, hw, addr);  /* BLX suffix (ARMv5) */
    } else if (kind == 2) {
        uint32_t high = sign_extend(hw & 0x7FF, 11) << 12;
        if (next >= 0 && ((uint32_t)next & 0xF800) == 0xF800) {
            out->op = GBA_OP_BL;
            out->size = 4;
            out->raw = hw | (uint32_t)next << 16;
            set_target(out, addr + 4 + high + (((uint32_t)next & 0x7FF) << 1));
        } else {
            out->op = GBA_OP_BL_HI;
            set_imm(out, high);
        }
    } else {
        out->op = GBA_OP_BL_LO;
        set_imm(out, (hw & 0x7FF) << 1);
    }
}
