/* interp.c - the interpreter: what lift/semantics.py and lift/function.py would have
 * generated for each instruction, run as it is decoded (decode.c). Each comment names the
 * lifter's rule it follows, so the two stay alike: a game must draw the same pictures
 * whether a piece of its code runs recompiled or here. */
#include "interp.h"

#include "decode.h"

#define PC 15
#define LR 14

static int is_load(int op) { return op == GBA_OP_LDR || op == GBA_OP_LDRB || op == GBA_OP_LDRH ||
                                    op == GBA_OP_LDRSB || op == GBA_OP_LDRSH; }
static int is_store(int op) { return op == GBA_OP_STR || op == GBA_OP_STRB || op == GBA_OP_STRH; }
static int is_dp(int op) { return op <= GBA_OP_MVN; }
static int is_compare(int op) { return op >= GBA_OP_TST && op <= GBA_OP_CMN; }
static int is_logical(int op)
{
    return op == GBA_OP_AND || op == GBA_OP_EOR || op == GBA_OP_TST || op == GBA_OP_TEQ ||
           op == GBA_OP_ORR || op == GBA_OP_MOV || op == GBA_OP_BIC || op == GBA_OP_MVN;
}
static int is_long_multiply(int op) { return op >= GBA_OP_UMULL && op <= GBA_OP_SMLAL; }

/* analysis/flow.py writes_pc */
static int writes_pc(const GbaInsn *i)
{
    if (i->op == GBA_OP_BX) return 1;
    if (is_dp(i->op) && !is_compare(i->op)) return i->rd == PC;
    if (i->op == GBA_OP_LDR) return i->rd == PC;
    if (i->op == GBA_OP_LDM) return (i->reglist >> PC) & 1 || !i->reglist;
    return 0;
}

/* function.py _leaves and _accesses */
static int leaves(const GbaInsn *i)
{
    return i->op == GBA_OP_B || i->op == GBA_OP_BL || i->op == GBA_OP_BL_LO || writes_pc(i);
}

static int accesses(const GbaInsn *i)
{
    return is_load(i->op) || is_store(i->op) || i->op == GBA_OP_LDM || i->op == GBA_OP_STM ||
           i->op == GBA_OP_SWP || i->op == GBA_OP_SWPB || i->op == GBA_OP_SWI;
}

/* semantics.py restores_cpsr */
static int restores_cpsr(const GbaInsn *i)
{
    if (is_compare(i->op)) return !i->thumb && ((i->raw >> 12) & 0xF) == PC;
    if (is_dp(i->op)) return i->s && i->rd == PC;
    return i->op == GBA_OP_LDM && i->user && ((i->reglist >> PC) & 1);
}

/* semantics.py cycles: (internal cycles, S fetches, N fetches) when the condition holds */
static void static_cost(const GbaInsn *i, uint32_t *k, uint32_t *s, uint32_t *n)
{
    *k = 1, *s = 1, *n = 0;
    if (i->thumb && i->op == GBA_OP_BL && i->size == 4)
        *k = 2, *s = 2;
    if (is_load(i->op) || is_store(i->op) || i->op == GBA_OP_LDM || i->op == GBA_OP_STM ||
        i->op == GBA_OP_SWP || i->op == GBA_OP_SWPB || i->op == GBA_OP_MUL || i->op == GBA_OP_MLA ||
        is_long_multiply(i->op))
        *s -= 1, *n += 1;
    if (i->shift_reg != GBA_NO_REG)
        *k += 1;
}

/* function.py _cost_expr: k cycles plus s sequential and n nonsequential fetches of code at addr */
static uint32_t cost(const GbaCtx *ctx, uint32_t k, uint32_t s, uint32_t n, uint32_t addr, int thumb)
{
    uint32_t r = gba_region(addr);
    return k + s * (thumb ? ctx->s16[r] : ctx->s32[r]) + n * (thumb ? ctx->n16[r] : ctx->n32[r]);
}

static int holds(const GbaCtx *ctx, int cond)
{
    switch (cond) {
    case 0x0: return GBA_EQ;
    case 0x1: return GBA_NE;
    case 0x2: return GBA_CS;
    case 0x3: return GBA_CC;
    case 0x4: return GBA_MI;
    case 0x5: return GBA_PL;
    case 0x6: return GBA_VS;
    case 0x7: return GBA_VC;
    case 0x8: return GBA_HI;
    case 0x9: return GBA_LS;
    case 0xA: return GBA_GE;
    case 0xB: return GBA_LT;
    case 0xC: return GBA_GT;
    case 0xD: return GBA_LE;
    default: return 1;
    }
}

