/* io.c - the I/O registers at 0x04000000.
 *
 * Registers are kept by halfword and most read back what was written. The exceptions:
 * - DISPSTAT's status bits and VCOUNT belong to the scheduler; writes cannot change them.
 * - KEYINPUT comes from the host; KEYCNT can make the keys request an interrupt.
 * - IF clears the bits written as 1.
 * - DMA source, destination and count registers are write-only: they read as 0.
 * - Writing IE, IF or IME can make an interrupt deliverable.
 * - Writing HALTCNT halts or stops the CPU.
 * - Timer counters are worked out from the cycle count; writes set the reload value.
 * - Starting a DMA channel latches its registers and may run it at once. */
#include <string.h>

#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

/* The keypad interrupt, as mGBA requests it: KEYCNT bit 14 enables it and bits 0-9 choose
 * keys. With bit 15 clear, any chosen key held requests it at every check (frame start,
 * new keys from the host, KEYCNT writes, Stop); with bit 15 set, all of them must be held,
 * and only a change of keys requests it again. */
void gba_keypad_check(GbaRuntime *rt)
{
    uint16_t control = IO(rt, GBA_REG_KEYCNT), chosen = control & 0x3FF;
    if (!(control & 0x4000))
        return;
    uint16_t last = rt->keys_last, keys = rt->keys_pressed;
    rt->keys_last = keys;
    if (control & 0x8000 && (keys & chosen) == chosen) {
        if (keys != last)
            gba_request_irq(rt, GBA_IRQ_KEYPAD);
    } else if (!(control & 0x8000) && (keys & chosen)) {
        gba_request_irq(rt, GBA_IRQ_KEYPAD);
    } else {
        rt->keys_last = 0x400;
    }
}

void gba_reset_io(GbaRuntime *rt)
{
    memset(rt->io, 0, sizeof rt->io);
    memset(rt->timer, 0, sizeof rt->timer);
    memset(rt->dma, 0, sizeof rt->dma);
    IO(rt, GBA_REG_DISPCNT) = 0x0080;  /* forced blank, as the BIOS leaves it */
    IO(rt, 0x020) = IO(rt, 0x026) = 0x0100;  /* BG2 affine matrix: identity */
    IO(rt, 0x030) = IO(rt, 0x036) = 0x0100;  /* BG3 */
    IO(rt, 0x088) = 0x0200;                  /* SOUNDBIAS */
    IO(rt, GBA_REG_RCNT) = 0x8000;
    IO(rt, GBA_REG_POSTFLG) = 0x0001;        /* booted */
    rt->keys_last = 0x400;
}

static int dma_channel(uint32_t offset)  /* the channel whose CNT_H is at offset, or -1 */
{
    if (offset < GBA_REG_DMA0SAD || offset > GBA_REG_DMA3CNT_H)
        return -1;
    uint32_t rel = offset - GBA_REG_DMA0SAD;
    return rel % 12 == 10 ? (int)(rel / 12) : -1;
}

uint16_t gba_io_read(GbaRuntime *rt, uint32_t offset)
{
    if (offset >= GBA_REG_DMA0SAD && offset <= GBA_REG_DMA3CNT_H && dma_channel(offset) < 0)
        return 0;  /* source, destination and count are write-only */
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H && !(offset & 2))
        return gba_timer_counter(rt, (int)(offset - GBA_REG_TM0CNT_L) / 4);
    if (offset == GBA_REG_KEYINPUT)
        return (uint16_t)(0x3FF & ~rt->keys_pressed);
    return IO(rt, offset);
}

void gba_io_write(GbaRuntime *rt, uint32_t offset, uint16_t value, uint16_t mask)
{
    uint16_t old = IO(rt, offset);
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    int channel = dma_channel(offset);
    if (channel >= 0) {
        gba_dma_write(rt, channel, merged);
        return;
    }
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H) {
        int n = (int)(offset - GBA_REG_TM0CNT_L) / 4;
        if (offset & 2)
            gba_timer_write(rt, n, merged);
        else
            rt->timer[n].reload = merged;  /* used at the next start or overflow */
        return;
    }
    switch (offset) {
    case GBA_REG_DISPSTAT: {
        uint16_t stat = (uint16_t)((old & 0x0007) | (merged & 0xFF38));
        uint16_t match = IO(rt, GBA_REG_VCOUNT) == (stat >> 8);
        IO(rt, offset) = (uint16_t)((stat & ~4) | (match ? 4 : 0));
        return;
    }
    case GBA_REG_VCOUNT:
    case GBA_REG_KEYINPUT:
        return;  /* read-only */
    case GBA_REG_IE:
        IO(rt, offset) = merged & 0x3FFF;
        gba_irq_changed(rt);
        return;
    case GBA_REG_IF:
        IO(rt, offset) = (uint16_t)(old & ~(value & mask));  /* writing 1 acknowledges */
        gba_irq_changed(rt);
        return;
    case GBA_REG_IME:
        IO(rt, offset) = merged & 1;
        gba_irq_changed(rt);
        return;
    case GBA_REG_KEYCNT:
        if (rt->keys_last < 0x400)  /* newly chosen keys count as changed (as in mGBA) */
            rt->keys_last &= old | ~merged;
        IO(rt, offset) = merged & 0xC3FF;
        gba_keypad_check(rt);
        return;
    case GBA_REG_WAITCNT:
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        return;
    case GBA_REG_POSTFLG:  /* POSTFLG in the low byte, HALTCNT (write-only) in the high one */
        IO(rt, offset) = merged & 0x0001;
        if (mask & 0xFF00) {
            if (value & 0x8000)
                gba_stop(rt);
            else
                gba_halt(rt);
        }
        return;
    default:
        IO(rt, offset) = merged;
        return;
    }
}
