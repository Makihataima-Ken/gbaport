/* timers.c - the four 16-bit timers.
 *
 * A ticking timer is not stepped: its counter is worked out from the cycles since it last
 * held a known value, and its overflow is a scheduler event. Count-up timers (bit 2, not
 * timer 0) tick when the timer below them overflows. */
#include "gba_runtime.h"

#define NEVER UINT64_MAX

static const int prescale_shift[4] = {0, 6, 8, 10};  /* 1, 64, 256 or 1024 cycles a tick */

static int ticking(const GbaTimer *t, int n)
{
    return (t->control & 0x80) && !(n > 0 && (t->control & 0x04));
}

static int shift(const GbaTimer *t) { return prescale_shift[t->control & 3]; }

uint16_t gba_timer_counter(GbaRuntime *rt, int n)
{
    const GbaTimer *t = &rt->timer[n];
    if (!ticking(t, n))
        return t->counter;
    uint64_t ticks = (rt->cpu.cycles - t->start) >> shift(t);
    uint64_t first = 0x10000u - t->counter;  /* ticks until the next overflow */
    if (ticks < first)
        return (uint16_t)(t->counter + ticks);
    return (uint16_t)(t->reload + (ticks - first) % (0x10000u - t->reload));  /* overflow not yet run */
}

static void schedule(GbaRuntime *rt, int n)
{
    const GbaTimer *t = &rt->timer[n];
    rt->event_at[GBA_EVENT_TIMER0 + n] =
        ticking(t, n) ? t->start + ((uint64_t)(0x10000u - t->counter) << shift(t)) : NEVER;
}

void gba_timer_write(GbaRuntime *rt, int n, uint16_t control)
{
    GbaTimer *t = &rt->timer[n];
    /* Overflows that were due before this write (the scheduler has not run them yet,
     * because blocks add their cycles up front) happened first. */
    while (rt->event_at[GBA_EVENT_TIMER0 + n] <= rt->cpu.cycles)
        gba_timer_overflow(rt, n, rt->event_at[GBA_EVENT_TIMER0 + n]);
    int starting = !(t->control & 0x80) && (control & 0x80);
    t->counter = gba_timer_counter(rt, n);  /* keep the count under the old settings */
    t->start = rt->cpu.cycles;
    t->control = control & 0xC7;
    rt->io[(GBA_REG_TM0CNT_L + 4 * n + 2) >> 1] = t->control;
    if (starting)
        t->counter = t->reload;
    schedule(rt, n);
    gba_reschedule(rt);
}

static void overflowed(GbaRuntime *rt, int n);

static void count_up(GbaRuntime *rt, int n)
{
    GbaTimer *t = &rt->timer[n];
    if (!(t->control & 0x80) || !(t->control & 0x04))
        return;
    if (++t->counter == 0) {
        t->counter = t->reload;
        overflowed(rt, n);
    }
}

static void overflowed(GbaRuntime *rt, int n)
{
    if (rt->timer[n].control & 0x40)
        gba_request_irq(rt, (uint16_t)(GBA_IRQ_TIMER0 << n));
    if (n < 3)
        count_up(rt, n + 1);
}

void gba_timer_overflow(GbaRuntime *rt, int n, uint64_t when)
{
    GbaTimer *t = &rt->timer[n];
    t->counter = t->reload;
    t->start = when;
    schedule(rt, n);
    overflowed(rt, n);
}