/* semantics.py read: r15 reads the instruction's address + 8 (ARM) or + 4 (Thumb) */
static uint32_t pc_value(const GbaInsn *i) { return i->addr + (i->thumb ? 4u : 8u); }

static uint32_t rd_(const GbaCtx *ctx, const GbaInsn *i, int n, uint32_t extra)
{
    return n == PC ? pc_value(i) + extra : ctx->r[n];
}

/* semantics.py stall_pc: the pc mGBA's prefetch model sees, 0 outside the cartridge */
static uint32_t stall_pc(const GbaInsn *i)
{
    uint32_t top = i->addr >> 24;
    return top >= 0x08 && top <= 0x0D ? i->addr + (i->thumb ? 4u : 8u) : 0u;
}

static uint32_t shifted(GbaCtx *ctx, int kind, uint32_t v, uint32_t amount, int carry)
{
    switch (kind) {
    case GBA_SHIFT_LSL: return carry ? gba_lsl_c(v, amount, &ctx->c) : gba_lsl(v, amount);
    case GBA_SHIFT_LSR: return carry ? gba_lsr_c(v, amount, &ctx->c) : gba_lsr(v, amount);
    case GBA_SHIFT_ASR: return carry ? gba_asr_c(v, amount, &ctx->c) : gba_asr(v, amount);
    case GBA_SHIFT_ROR: return carry ? gba_ror_c(v, amount, &ctx->c) : gba_ror(v, amount);
    default: return carry ? gba_rrx_c(v, &ctx->c) : gba_rrx(v, ctx->c);
    }
}

/* semantics.py _operand2 */
static uint32_t operand2(GbaCtx *ctx, const GbaInsn *i, int carry, uint32_t extra)
{
    if (i->has_imm)
        return carry && i->imm_rot ? gba_imm_c(i->imm, &ctx->c) : i->imm;
    uint32_t v = rd_(ctx, i, i->rm, extra);
    if (i->shift_kind == GBA_SHIFT_NONE)
        return v;
    uint32_t amount = i->shift_reg != GBA_NO_REG ? (ctx->r[i->shift_reg] & 0xFFu) : i->shift_amount;
    return shifted(ctx, i->shift_kind, v, amount, carry);
}

/* Writes to r15 go to t, as in lifted code. */
static void put(GbaCtx *ctx, int n, uint32_t v, uint32_t *t)
{
    if (n == PC) *t = v;
    else ctx->r[n] = v;
}

/* semantics.py _data_processing */
static void data_processing(GbaCtx *ctx, const GbaInsn *i, uint32_t *t)
{
    int op = i->op;
    if (op == GBA_OP_ADD && i->rn == PC && i->has_target) {  /* Thumb ADR */
        put(ctx, i->rd, i->target, t);
        return;
    }
    uint32_t extra = i->shift_reg != GBA_NO_REG && !i->thumb ? 4u : 0u;
    int exception_return = restores_cpsr(i);
    int flags = i->s && !exception_return;
    uint32_t op2 = operand2(ctx, i, flags && is_logical(op), extra);
    uint32_t a = (op == GBA_OP_MOV || op == GBA_OP_MVN) ? 0 : rd_(ctx, i, i->rn, extra);
    uint32_t value;
    switch (op) {
    case GBA_OP_AND: case GBA_OP_TST: value = a & op2; break;
    case GBA_OP_EOR: case GBA_OP_TEQ: value = a ^ op2; break;
    case GBA_OP_ORR: value = a | op2; break;
    case GBA_OP_BIC: value = a & ~op2; break;
    case GBA_OP_MOV: value = op2; break;
    case GBA_OP_MVN: value = ~op2; break;
    default: {
        uint32_t x, y, carry_in;
        switch (op) {
        case GBA_OP_ADD: case GBA_OP_CMN: x = a, y = op2, carry_in = 0; break;
        case GBA_OP_ADC: x = a, y = op2, carry_in = ctx->c; break;
        case GBA_OP_SUB: case GBA_OP_CMP: x = a, y = ~op2, carry_in = 1; break;
        case GBA_OP_SBC: x = a, y = ~op2, carry_in = ctx->c; break;
        case GBA_OP_RSB: x = op2, y = ~a, carry_in = 1; break;
        default: x = op2, y = ~a, carry_in = ctx->c; break;  /* RSC */
        }
        value = flags ? gba_addc(ctx, x, y, carry_in) : x + y + carry_in;
        flags = 0;  /* gba_addc set them */
    }
    }
    if (flags)
        gba_nz(ctx, value);
    if (!is_compare(op))
        put(ctx, i->rd, value, t);
    if (exception_return)
        gba_restore_cpsr(ctx);
}

