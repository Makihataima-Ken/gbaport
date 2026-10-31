/* lifthost.c - runs lifted test programs against a small flat memory, for tests/liftkit.py.
 *
 * usage: lifthost INPUT OUTPUT
 *
 * INPUT holds a u32 case count, then per case: u32 case index, u32 r0-r14, u32 CPSR,
 * and the ROM, EWRAM and IWRAM windows (WINDOW bytes each). OUTPUT holds per case:
 * u32 status, u32 r0-r14, u32 CPSR and the EWRAM and IWRAM windows. A program stops
 * at "svc #0xff"; every other way out is a status the tests report.
 *
 * Built with LIFTHOST_INTERPRET, it runs every case in runtime/interp.c instead, from
 * LIFTHOST_ENTRY, and has no case table. */
#define _CRT_SECURE_NO_WARNINGS /* fopen is fine here (MSVC's C library) */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lifthost.h"
#ifdef LIFTHOST_INTERPRET
#include "interp.h"
#endif

#define WINDOW 0x1000u
#define CYCLE_LIMIT 1000000u

enum { STOPPED = 1, RETURNED, UNDEFINED, MISSING, FAULT, RUNAWAY }; /* setjmp returns 0 first */

static uint8_t rom[WINDOW], ewram[WINDOW], iwram[WINDOW];
static jmp_buf escape;

static uint8_t *window(uint32_t addr, uint32_t size, int writing)
{
    uint32_t offset = addr & 0x00FFFFFFu;
    uint8_t *base;
    switch (addr >> 24) {
    case 0x02: base = ewram; break;
    case 0x03: base = iwram; break;
    case 0x08: base = writing ? NULL : rom; break;
    default: base = NULL; break;
    }
    if (base == NULL || offset + size > WINDOW)
        longjmp(escape, FAULT);
    return base + offset;
}

uint32_t gba_read8(GbaCtx *ctx, uint32_t addr) { (void)ctx; return *window(addr, 1, 0); }

uint32_t gba_read16(GbaCtx *ctx, uint32_t addr)
{
    uint8_t *p = window(addr, 2, 0);
    (void)ctx;
    return (uint32_t)p[0] | (uint32_t)p[1] << 8;
}

uint32_t gba_read32(GbaCtx *ctx, uint32_t addr)
{
    uint8_t *p = window(addr, 4, 0);
    (void)ctx;
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

void gba_write8(GbaCtx *ctx, uint32_t addr, uint32_t value) { (void)ctx; *window(addr, 1, 1) = (uint8_t)value; }

void gba_write16(GbaCtx *ctx, uint32_t addr, uint32_t value)
{
    uint8_t *p = window(addr & ~1u, 2, 1);  /* stores arrive with the whole address */
    (void)ctx;
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

void gba_write32(GbaCtx *ctx, uint32_t addr, uint32_t value)
{
    uint8_t *p = window(addr & ~3u, 4, 1);
    (void)ctx;
    for (int i = 0; i < 4; i++)
        p[i] = (uint8_t)(value >> (8 * i));
}

void gba_swi(GbaCtx *ctx, uint32_t number)
{
    (void)ctx;
    if (number == 0xFF)
        longjmp(escape, STOPPED);
}

void gba_undefined(GbaCtx *ctx, uint32_t addr) { (void)ctx; (void)addr; longjmp(escape, UNDEFINED); }

#ifdef LIFTHOST_INTERPRET
uint32_t gba_fetch16(GbaCtx *ctx, uint32_t addr) { return gba_read16(ctx, addr); }
uint32_t gba_fetch32(GbaCtx *ctx, uint32_t addr) { return gba_read32(ctx, addr); }

GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
{
    ctx->interp_pc = addr;
    return gba_interpret;
}

static GbaFn interpret_everything(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }
#else
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr) { (void)ctx; (void)addr; longjmp(escape, MISSING); }
#endif

/* Calls nested this deep come from code that calls without returning: a runaway. */
void gba_call_overflow(GbaCtx *ctx, uint32_t ret) { (void)ctx; (void)ret; longjmp(escape, RUNAWAY); }

void gba_events(GbaCtx *ctx)
{
    if (ctx->cycles >= CYCLE_LIMIT)
        longjmp(escape, RUNAWAY);
    ctx->next_event = CYCLE_LIMIT;
}

static uint32_t read_u32(FILE *f)
{
    uint8_t b[4];
    if (fread(b, 1, 4, f) != 4) {
        fprintf(stderr, "lifthost: input truncated\n");
        exit(2);
    }
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
}

static void write_u32(FILE *f, uint32_t v)
{
    uint8_t b[4] = {(uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24)};
    fwrite(b, 1, 4, f);
}

static void read_window(FILE *f, uint8_t *dest)
{
    if (fread(dest, 1, WINDOW, f) != WINDOW) {
        fprintf(stderr, "lifthost: input truncated\n");
        exit(2);
    }
}

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: lifthost INPUT OUTPUT\n");
        return 2;
    }
    FILE *in = fopen(argv[1], "rb"), *out = fopen(argv[2], "wb");
    if (in == NULL || out == NULL) {
        fprintf(stderr, "lifthost: cannot open files\n");
        return 2;
    }
    uint32_t count = read_u32(in);
    for (uint32_t n = 0; n < count; n++) {
        static GbaCtx ctx;
        uint32_t index = read_u32(in);
#ifdef LIFTHOST_INTERPRET
        (void)index;  /* every case runs from LIFTHOST_ENTRY */
#else
        if (index >= HARNESS_CASE_COUNT) {
            fprintf(stderr, "lifthost: no case %u\n", index);
            return 2;
        }
#endif
        memset(&ctx, 0, sizeof ctx);
        for (int r = 0; r < 15; r++)
            ctx.r[r] = read_u32(in);
        uint32_t cpsr = read_u32(in);
        ctx.n = cpsr >> 31;
        ctx.z = (cpsr >> 30) & 1;
        ctx.c = (cpsr >> 29) & 1;
        ctx.v = (cpsr >> 28) & 1;
        ctx.cpsr_ctrl = cpsr & 0x0FFFFFFFu;
        ctx.next_event = CYCLE_LIMIT;
#ifdef LIFTHOST_INTERPRET
        ctx.lookup = interpret_everything;
#else
        ctx.lookup = HARNESS_CASES[index].lookup;
#endif
        read_window(in, rom);
        read_window(in, ewram);
        read_window(in, iwram);
        uint32_t initial_lr = ctx.r[14];
        int status = setjmp(escape);
        if (status == 0) {
#ifdef LIFTHOST_INTERPRET
            gba_call(&ctx, LIFTHOST_ENTRY | (cpsr & 0x20u ? 1u : 0u), initial_lr);
#else
            gba_call_direct(&ctx, HARNESS_CASES[index].entry, initial_lr);
#endif
            status = RETURNED;
        }
        write_u32(out, (uint32_t)(status - STOPPED));
        for (int r = 0; r < 15; r++)
            write_u32(out, ctx.r[r]);
        write_u32(out, gba_cpsr(&ctx));
        fwrite(ewram, 1, WINDOW, out);
        fwrite(iwram, 1, WINDOW, out);
    }
    fclose(in);
    fclose(out);
    return 0;
}
