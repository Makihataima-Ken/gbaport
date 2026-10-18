/* bios.c - the BIOS calls (SWI), reimplemented in C.
 *
 * gba_swi dispatches every call. This file has the ones that control the CPU (resets,
 * Halt, Stop, the interrupt waits) and the small ones; the others are in
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq;
 * - bios_memory.c: CpuSet, CpuFastSet, BitUnPack, BgAffineSet, ObjAffineSet.
 * Any other BIOS function ends the run with an error that names it, for now.
 * The sound driver calls (0x1A-0x1E, 0x20-0x24, 0x28-0x2A) are ignored with a warning
 * until sound arrives. Numbers above 0x2A do not exist in the BIOS; they are ignored with
 * a warning too. */
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
    case 0x06: gba_bios_div(rt, (int32_t)ctx->r[0], (int32_t)ctx->r[1]); break;
    case 0x07: gba_bios_div(rt, (int32_t)ctx->r[1], (int32_t)ctx->r[0]); break;  /* DivArm */
    case 0x08: gba_bios_sqrt(rt); break;
    case 0x09: gba_bios_arctan(rt); break;
    case 0x0A: gba_bios_arctan2(rt); break;
    case 0x0B: gba_bios_cpu_set(rt); break;
    case 0x0C: gba_bios_cpu_fast_set(rt); break;
    case 0x0D: ctx->r[0] = 0xBAAE187Fu; break;  /* GetBiosChecksum */
    case 0x0E: gba_bios_bg_affine_set(rt); break;
    case 0x0F: gba_bios_obj_affine_set(rt); break;
    case 0x10: gba_bios_bit_unpack(rt); break;
    case 0x19:  /* SoundBias: straight to the target level */
        IO(rt, 0x088) = (uint16_t)((IO(rt, 0x088) & 0xC000) | (ctx->r[0] ? 0x200 : 0));
        break;
    case 0x1F: gba_bios_midi_key_to_freq(rt); break;
    case 0x25: ctx->r[0] = 1; break;  /* MultiBoot fails: there is no link cable */
    case 0x27:  /* CustomHalt: r2's low byte goes to HALTCNT */
        if (ctx->r[2] & 0x80)
            gba_end(rt, GBA_END_STOPPED);
        gba_halt(rt);
        break;
    case 0x1A: case 0x1B: case 0x1C: case 0x1D: case 0x1E:
    case 0x20: case 0x21: case 0x22: case 0x23: case 0x24:
    case 0x28: case 0x29: case 0x2A:
        gba_warn_once(rt, GBA_WARN_SOUND,
                      "ignoring the BIOS sound driver (SWI 0x%02x) until sound arrives",
                      (unsigned)number);
        break;
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        gba_warn_once(rt, GBA_WARN_SWI, "ignoring SWI 0x%02x: the BIOS has no such function",
                      (unsigned)number);
        break;
    }
    rt->bios_bus = 0xE3A02004u;  /* the opcode the BIOS fetches last on its way out */
}
