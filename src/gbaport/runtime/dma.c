/* dma.c - the four DMA channels.
 *
 * Starting a channel (enable bit 0 -> 1) latches its source, destination and count. An
 * immediate channel runs at once; VBlank and HBlank channels run when the scheduler
 * triggers them. Special timing (sound FIFOs, video capture) is not handled yet. The
 * transfer goes through the normal memory accessors, so it sees every region's rules. */
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

static void run(GbaRuntime *rt, int n)
{
    GbaCtx *ctx = &rt->cpu;
    GbaDma *d = &rt->dma[n];
    uint16_t control = IO(rt, base(n) + 10);
    uint32_t size = control & 0x0400 ? 4 : 2;
    int dst_control = (control >> 5) & 3, src_control = (control >> 7) & 3;
    if (d->src >= 0x08000000u && d->src < 0x0E000000u && src_control == 1)
        src_control = 0;  /* the cartridge bus cannot count down */
    int32_t dst_step = step(dst_control, size), src_step = step(src_control, size);
    for (uint32_t i = 0; i < d->count; i++) {
        if (size == 4)
            gba_write32(ctx, d->dst & ~3u, gba_read32(ctx, d->src & ~3u));
        else
            gba_write16(ctx, d->dst & ~1u, gba_read16(ctx, d->src & ~1u));
        d->src += (uint32_t)src_step;
        d->dst += (uint32_t)dst_step;
    }
    ctx->cycles += 4 + 2 * (uint64_t)d->count;
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
        run(rt, n);
}

void gba_dma_trigger(GbaRuntime *rt, int timing)
{
    for (int n = 0; n < 4; n++) {
        uint16_t control = IO(rt, base(n) + 10);
        if ((control & 0x8000) && ((control >> 12) & 3) == timing)
            run(rt, n);
    }
}
