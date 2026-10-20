/* dma.c - the four DMA channels.
 *
 * Starting a channel (enable bit 0 -> 1) latches its source, destination and count. An
 * immediate channel runs at once; VBlank and HBlank channels run when the scheduler
 * triggers them. Channels 1 and 2 in special timing feed the sound FIFOs: when a FIFO asks,
 * the channel whose destination it is copies 4 words, whatever its count, width and
 * destination step say. Special timing on channels 0 and 3 (video capture) is not handled.
 * The transfer goes through the normal memory accessors, so it sees every region's rules.
 *
 * The CPU waits while a transfer runs, as long as in mGBA: 3 cycles to start, then for
 * each unit 2 cycles and the wait states of its source and destination (nonsequential for
 * the first, sequential after it), unit by unit, so a unit sees the time it is copied at
 * (the EEPROM's busy time counts from its last data bit). A FIFO's 4 words are not added:
 * they run from a timer's overflow inside the scheduler, and two FIFOs on a timer that
 * overflows every cycle would then ask for more time than passes, so the game would never
 * run again and the sound would run ahead of the frames. At the rates games play (two
 * FIFOs at 13379 to 32768 bytes a second), the time left out is 0.1% to 0.3% of the CPU's. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

static const uint32_t src_mask[4] = {0x07FFFFFF, 0x0FFFFFFF, 0x0FFFFFFF, 0x0FFFFFFF};
static const uint32_t dst_mask[4] = {0x07FFFFFF, 0x07FFFFFF, 0x07FFFFFF, 0x0FFFFFFF};

static uint32_t base(int n) { return GBA_REG_DMA0SAD + 12u * (uint32_t)n; }

static uint32_t reg32(const GbaRuntime *rt, uint32_t offset)
{
    return IO(rt, offset) | (uint32_t)IO(rt, offset + 2) << 16;
}

static uint32_t word_count(const GbaRuntime *rt, int n)
{
    uint32_t mask = n == 3 ? 0xFFFF : 0x3FFF;
    uint32_t count = IO(rt, base(n) + 8) & mask;
    return count ? count : mask + 1;  /* 0 means the maximum */
}

static int32_t step(int control, uint32_t size)
{
    switch (control) {
    case 1: return -(int32_t)size;  /* decrement */
    case 2: return 0;               /* fixed */
    default: return (int32_t)size;  /* increment (3: increment, then reload the destination) */
    }
}

static void run(GbaRuntime *rt, int n, int fifo)
{
    GbaCtx *ctx = &rt->cpu;
    GbaDma *d = &rt->dma[n];
    uint16_t control = IO(rt, base(n) + 10);
    uint32_t size = control & 0x0400 || fifo ? 4 : 2;
    int dst_control = fifo ? 2 : (control >> 5) & 3, src_control = (control >> 7) & 3;
    if (d->src >= 0x08000000u && d->src < 0x0E000000u && src_control == 1)
        src_control = 0;  /* the cartridge bus cannot count down */
    int32_t dst_step = step(dst_control, size), src_step = step(src_control, size);
    uint32_t count = fifo ? 4 : d->count;
    if (gba_save_is_eeprom(rt, d->dst) || gba_save_is_eeprom(rt, d->src))
        gba_eeprom_dma(rt, d->count);  /* the length tells the EEPROM's size */
    if (!fifo)  /* see the top of the file */
        ctx->cycles += 3;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t sr = gba_region(d->src), dr = gba_region(d->dst);
        if (size == 4)
            gba_write32(ctx, d->dst & ~3u, gba_read32(ctx, d->src & ~3u));
        else
            gba_write16(ctx, d->dst & ~1u, gba_read16(ctx, d->src & ~1u));
        d->src += (uint32_t)src_step;
        d->dst += (uint32_t)dst_step;
        if (fifo)
            continue;
        if (size == 4)
            ctx->cycles += 2u + (i ? ctx->s32[sr] + ctx->s32[dr] : ctx->n32[sr] + ctx->n32[dr]);
        else
            ctx->cycles += 2u + (i ? ctx->s16[sr] + ctx->s16[dr] : ctx->n16[sr] + ctx->n16[dr]);
    }
    int timing = (control >> 12) & 3;
    if ((control & 0x0200) && timing != 0) {  /* repeat: wait for the next trigger */
        d->count = word_count(rt, n);
        if (dst_control == 3)
            d->dst = reg32(rt, base(n) + 4) & dst_mask[n];
    } else {
        IO(rt, base(n) + 10) = control & ~0x8000;
    }
    if (control & 0x4000)
        gba_request_irq(rt, (uint16_t)(GBA_IRQ_DMA0 << n));
}

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control)
{
    uint16_t old = IO(rt, base(n) + 10);
    IO(rt, base(n) + 10) = control;
    if ((old & 0x8000) || !(control & 0x8000))
        return;
    GbaDma *d = &rt->dma[n];
    d->src = reg32(rt, base(n)) & src_mask[n];
    d->dst = reg32(rt, base(n) + 4) & dst_mask[n];
    d->count = word_count(rt, n);
    if (((control >> 12) & 3) == 0)
        run(rt, n, 0);
}

void gba_dma_trigger(GbaRuntime *rt, int timing)
{
    for (int n = 0; n < 4; n++) {
        uint16_t control = IO(rt, base(n) + 10);
        if ((control & 0x8000) && ((control >> 12) & 3) == timing)
            run(rt, n, 0);
    }
}

void gba_dma_fifo(GbaRuntime *rt, int fifo)
{
    for (int n = 1; n <= 2; n++) {
        uint16_t control = IO(rt, base(n) + 10);
        if ((control & 0x8000) && ((control >> 12) & 3) == 3 &&
            rt->dma[n].dst == GBA_REG_FIFO_A + 0x04000000u + 4u * (uint32_t)fifo) {
            run(rt, n, 1);
            return;
        }
    }
}