/* semantics.py _multiply and _long_multiply */
static void multiply(GbaCtx *ctx, const GbaInsn *i)
{
    if (i->op == GBA_OP_MUL || i->op == GBA_OP_MLA) {
        gba_mul_wait(ctx, rd_(ctx, i, i->rs, 0), 1, i->op == GBA_OP_MLA, stall_pc(i));
        uint32_t value = rd_(ctx, i, i->rm, 0) * rd_(ctx, i, i->rs, 0);
        if (i->op == GBA_OP_MLA)
            value += rd_(ctx, i, i->rn, 0);
        if (i->s)
            gba_nz(ctx, value);
        ctx->r[i->rd] = value;
        return;
    }
    int is_signed = i->op == GBA_OP_SMULL || i->op == GBA_OP_SMLAL;
    int accumulate = i->op == GBA_OP_UMLAL || i->op == GBA_OP_SMLAL;
    uint32_t rm = rd_(ctx, i, i->rm, 0), rs = rd_(ctx, i, i->rs, 0);
    gba_mul_wait(ctx, rs, is_signed, 1 + accumulate, stall_pc(i));
    uint64_t p = is_signed ? (uint64_t)((int64_t)(int32_t)rm * (int32_t)rs) : (uint64_t)rm * rs;
    if (accumulate)
        p += (uint64_t)ctx->r[i->rd_hi] << 32 | ctx->r[i->rd];
    if (i->s)
        gba_nz64(ctx, p);
    ctx->r[i->rd] = (uint32_t)p;
    ctx->r[i->rd_hi] = (uint32_t)(p >> 32);
}

/* semantics.py _offset */
static uint32_t offset(GbaCtx *ctx, const GbaInsn *i)
{
    if (i->rm == GBA_NO_REG)
        return i->imm;
    uint32_t v = rd_(ctx, i, i->rm, 0);
    if (i->shift_kind == GBA_SHIFT_NONE)
        return v;
    return shifted(ctx, i->shift_kind, v, i->shift_amount, 0);
}

/* semantics.py _single_transfer */
static void single_transfer(GbaCtx *ctx, const GbaInsn *i, uint32_t *t)
{
    uint32_t addr, moved = 0;
    int written_back = 0;
    if (i->rn == PC && i->has_target) {  /* literal pool */
        addr = i->target;
    } else {
        uint32_t base = rd_(ctx, i, i->rn, 0), off = offset(ctx, i);
        moved = i->up ? base + off : base - off;
        addr = i->pre ? moved : base;
        written_back = i->writeback;
    }
    if (is_store(i->op)) {
        uint32_t v = rd_(ctx, i, i->rd, i->rd == PC && !i->thumb ? 4u : 0u);  /* STR pc: pc + 12 */
        if (written_back)
            ctx->r[i->rn] = moved;
        if (i->op == GBA_OP_STR) gba_str(ctx, addr, v);
        else if (i->op == GBA_OP_STRB) gba_strb(ctx, addr, v);
        else gba_strh(ctx, addr, v);
        gba_store_wait(ctx, addr, i->op == GBA_OP_STR, stall_pc(i));
        return;
    }
    uint32_t v;
    switch (i->op) {
    case GBA_OP_LDR: v = gba_ldr(ctx, addr); break;
    case GBA_OP_LDRB: v = gba_read8(ctx, addr); break;
    case GBA_OP_LDRH: v = gba_ldrh(ctx, addr); break;
    case GBA_OP_LDRSB: v = gba_ldrsb(ctx, addr); break;
    default: v = gba_ldrsh(ctx, addr); break;
    }
    gba_load_wait(ctx, addr, i->op == GBA_OP_LDR, stall_pc(i));
    if (written_back)
        ctx->r[i->rn] = moved;
    put(ctx, i->rd, v, t);  /* a loaded base wins over the written-back one */
}

