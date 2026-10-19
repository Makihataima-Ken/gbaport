/* gba_cpu.h - CPU state and instruction helpers shared by recompiled code and the runtime.
 *
 * Recompiled functions have the type GbaFn: they run guest code starting at their
 * entry and return the guest address execution continues at (a return address, a
 * tail-call target, or any other jump target). gba_call() runs such a chain until
 * it reaches the return address of the call that started it, so returns end C
 * calls while tail calls and jumps never grow the C stack. Code that calls without
 * ever returning (bl used as a jump in a loop) would still nest C calls forever, so
 * nesting deeper than GBA_MAX_CALL_DEPTH goes to the runtime's gba_call_overflow.
 *
 * The runtime provides the memory accessors (aligned addresses only; the CPU-level
 * helpers below apply the ARM7TDMI rules for misaligned loads and stores), the BIOS
 * (gba_swi), the scheduler (gba_events) and the handlers for undefined instructions
 * and addresses that have no recompiled function. */
#ifndef GBA_CPU_H
#define GBA_CPU_H

#include <stdint.h>

enum {
    GBA_MODE_USR = 0x10, GBA_MODE_FIQ = 0x11, GBA_MODE_IRQ = 0x12, GBA_MODE_SVC = 0x13,
    GBA_MODE_ABT = 0x17, GBA_MODE_UND = 0x1B, GBA_MODE_SYS = 0x1F,
};

struct GbaCtx;
typedef uint32_t (*GbaFn)(struct GbaCtx *ctx);

typedef struct GbaCtx {
    uint32_t r[16];             /* registers of the current mode; r[15] is unused */
    uint32_t n, z, c, v;        /* condition flags, each 0 or 1 */
    uint32_t cpsr_ctrl;         /* CPSR bits 0-27: mode, T, F, I */
    uint32_t spsr;              /* SPSR of the current mode (meaningless in USR/SYS) */
    uint32_t bank_r8_12[2][5];  /* r8-r12: [0] every mode but FIQ, [1] FIQ */
    uint32_t bank_r13_14[6][2]; /* r13, r14 of USR/SYS, FIQ, IRQ, SVC, ABT, UND */
    uint32_t bank_spsr[6];
    uint64_t cycles;            /* estimated CPU cycles run so far */
    uint64_t next_event;        /* gba_events() runs once cycles reach this */
    uint32_t call_depth;        /* gba_call chains currently running */
    GbaFn (*lookup)(struct GbaCtx *ctx, uint32_t addr); /* recompiled function at addr */
    void *runtime;              /* owned by the runtime */
} GbaCtx;

/* Provided by the runtime. */
uint32_t gba_read8(GbaCtx *ctx, uint32_t addr);
uint32_t gba_read16(GbaCtx *ctx, uint32_t addr);
uint32_t gba_read32(GbaCtx *ctx, uint32_t addr);
void gba_write8(GbaCtx *ctx, uint32_t addr, uint32_t value);
void gba_write16(GbaCtx *ctx, uint32_t addr, uint32_t value);
void gba_write32(GbaCtx *ctx, uint32_t addr, uint32_t value);
void gba_swi(GbaCtx *ctx, uint32_t number);
void gba_undefined(GbaCtx *ctx, uint32_t addr);
void gba_events(GbaCtx *ctx);
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr); /* no function recompiled at addr */
void gba_call_overflow(GbaCtx *ctx, uint32_t ret); /* calls nested too deep; never returns */

/* ---- control flow ---------------------------------------------------------- */

#ifndef GBA_MAX_CALL_DEPTH
#define GBA_MAX_CALL_DEPTH 1024u
#endif

