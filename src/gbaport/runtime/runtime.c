/* runtime.c - start-up, the run loop, resets and runtime errors. */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"
#include "interp.h"

#define EWRAM_ENTRY 0x02000000u
#define BIOS_RESET 0x00000000u  /* never a return address: reaching it is an error */

uint32_t gba_crc32(const uint8_t *data, uint32_t size)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return ~crc;
}

int gba_init(GbaRuntime *rt, const uint8_t *rom, uint32_t size, const GbaHost *host)
{
    memset(rt, 0, sizeof *rt);
    rt->host = *host;
    rt->rom = rom;
    rt->rom_size = size;
    gba_save_init(rt);
    if (size != gba_rom_size || gba_crc32(rom, size) != gba_rom_crc32) {
        snprintf(rt->error, sizeof rt->error,
                 "this build was recompiled from a different ROM (want %u bytes with CRC32 "
                 "%08x, got %u bytes with CRC32 %08x)",
                 (unsigned)gba_rom_size, (unsigned)gba_rom_crc32, (unsigned)size,
                 (unsigned)gba_crc32(rom, size));
        return -1;
    }
    return 0;
}

/* --interpret-all: every address goes to gba_missing, so the interpreter runs it all. */
static GbaFn interpret_everything(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }

/* The CPU state the BIOS leaves for the game: system mode, its stacks set, r0-r12 zero. */
static void reset_cpu(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint64_t cycles = ctx->cycles, interpreted = ctx->interpreted;
    memset(ctx, 0, sizeof *ctx);
    ctx->cycles = cycles;
    ctx->interpreted = interpreted;
    ctx->lookup = rt->interpret_all ? interpret_everything : gba_lookup;
    ctx->find = rt->interpret_all ? NULL : gba_find;
    ctx->runtime = rt;
    ctx->cpsr_ctrl = GBA_MODE_SYS;
    ctx->r[13] = 0x03007F00u;
    ctx->bank_r13_14[gba_bank(GBA_MODE_IRQ)][0] = 0x03007FA0u;
    ctx->bank_r13_14[gba_bank(GBA_MODE_SVC)][0] = 0x03007FE0u;
    gba_waitcnt(rt, rt->io[GBA_REG_WAITCNT >> 1]);
}

static void power_on(GbaRuntime *rt)
{
    memset(rt->ewram, 0, sizeof rt->ewram);
    memset(rt->iwram, 0, sizeof rt->iwram);
    memset(rt->palette, 0, sizeof rt->palette);
    memset(rt->vram, 0, sizeof rt->vram);
    memset(rt->oam, 0, sizeof rt->oam);
    rt->cpu.cycles = GBA_CYCLES_HDRAW - GBA_START_HBLANK;  /* the start line began at 0 */
    reset_cpu(rt);
    gba_reset_io(rt);
    gba_audio_reset(rt);
    rt->bios_bus = 0xE129F000u;  /* the opcode the BIOS fetches last before starting the game */
    gba_scheduler_start(rt);
}

/* SoftReset: clear the top 0x200 bytes of IWRAM (stacks, IRQ vector and flags), reset the
 * CPU registers, and start again at the ROM, or at EWRAM if [0x03007FFA] is non-zero.
 * Memory and I/O registers are kept. */
static uint32_t soft_reset(GbaRuntime *rt)
{
    uint32_t entry = rt->iwram[0x7FFA] ? EWRAM_ENTRY : gba_rom_entry;
    memset(rt->iwram + 0x7E00, 0, 0x200);
    reset_cpu(rt);
    gba_reschedule(rt);
    return entry;
}

GbaEnd gba_run(GbaRuntime *rt)
{
    power_on(rt);
    volatile uint32_t entry = gba_rom_entry;
    for (;;) {
        if (setjmp(rt->end_jump) == 0) {
            gba_call(&rt->cpu, entry, BIOS_RESET);
            gba_fail(rt, "the game jumped to the BIOS reset vector (0x00000000)");
        }
        if (!rt->resetting)
            return rt->end;
        if (rt->resetting == 2) {  /* HardReset: as if switched off and on (saves stay) */
            power_on(rt);
            entry = gba_rom_entry;
        } else {
            entry = soft_reset(rt);
        }
        rt->resetting = 0;
    }
}