/* semantics.py _block_transfer */
static void block_transfer(GbaCtx *ctx, const GbaInsn *i, uint32_t *t)
{
    uint32_t list = i->reglist ? i->reglist : 1u << PC;  /* ARMv4: empty means r15 alone */
    uint32_t count = 0;
    for (uint32_t m = i->reglist; m; m &= m - 1)
        count++;
    if (!count)
        count = 16;
    uint32_t base = rd_(ctx, i, i->rn, 0);
    uint32_t first = i->up ? (i->pre ? 4u : 0u) : (i->pre ? 0u - 4u * count : 4u - 4u * count);
    uint32_t final = i->up ? base + 4u * count : base - 4u * count;
    int restore = restores_cpsr(i), user = i->user && !restore;
    uint32_t addr = (base + first) & ~3u, slot = addr;
    int index = 0;
    for (int r = 0; r < 16; r++) {
        if (!((list >> r) & 1))
            continue;
        uint32_t *target = user && r != PC ? gba_user_reg(ctx, r) : r == PC ? t : &ctx->r[r];
        if (i->op == GBA_OP_STM) {
            uint32_t value;
            if (r == i->rn && i->writeback && index > 0)
                value = final;  /* ARMv4: the new base is stored unless it comes first */
            else if (r == PC)
                value = pc_value(i) + (i->thumb ? 2u : 4u);  /* + 12 in ARM state, + 6 in Thumb */
            else
                value = *target;
            gba_write32(ctx, slot, value);
        } else {
            *target = gba_read32(ctx, slot);
        }
        slot += 4;
        index++;
    }
    gba_multiple_wait(ctx, addr, count, i->op == GBA_OP_LDM, stall_pc(i));
    if (i->writeback)
        ctx->r[i->rn] = final;
    if (restore)
        gba_restore_cpsr(ctx);
}

/* semantics.py _swap */
static void swap(GbaCtx *ctx, const GbaInsn *i)
{
    int word = i->op == GBA_OP_SWP;
    uint32_t addr = rd_(ctx, i, i->rn, 0);
    uint32_t old = word ? gba_ldr(ctx, addr) : gba_read8(ctx, addr);
    gba_load_wait(ctx, addr, word, stall_pc(i));
    uint32_t v = rd_(ctx, i, i->rm, 0);
    if (word) gba_str(ctx, addr, v);
    else gba_strb(ctx, addr, v);
    gba_store_wait(ctx, addr, word, stall_pc(i));
    ctx->r[i->rd] = old;
}

/* semantics.py lift_effects, for everything but B, BL, BL_LO and UNDEFINED */
static void effects(GbaCtx *ctx, const GbaInsn *i, uint32_t *t)
{
    int op = i->op;
    if (is_dp(op)) data_processing(ctx, i, t);
    else if (op <= GBA_OP_SMLAL) multiply(ctx, i);
    else if (is_load(op) || is_store(op)) single_transfer(ctx, i, t);
    else if (op == GBA_OP_LDM || op == GBA_OP_STM) block_transfer(ctx, i, t);
    else if (op == GBA_OP_SWP || op == GBA_OP_SWPB) swap(ctx, i);
    else if (op == GBA_OP_MRS) ctx->r[i->rd] = i->spsr ? ctx->spsr : gba_cpsr(ctx) & ~0x20u;
    else if (op == GBA_OP_MSR) {
        uint32_t value = i->has_imm ? i->imm : rd_(ctx, i, i->rm, 0);
        if (i->spsr) gba_set_spsr(ctx, value, i->psr_mask);
        else gba_set_cpsr(ctx, value, i->psr_mask);
    }
    else if (op == GBA_OP_SWI) gba_swi(ctx, i->thumb ? i->imm : i->imm >> 16);
    else if (op == GBA_OP_BX) *t = rd_(ctx, i, i->rm, 0);
    else if (op == GBA_OP_BL_HI) ctx->r[LR] = pc_value(i) + i->imm;
}

static void decode_at(GbaCtx *ctx, uint32_t pc, int thumb, GbaInsn *out)
{
    if (thumb) {
        uint32_t hw = gba_fetch16(ctx, pc);  /* a BL prefix pairs with the halfword after it */
        gba_decode_thumb(hw, pc, (hw & 0xF800) == 0xF000 ? (int32_t)gba_fetch16(ctx, pc + 2) : -1, out);
    } else
        gba_decode_arm(gba_fetch32(ctx, pc), pc, out);
}

/* flow.py links_to_next: `mov lr, pc` just before a jump turns it into a call. */
static int after_mov_lr_pc(GbaCtx *ctx, const GbaInsn *i)
{
    GbaInsn prev;
    uint32_t before = i->addr - (i->thumb ? 2u : 4u);
    if (i->thumb)
        gba_decode_thumb(gba_fetch16(ctx, before), before, -1, &prev);
    else
        gba_decode_arm(gba_fetch32(ctx, before), before, &prev);
    return prev.op == GBA_OP_MOV && prev.rd == LR && prev.rm == PC && prev.shift_kind == GBA_SHIFT_NONE;
}