/* Runs the chain that starts at guest address next until it comes back to ret. */
static inline void gba_call(GbaCtx *ctx, uint32_t next, uint32_t ret)
{
    if (++ctx->call_depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    while ((next ^ ret) & ~1u)
        next = ctx->lookup(ctx, next)(ctx);
    ctx->call_depth--;
}

/* The same for a call to a recompiled function, which needs no lookup to start. */
static inline void gba_call_direct(GbaCtx *ctx, GbaFn fn, uint32_t ret)
{
    if (++ctx->call_depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    uint32_t next = fn(ctx);
    ctx->call_depth--;
    gba_call(ctx, next, ret);
}

#define GBA_EXIT(target) do { \
        uint32_t gba_exit_ = (target); \
        if (ctx->cycles >= ctx->next_event) gba_events(ctx); \
        return gba_exit_; \
    } while (0)

#define GBA_CHECK_EVENTS() do { if (ctx->cycles >= ctx->next_event) gba_events(ctx); } while (0)

/* ---- shifter: value, and the carry-out written through *c ------------------- */

static inline uint32_t gba_ror32(uint32_t v, uint32_t n)
{
    n &= 31;
    return n ? (v >> n) | (v << (32 - n)) : v;
}

static inline uint32_t gba_lsl(uint32_t v, uint32_t n) { return n < 32 ? v << n : 0; }
static inline uint32_t gba_lsr(uint32_t v, uint32_t n) { return n < 32 ? v >> n : 0; }
static inline uint32_t gba_asr(uint32_t v, uint32_t n)
{
    return (uint32_t)((int32_t)v >> (n < 32 ? n : 31));
}
static inline uint32_t gba_ror(uint32_t v, uint32_t n) { return gba_ror32(v, n); }
static inline uint32_t gba_rrx(uint32_t v, uint32_t c) { return (c << 31) | (v >> 1); }

static inline uint32_t gba_lsl_c(uint32_t v, uint32_t n, uint32_t *c)
{
    if (n == 0) return v;
    if (n < 32) { *c = (v >> (32 - n)) & 1; return v << n; }
    *c = n == 32 ? v & 1 : 0;
    return 0;
}

static inline uint32_t gba_lsr_c(uint32_t v, uint32_t n, uint32_t *c)
{
    if (n == 0) return v;
    if (n < 32) { *c = (v >> (n - 1)) & 1; return v >> n; }
    *c = n == 32 ? v >> 31 : 0;
    return 0;
}

static inline uint32_t gba_asr_c(uint32_t v, uint32_t n, uint32_t *c)
{
    if (n == 0) return v;
    if (n < 32) { *c = (uint32_t)((int32_t)v >> (n - 1)) & 1; return (uint32_t)((int32_t)v >> n); }
    *c = v >> 31;
    return *c ? 0xFFFFFFFFu : 0;
}

static inline uint32_t gba_ror_c(uint32_t v, uint32_t n, uint32_t *c)
{
    if (n == 0) return v;
    n &= 31;
    if (n == 0) { *c = v >> 31; return v; }
    *c = (v >> (n - 1)) & 1;
    return gba_ror32(v, n);
}

static inline uint32_t gba_rrx_c(uint32_t v, uint32_t *c)
{
    uint32_t result = (*c << 31) | (v >> 1);
    *c = v & 1;
    return result;
}

/* A rotated immediate sets the shifter carry to its bit 31. */
static inline uint32_t gba_imm_c(uint32_t imm, uint32_t *c)
{
    *c = imm >> 31;
    return imm;
}

/* ---- ALU ------------------------------------------------------------------- */

/* a + b + carry_in, setting N, Z, C (carry out) and V (signed overflow).
 * Subtractions are a + ~b + 1 (SUB, CMP) and a + ~b + C (SBC). */
static inline uint32_t gba_addc(GbaCtx *ctx, uint32_t a, uint32_t b, uint32_t carry_in)
{
    uint64_t wide = (uint64_t)a + b + carry_in;
    uint32_t r = (uint32_t)wide;
    ctx->n = r >> 31;
    ctx->z = r == 0;
    ctx->c = (uint32_t)(wide >> 32);
    ctx->v = ((~(a ^ b) & (a ^ r)) >> 31) & 1;
    return r;
}

static inline uint32_t gba_nz(GbaCtx *ctx, uint32_t r)
{
    ctx->n = r >> 31;
    ctx->z = r == 0;
    return r;
}

static inline void gba_nz64(GbaCtx *ctx, uint64_t r)
{
    ctx->n = (uint32_t)(r >> 63);
    ctx->z = r == 0;
}

/* ---- conditions ------------------------------------------------------------ */

#define GBA_EQ (ctx->z)
#define GBA_NE (!ctx->z)
#define GBA_CS (ctx->c)
#define GBA_CC (!ctx->c)
#define GBA_MI (ctx->n)
#define GBA_PL (!ctx->n)
#define GBA_VS (ctx->v)
#define GBA_VC (!ctx->v)
#define GBA_HI (ctx->c && !ctx->z)
#define GBA_LS (!ctx->c || ctx->z)
#define GBA_GE (ctx->n == ctx->v)
#define GBA_LT (ctx->n != ctx->v)
#define GBA_GT (!ctx->z && ctx->n == ctx->v)
#define GBA_LE (ctx->z || ctx->n != ctx->v)

/* ---- loads and stores with the ARM7TDMI's misalignment rules ----------------- */

static inline uint32_t gba_ldr(GbaCtx *ctx, uint32_t addr)
{
    return gba_ror32(gba_read32(ctx, addr & ~3u), (addr & 3) * 8);
}

static inline uint32_t gba_ldrh(GbaCtx *ctx, uint32_t addr)
{
    return gba_ror32(gba_read16(ctx, addr & ~1u), (addr & 1) * 8);
}

static inline uint32_t gba_ldrsb(GbaCtx *ctx, uint32_t addr)
{
    return (uint32_t)(int32_t)(int8_t)gba_read8(ctx, addr);
}

static inline uint32_t gba_ldrsh(GbaCtx *ctx, uint32_t addr)
{
    if (addr & 1)  /* a misaligned LDRSH loads the sign-extended byte */
        return gba_ldrsb(ctx, addr);
    return (uint32_t)(int32_t)(int16_t)gba_read16(ctx, addr);
}

/* Stores pass the whole address: the memory rounds it down, except on the save chip's bus. */
static inline void gba_str(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write32(ctx, addr, v); }
static inline void gba_strh(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write16(ctx, addr, v & 0xFFFF); }
static inline void gba_strb(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write8(ctx, addr, v & 0xFF); }

/* ---- modes, banked registers, CPSR and SPSR ------------------------------------ */

static inline int gba_bank(uint32_t mode)
{
    switch (mode & 0x1F) {
    case GBA_MODE_FIQ: return 1;
    case GBA_MODE_IRQ: return 2;
    case GBA_MODE_SVC: return 3;
    case GBA_MODE_ABT: return 4;
    case GBA_MODE_UND: return 5;
    default: return 0;
    }
}

static inline void gba_switch_mode(GbaCtx *ctx, uint32_t mode)
{
    int old_bank = gba_bank(ctx->cpsr_ctrl), new_bank = gba_bank(mode);
    if (old_bank != new_bank) {
        ctx->bank_r13_14[old_bank][0] = ctx->r[13];
        ctx->bank_r13_14[old_bank][1] = ctx->r[14];
        ctx->bank_spsr[old_bank] = ctx->spsr;
        if ((old_bank == 1) != (new_bank == 1)) {
            int was_fiq = old_bank == 1, is_fiq = new_bank == 1;
            for (int i = 0; i < 5; i++) {
                ctx->bank_r8_12[was_fiq][i] = ctx->r[8 + i];
                ctx->r[8 + i] = ctx->bank_r8_12[is_fiq][i];
            }
        }
        ctx->r[13] = ctx->bank_r13_14[new_bank][0];
        ctx->r[14] = ctx->bank_r13_14[new_bank][1];
        ctx->spsr = ctx->bank_spsr[new_bank];
    }
    ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0x1Fu) | (mode & 0x1F);
}

