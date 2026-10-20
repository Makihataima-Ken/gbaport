/* scheduler.c - scanline timing, timed events and interrupt delivery.
 *
 * Recompiled code runs gba_events() once ctx->cycles reaches ctx->next_event. It runs
 * every event that is due, in time order, then delivers an interrupt if one is requested,
 * enabled (IE, IME) and not masked by the CPSR's I bit. Writes that can make an interrupt
 * deliverable pull next_event forward to "now", so the interrupt is taken at the next loop
 * head or function exit. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define NEVER UINT64_MAX
#define BIOS_IRQ_RETURN 0x00000138u  /* where the BIOS's IRQ code expects the handler back */
#define IRQ_VECTOR 0x03007FFCu

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

static int irq_ready(const GbaRuntime *rt)
{
    return (IO(rt, GBA_REG_IME) & 1) && (IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & 0x3FFF) &&
           !(rt->cpu.cpsr_ctrl & 0x80);
}

void gba_reschedule(GbaRuntime *rt)
{
    int which;
    rt->cpu.next_event = irq_ready(rt) ? rt->cpu.cycles : earliest(rt, &which);
}

void gba_irq_changed(GbaRuntime *rt)
{
    if (irq_ready(rt))
        rt->cpu.next_event = rt->cpu.cycles;
}

void gba_request_irq(GbaRuntime *rt, uint16_t bits)
{
    IO(rt, GBA_REG_IF) |= bits;
    gba_irq_changed(rt);
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
    rt->line_start = rt->cpu.cycles + GBA_START_HBLANK - GBA_CYCLES_HDRAW;
    rt->frames = 0;
    IO(rt, GBA_REG_VCOUNT) = GBA_START_LINE;
    schedule_line(rt);
    gba_reschedule(rt);
}

static void hblank(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    if (IO(rt, GBA_REG_VCOUNT) < GBA_VISIBLE_LINES)  /* before HBlank DMA and interrupts */
        gba_render_line(rt, IO(rt, GBA_REG_VCOUNT));
    IO(rt, GBA_REG_DISPSTAT) |= 2;
    if (IO(rt, GBA_REG_DISPSTAT) & 0x10)
        gba_request_irq(rt, GBA_IRQ_HBLANK);
    if (IO(rt, GBA_REG_VCOUNT) < GBA_VISIBLE_LINES)  /* no HBlank DMA during VBlank */
        gba_dma_trigger(rt, 2);
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
    if (line == 0)
        gba_keypad_check(rt);  /* at the start of every frame */
    if (line == GBA_VISIBLE_LINES) {
        gba_render_frame_start(rt);
        if (stat & 0x08)
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        gba_dma_trigger(rt, 1);
        gba_audio_run(rt, when);
        rt->frames++;
        if (rt->host.frame)
            rt->host.frame(rt, rt->host.user);
    }
}

/* Run every event that is due by ctx->cycles, in time order. */
static void advance(GbaRuntime *rt)
{
    for (;;) {
        int which = 0;
        uint64_t when = earliest(rt, &which);
        if (when > rt->cpu.cycles)
            break;
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else if (which == GBA_EVENT_LINE)
            line_end(rt, when);
        else
            gba_timer_overflow(rt, which - GBA_EVENT_TIMER0, when);
    }
    gba_reschedule(rt);
}

/* What the BIOS does on an IRQ: IRQ mode, push r0-r3, r12, lr; call [0x03007FFC] with
 * lr = 0x138; pop; return with CPSR = SPSR. The interrupted code resumes in C where it
 * called gba_events, so lr_irq (the resume address) is not known and is pushed as 0. */
static void deliver(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t cpsr = gba_cpsr(ctx);
    uint32_t handler = gba_read32(ctx, IRQ_VECTOR);
    if (handler == 0)
        gba_fail(rt, "an interrupt was requested but no handler is set at 0x03007FFC");
    gba_switch_mode(ctx, GBA_MODE_IRQ);
    ctx->spsr = cpsr;
    ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0xBFu) | 0x80u | GBA_MODE_IRQ;  /* ARM, I set, F kept */
    ctx->r[14] = 0;
    uint32_t sp = ctx->r[13] - 24;
    static const int saved[6] = {0, 1, 2, 3, 12, 14};
    for (int i = 0; i < 6; i++)
        gba_write32(ctx, sp + 4 * i, ctx->r[saved[i]]);
    ctx->r[13] = sp;
    ctx->r[0] = 0x04000000u;
    ctx->r[14] = BIOS_IRQ_RETURN;
    /* The BIOS's IRQ entry and exit as mGBA counts them (its stand-in BIOS's code): the
     * jump to 0x18 (2), stmfd of 6 registers (7), mov and add (2), ldr pc (5), ldmfd (8) and
     * subs pc (1), whose jump back is taken to be to Thumb code in the cartridge (2 + N + S);
     * the handler's own return to the BIOS is the recompiled code's. */
    ctx->cycles += 25 + 2 + ctx->n16[8] + ctx->s16[8];
    ctx->prefetched = 0;
    rt->bios_bus = 0xE25EF004u;  /* the opcode at 0x13C, fetched while the handler runs */
    gba_call(ctx, handler, BIOS_IRQ_RETURN);
    sp = ctx->r[13];
    for (int i = 0; i < 6; i++)
        ctx->r[saved[i]] = gba_read32(ctx, sp + 4 * i);
    ctx->r[13] = sp + 24;
    gba_restore_cpsr(ctx);
    rt->bios_bus = 0xE55EC002u;  /* the opcode at 0x144, fetched after it returns */
    gba_reschedule(rt);
}

void gba_events(GbaCtx *ctx)
{
    GbaRuntime *rt = gba_rt(ctx);
    advance(rt);
    while (irq_ready(rt))
        deliver(rt);
}

/* Stop: the CPU, the clocks and the display stand still until a keypad, cartridge or
 * link interrupt that IE enables is requested. Only the keypad can request one here, and
 * only the host can press keys: it waits for input in its stopped callback. */
void gba_stop(GbaRuntime *rt)
{
    const uint16_t wake = GBA_IRQ_KEYPAD | GBA_IRQ_GAMEPAK | GBA_IRQ_SERIAL;
    gba_keypad_check(rt);  /* keys held already wake it, as at a frame start */
    while (!(IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & wake))
        if (!rt->host.stopped || !rt->host.stopped(rt, rt->host.user))
            gba_end(rt, GBA_END_STOPPED);
    while (irq_ready(rt))
        deliver(rt);
}

/* Halt: skip ahead from event to event until an interrupt is requested and enabled in IE
 * (IME and the CPSR do not matter for waking up), then deliver it if they allow. */
void gba_halt(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    while (!(IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & 0x3FFF)) {
        int which;
        uint64_t when = earliest(rt, &which);
        if (ctx->cycles < when)
            ctx->cycles = when;
        advance(rt);
    }
    while (irq_ready(rt))
        deliver(rt);
}