void gba_end(GbaRuntime *rt, GbaEnd why)
{
    rt->end = why;
    longjmp(rt->end_jump, 1);
}

void gba_reset(GbaRuntime *rt)
{
    rt->resetting = 1;
    longjmp(rt->end_jump, 1);
}

void gba_hard_reset(GbaRuntime *rt)
{
    rt->resetting = 2;
    longjmp(rt->end_jump, 1);
}

void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...)
{
    if (rt->warned & kind)
        return;
    rt->warned |= kind;
    if (!rt->host.diag)
        return;
    char text[256];
    va_list args;
    va_start(args, fmt);
    vsnprintf(text, sizeof text, fmt, args);
    va_end(args);
    rt->host.diag(rt, text, rt->host.user);
}

void gba_fail(GbaRuntime *rt, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    vsnprintf(rt->error, sizeof rt->error, fmt, args);
    va_end(args);
    gba_end(rt, GBA_END_ERROR);
}

void gba_set_keys(GbaRuntime *rt, uint16_t pressed)
{
    rt->keys_pressed = pressed & 0x3FF;
    gba_keypad_check(rt);
}

/* ---- hooks from gba_cpu.h: what recompiled code cannot handle itself -------------- */

/* What a lookup of an outer call's return address runs: it goes back there at once, and
 * the calls in between see unwind_depth and return too (gba_call, GBA_UNWOUND). */
static uint32_t unwinding(GbaCtx *ctx)
{
    return ctx->rets[ctx->unwind_depth];
}

/* addr has bit 0 set when execution was to go on in Thumb state. The return address of a
 * call further out is not missing code: execution goes back to that call (the innermost,
 * if several), as when a task switch returns into the task that called it. */
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
{
    for (uint32_t depth = ctx->call_depth; depth > 0; depth--)
        if (!((ctx->rets[depth] ^ addr) & ~1u)) {
            ctx->unwind_depth = depth;
            return unwinding;
        }
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t thumb = addr & 1, at = thumb ? addr & ~1u : addr & ~3u, region = at >> 24;
    int rom = region >= 0x08 && region <= 0x0D;
    if (rom ? (at & 0x01FFFFFFu) >= rt->rom_size : region != 0x02 && region != 0x03 && region != 0x06)
        gba_fail(rt, "no recompiled code at 0x%08x (%s state, lr = 0x%08x, frame %lu), and none "
                 "can be there: %s", (unsigned)at, thumb ? "Thumb" : "ARM", (unsigned)ctx->r[14],
                 (unsigned long)rt->frames,
                 rom ? "it is past the end of the ROM" : "no memory there holds code");
    /* Code the build missed: the interpreter runs it, and the place goes on the list. */
    gba_note_place(rt, at | thumb, (uint32_t)rt->frames);
    ctx->interp_pc = at | thumb;
    return gba_interpret;
}

int gba_note_place(GbaRuntime *rt, uint32_t addr, uint32_t frame)
{
    uint32_t mask = 2 * GBA_MAX_PLACES - 1, slot = (addr * 2654435761u >> 8) & mask;
    for (uint32_t i; (i = rt->place_slots[slot]) != 0; slot = (slot + 1) & mask)
        if (rt->places[i - 1].addr == addr)
            return 0;
    if (rt->place_count == GBA_MAX_PLACES)
        return 0;
    rt->places[rt->place_count] = (GbaPlace){addr, frame};
    rt->place_slots[slot] = ++rt->place_count;
    return 1;
}

void gba_undefined(GbaCtx *ctx, uint32_t addr)
{
    gba_fail(gba_rt(ctx), "undefined instruction at 0x%08x", (unsigned)addr);
}

void gba_call_overflow(GbaCtx *ctx, uint32_t ret)
{
    gba_fail(gba_rt(ctx),
             "calls nested deeper than %u (return address 0x%08x): code that calls "
             "without ever returning",
             (unsigned)GBA_MAX_CALL_DEPTH, (unsigned)ret);
}