static inline uint32_t gba_cpsr(const GbaCtx *ctx)
{
    return ctx->n << 31 | ctx->z << 30 | ctx->c << 29 | ctx->v << 28 | (ctx->cpsr_ctrl & 0x0FFFFFFFu);
}

/* MSR CPSR: fields is the instruction's mask (8 = flags, 1 = control). Outside USR mode
 * the control field sets the mode, I and F; the T bit cannot be changed this way. */
static inline void gba_set_cpsr(GbaCtx *ctx, uint32_t value, uint32_t fields)
{
    if (fields & 8) {
        ctx->n = value >> 31;
        ctx->z = (value >> 30) & 1;
        ctx->c = (value >> 29) & 1;
        ctx->v = (value >> 28) & 1;
    }
    if ((fields & 1) && (ctx->cpsr_ctrl & 0x1F) != GBA_MODE_USR) {
        gba_switch_mode(ctx, value & 0x1F);
        ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0xDFu) | (value & 0xDF);
    }
}

static inline void gba_set_spsr(GbaCtx *ctx, uint32_t value, uint32_t fields)
{
    uint32_t mask = (fields & 8 ? 0xFF000000u : 0) | (fields & 1 ? 0xFFu : 0);
    ctx->spsr = (ctx->spsr & ~mask) | (value & mask);
}

/* Exception return (MOVS pc, lr / LDM ..., pc}^): CPSR = SPSR, including T. */
static inline void gba_restore_cpsr(GbaCtx *ctx)
{
    uint32_t saved = ctx->spsr;
    gba_switch_mode(ctx, saved & 0x1F);
    ctx->cpsr_ctrl = saved & 0x0FFFFFFFu;
    ctx->n = saved >> 31;
    ctx->z = (saved >> 30) & 1;
    ctx->c = (saved >> 29) & 1;
    ctx->v = (saved >> 28) & 1;
}

/* LDM/STM with ^ and no pc: transfer the USR-mode registers from a privileged mode. */
static inline uint32_t *gba_user_reg(GbaCtx *ctx, int n)
{
    int bank = gba_bank(ctx->cpsr_ctrl);
    if (n >= 13 && n <= 14 && bank != 0)
        return &ctx->bank_r13_14[0][n - 13];
    if (n >= 8 && n <= 12 && bank == 1)
        return &ctx->bank_r8_12[0][n - 8];
    return &ctx->r[n];
}

#endif