/* Where a taken B goes: back to the dispatcher, as a lifted function's exit would, or on here. */
static int stays(GbaCtx *ctx, uint32_t target)
{
    uint32_t depth = ctx->call_depth;
    if (!((target ^ ctx->rets[depth]) & ~1u))
        return 0;  /* the call's return address: it ends */
    if (ctx->find && ctx->find(ctx, target))
        return 0;  /* recompiled code */
    for (uint32_t d = depth; d > 0; d--)
        if (!((target ^ ctx->rets[d]) & ~1u))
            return 0;  /* an outer call's return address: gba_missing unwinds to it */
    return 1;
}

uint32_t gba_interpret(GbaCtx *ctx)
{
    uint32_t pc = ctx->interp_pc;
    int thumb = (int)(pc & 1u);
    pc &= thumb ? ~1u : ~3u;
    uint64_t pending = 0;  /* the cost of instructions run but not yet added to ctx->cycles */
    for (;;) {
        GbaInsn insn, *i = &insn;
        decode_at(ctx, pc, thumb, i);
        ctx->interpreted++;
        uint32_t after = pc + i->size;
        /* function.py _block: costs charged in pieces, before accesses and leaving */
        uint32_t k, s, n;
        static_cost(i, &k, &s, &n);
        int conditional_arm = !thumb && i->cond != GBA_COND_AL;
        uint64_t own = conditional_arm ? cost(ctx, 1, 1, 0, pc, thumb) : cost(ctx, k, s, n, pc, thumb);
        int leaving = leaves(i);
        if (leaving)
            pending += own, own = 0;
        if (leaving || accesses(i)) {
            ctx->cycles += pending;
            pending = 0;
        }
        pending += own;
        if (i->cond != GBA_COND_AL && !holds(ctx, i->cond)) {
            pc = after;
            continue;
        }
        if (conditional_arm && !(k == 1 && s == 1 && n == 0))  /* function.py _extra */
            ctx->cycles += cost(ctx, k - 1, s - 1, n, pc, thumb);
        /* function.py _instruction */
        uint32_t t = 0;
        switch (i->op) {
        case GBA_OP_UNDEFINED:
            gba_undefined(ctx, pc);
            return pc | (uint32_t)thumb;
        case GBA_OP_B:
            gba_jumped(ctx, cost(ctx, 2, 1, 1, i->target, thumb));
            if (i->target == after) {
                pc = after;
                continue;
            }
            if (i->target <= pc)  /* a backward branch checks for due events */
                GBA_CHECK_EVENTS();
            if (!stays(ctx, i->target | (uint32_t)thumb))
                return i->target | (uint32_t)thumb;
            pc = i->target;
            continue;
        case GBA_OP_BL: {
            uint32_t ret = after | (uint32_t)thumb;
            ctx->r[LR] = ret;
            gba_jumped(ctx, cost(ctx, 2, 1, 1, i->target, thumb));
            if (i->target != after) {
                gba_call(ctx, i->target | (uint32_t)thumb, ret);
                GBA_UNWOUND();
            }
            pc = after;
            continue;
        }
        case GBA_OP_BL_LO: {
            uint32_t ret = after | (uint32_t)thumb;
            t = (ctx->r[LR] + i->imm) | 1u;  /* stays in Thumb state */
            ctx->r[LR] = ret;
            gba_jumped(ctx, gba_refill(ctx, t));
            gba_call(ctx, t, ret);
            GBA_UNWOUND();
            pc = after;
            continue;
        }
        default:
            break;
        }
        effects(ctx, i, &t);
        if (!writes_pc(i)) {
            pc = after;
            continue;
        }
        if (i->op != GBA_OP_BX) {  /* function.py _mask */
            if (restores_cpsr(i))
                t = (ctx->cpsr_ctrl & 0x20u) ? t | 1u : t & ~3u;
            else
                t = thumb ? t | 1u : t & ~3u;
        }
        gba_jumped(ctx, gba_refill(ctx, t));
        if (after_mov_lr_pc(ctx, i)) {  /* a call through a register */
            gba_call(ctx, t, ctx->r[LR]);
            GBA_UNWOUND();
            pc = after;
            continue;
        }
        GBA_CHECK_EVENTS();  /* a jump through a register checks for due events */
        return t;
    }
}
