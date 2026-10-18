/* scheduler.c - scanline timing and timed events.
 *
 * Recompiled code runs gba_events() once ctx->cycles reaches ctx->next_event. It runs
 * every event that is due, in time order: each scanline's HBlank and end, which keep
 * DISPSTAT and VCOUNT up to date, request interrupts in IF and count frames. Nothing
 * delivers the interrupts yet. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define NEVER UINT64_MAX

static uint64_t earliest(const GbaRuntime *rt, int *which)
{
    uint64_t when = NEVER;
    for (int i = 0; i < GBA_EVENT_COUNT; i++) {
        if (rt->event_at[i] < when) {
            when = rt->event_at[i];
            *which = i;
        }
    }
    return when;
}

void gba_reschedule(GbaRuntime *rt)
{
    int which;
    rt->cpu.next_event = earliest(rt, &which);
}

void gba_request_irq(GbaRuntime *rt, uint16_t bits)
{
    IO(rt, GBA_REG_IF) |= bits;
}

static void schedule_line(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = rt->line_start + GBA_CYCLES_HDRAW;
    rt->event_at[GBA_EVENT_LINE] = rt->line_start + GBA_CYCLES_LINE;
}

void gba_scheduler_start(GbaRuntime *rt)
{
    for (int i = 0; i < GBA_EVENT_COUNT; i++)
        rt->event_at[i] = NEVER;
    rt->line_start = rt->cpu.cycles;
    rt->frames = 0;
    IO(rt, GBA_REG_VCOUNT) = 0;
    schedule_line(rt);
    gba_reschedule(rt);
}

static void hblank(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    IO(rt, GBA_REG_DISPSTAT) |= 2;
    if (IO(rt, GBA_REG_DISPSTAT) & 0x10)
        gba_request_irq(rt, GBA_IRQ_HBLANK);
}

static void line_end(GbaRuntime *rt, uint64_t when)
{
    uint16_t line = (uint16_t)((IO(rt, GBA_REG_VCOUNT) + 1) % GBA_LINES);
    uint16_t stat = IO(rt, GBA_REG_DISPSTAT) & ~2;
    rt->line_start = when;
    schedule_line(rt);
    IO(rt, GBA_REG_VCOUNT) = line;
    if (line == GBA_VISIBLE_LINES)
        stat |= 1;
    else if (line == GBA_LINES - 1)
        stat &= ~1;  /* the VBlank flag is clear again in the last line */
    int match = line == (stat >> 8);
    stat = (uint16_t)(match ? stat | 4 : stat & ~4);
    IO(rt, GBA_REG_DISPSTAT) = stat;
    if (match && (stat & 0x20))
        gba_request_irq(rt, GBA_IRQ_VCOUNT);
    if (line == GBA_VISIBLE_LINES) {
        if (stat & 0x08)
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        rt->frames++;
        if (rt->host.frame)
            rt->host.frame(rt, rt->host.user);
    }
}

void gba_events(GbaCtx *ctx)
{
    GbaRuntime *rt = gba_rt(ctx);
    for (;;) {
        int which = 0;
        uint64_t when = earliest(rt, &which);
        if (when > ctx->cycles)
            break;
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else
            line_end(rt, when);
    }
    gba_reschedule(rt);
}
