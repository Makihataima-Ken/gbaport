/* bios.c - the BIOS calls (SWI), reimplemented in C.
 *
 * This file has the calls that control the CPU: resets, Halt, Stop and the interrupt
 * waits. The other BIOS functions (0x06-0x2A: arithmetic, copies, decompression, ...)
 * are not implemented yet and end the run with an error that names them. Numbers above
 * 0x2A do not exist in the BIOS; the first one is reported and they are ignored. */
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define BIOS_IF 0x03007FF8u  /* the flags a game's IRQ handler sets for IntrWait */

/* RegisterRamReset: r0 selects what to clear. Bit 1 keeps the top 0x200 bytes of IWRAM;
 * bit 7 resets the I/O registers other than serial and sound. */
static void register_ram_reset(GbaRuntime *rt, uint32_t flags)
{
    if (flags & 0x01) memset(rt->ewram, 0, sizeof rt->ewram);
    if (flags & 0x02) memset(rt->iwram, 0, 0x7E00);
    if (flags & 0x04) memset(rt->palette, 0, sizeof rt->palette);
    if (flags & 0x08) memset(rt->vram, 0, sizeof rt->vram);
    if (flags & 0x10) memset(rt->oam, 0, sizeof rt->oam);
    if (flags & 0x20) {
        for (uint32_t r = GBA_REG_SIO_FIRST; r <= GBA_REG_SIO_LAST; r += 2)
            if (r != GBA_REG_KEYINPUT && r != GBA_REG_KEYCNT)
                IO(rt, r) = 0;
        IO(rt, GBA_REG_RCNT) = 0x8000;
    }
    if (flags & 0x40)
        for (uint32_t r = GBA_REG_SOUND_FIRST; r <= GBA_REG_SOUND_LAST; r += 2)
            IO(rt, r) = 0;
    if (flags & 0x80) {
        uint16_t keep[0x200];
        memcpy(keep, rt->io, sizeof keep);
        gba_reset_io(rt);
        IO(rt, GBA_REG_VCOUNT) = keep[GBA_REG_VCOUNT >> 1];
        IO(rt, GBA_REG_DISPSTAT) = keep[GBA_REG_DISPSTAT >> 1] & 7;
        for (uint32_t r = GBA_REG_SOUND_FIRST; r <= GBA_REG_SOUND_LAST; r += 2)
            IO(rt, r) = keep[r >> 1];
        for (uint32_t r = GBA_REG_SIO_FIRST; r <= GBA_REG_SIO_LAST; r += 2)
            if (r != GBA_REG_KEYCNT)
                IO(rt, r) = keep[r >> 1];
        for (int n = 0; n < 4; n++)
            rt->event_at[GBA_EVENT_TIMER0 + n] = UINT64_MAX;
        gba_reschedule(rt);
    }
}

/* IntrWait: wait until the IRQ handler has set one of `flags` in BIOS_IF, then clear it.
 * With `discard`, flags that were already set do not count. Like the BIOS, it turns IME on
 * again on every pass, so a handler that leaves IME off cannot stop the wait. */
static void intr_wait(GbaRuntime *rt, uint32_t discard, uint32_t flags)
{
    GbaCtx *ctx = &rt->cpu;
    if (ctx->cpsr_ctrl & 0x80)
        gba_fail(rt, "IntrWait was called with interrupts disabled in the CPSR; it would never return");
    if (discard)
        gba_write16(ctx, BIOS_IF, gba_read16(ctx, BIOS_IF) & ~flags);
    for (;;) {
        IO(rt, GBA_REG_IME) = 1;
        uint32_t set = gba_read16(ctx, BIOS_IF);
        if (set & flags) {
            gba_write16(ctx, BIOS_IF, set & ~flags);
            return;
        }
        gba_halt(rt);
    }
}

void gba_swi(GbaCtx *ctx, uint32_t number)
{
    GbaRuntime *rt = gba_rt(ctx);
    ctx->cycles += 20;  /* entering and leaving the BIOS */
    switch (number) {
    case 0x00: gba_reset(rt); break;
    case 0x01: register_ram_reset(rt, ctx->r[0]); break;
    case 0x02: gba_halt(rt); break;
    case 0x03: gba_end(rt, GBA_END_STOPPED); break;  /* nothing can wake a headless run */
    case 0x04: intr_wait(rt, ctx->r[0], ctx->r[1]); break;
    case 0x05:
        ctx->r[0] = ctx->r[1] = 1;
        intr_wait(rt, 1, GBA_IRQ_VBLANK);
        break;
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        if (!rt->warned_swi && rt->host.diag) {
            char text[96];
            snprintf(text, sizeof text, "ignoring SWI 0x%02x: the BIOS has no such function",
                     (unsigned)number);
            rt->host.diag(rt, text, rt->host.user);
        }
        rt->warned_swi = 1;
        break;
    }
    rt->bios_bus = 0xE3A02004u;  /* the opcode the BIOS fetches last on its way out */
}
