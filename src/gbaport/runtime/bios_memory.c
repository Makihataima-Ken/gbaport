/* bios_memory.c - the BIOS's memory calls: CpuSet, CpuFastSet, BitUnPack, BgAffineSet and
 * ObjAffineSet.
 *
 * Like the BIOS, CpuSet and CpuFastSet do nothing when their source is in the BIOS area
 * (0x00000000-0x01FFFFFF). The affine calls use a 256-entry sine table in 1.14 fixed point,
 * round(16384 * sin(2 pi i / 256)); the BIOS keeps its own table of the same kind, so
 * results can differ from it in the lowest bit. */
#include "gba_runtime.h"

static const int16_t sine[256] = {
    0, 402, 804, 1205, 1606, 2006, 2404, 2801, 3196, 3590, 3981, 4370, 4756, 5139, 5520, 5897,
    6270, 6639, 7005, 7366, 7723, 8076, 8423, 8765, 9102, 9434, 9760, 10080, 10394, 10702, 11003, 11297,
    11585, 11866, 12140, 12406, 12665, 12916, 13160, 13395, 13623, 13842, 14053, 14256, 14449, 14635, 14811, 14978,
    15137, 15286, 15426, 15557, 15679, 15791, 15893, 15986, 16069, 16143, 16207, 16261, 16305, 16340, 16364, 16379,
    16384, 16379, 16364, 16340, 16305, 16261, 16207, 16143, 16069, 15986, 15893, 15791, 15679, 15557, 15426, 15286,
    15137, 14978, 14811, 14635, 14449, 14256, 14053, 13842, 13623, 13395, 13160, 12916, 12665, 12406, 12140, 11866,
    11585, 11297, 11003, 10702, 10394, 10080, 9760, 9434, 9102, 8765, 8423, 8076, 7723, 7366, 7005, 6639,
    6270, 5897, 5520, 5139, 4756, 4370, 3981, 3590, 3196, 2801, 2404, 2006, 1606, 1205, 804, 402,
    0, -402, -804, -1205, -1606, -2006, -2404, -2801, -3196, -3590, -3981, -4370, -4756, -5139, -5520, -5897,
    -6270, -6639, -7005, -7366, -7723, -8076, -8423, -8765, -9102, -9434, -9760, -10080, -10394, -10702, -11003, -11297,
    -11585, -11866, -12140, -12406, -12665, -12916, -13160, -13395, -13623, -13842, -14053, -14256, -14449, -14635, -14811, -14978,
    -15137, -15286, -15426, -15557, -15679, -15791, -15893, -15986, -16069, -16143, -16207, -16261, -16305, -16340, -16364, -16379,
    -16384, -16379, -16364, -16340, -16305, -16261, -16207, -16143, -16069, -15986, -15893, -15791, -15679, -15557, -15426, -15286,
    -15137, -14978, -14811, -14635, -14449, -14256, -14053, -13842, -13623, -13395, -13160, -12916, -12665, -12406, -12140, -11866,
    -11585, -11297, -11003, -10702, -10394, -10080, -9760, -9434, -9102, -8765, -8423, -8076, -7723, -7366, -7005, -6639,
    -6270, -5897, -5520, -5139, -4756, -4370, -3981, -3590, -3196, -2801, -2404, -2006, -1606, -1205, -804, -402
};

static int in_bios(uint32_t addr) { return (addr & 0x0E000000u) == 0; }

/* SWI 0x0B: copy or fill r2 & 0x1FFFFF units of 16 bits (32 with bit 26); bit 24 fills. */
void gba_bios_cpu_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t mode = ctx->r[2], count = mode & 0x1FFFFF;
    uint32_t size = mode & (1u << 26) ? 4 : 2;
    uint32_t src = ctx->r[0] & ~(size - 1), dst = ctx->r[1] & ~(size - 1);
    int fill = (mode >> 24) & 1;
    if (in_bios(src) || (!fill && count && in_bios(src + count * size - 1)))
        return;
    uint32_t value = size == 4 ? gba_read32(ctx, src) : gba_read16(ctx, src);
    for (uint32_t i = 0; i < count; i++) {
        if (!fill)
            value = size == 4 ? gba_read32(ctx, src + i * size) : gba_read16(ctx, src + i * size);
        if (size == 4)
            gba_write32(ctx, dst + i * size, value);
        else
            gba_write16(ctx, dst + i * size, value);
    }
    ctx->cycles += 20 + 4 * (uint64_t)count;
}

/* SWI 0x0C: copy or fill 32-bit words in blocks of 8 (the count is rounded up). */
void gba_bios_cpu_fast_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t mode = ctx->r[2], count = ((mode & 0x1FFFFF) + 7) & ~7u;
    uint32_t src = ctx->r[0] & ~3u, dst = ctx->r[1] & ~3u;
    int fill = (mode >> 24) & 1;
    if (in_bios(src) || (!fill && count && in_bios(src + count * 4 - 1)))
        return;
    uint32_t value = gba_read32(ctx, src);
    for (uint32_t i = 0; i < count; i++) {
        if (!fill)
            value = gba_read32(ctx, src + 4 * i);
        gba_write32(ctx, dst + 4 * i, value);
    }
    ctx->cycles += 20 + 2 * (uint64_t)count;
}

/* SWI 0x10: widen units. The info block at r2 holds the source length in bytes (16 bits),
 * the source and destination unit widths (8 bits each) and an offset (bits 0-30) added to
 * non-zero units, or to every unit when bit 31 is set. Words go out with 32-bit writes. */
void gba_bios_bit_unpack(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1] & ~3u, info = ctx->r[2];
    uint32_t length = gba_read16(ctx, info & ~1u);
    uint32_t src_width = gba_read8(ctx, info + 2), dst_width = gba_read8(ctx, info + 3);
    uint32_t offset = gba_read32(ctx, (info + 4) & ~3u);
    int widths_ok = (src_width == 1 || src_width == 2 || src_width == 4 || src_width == 8) &&
                    (dst_width == 1 || dst_width == 2 || dst_width == 4 || dst_width == 8 ||
                     dst_width == 16 || dst_width == 32);
    if (!widths_ok) {
        gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "BitUnPack with unit widths %u and %u ignored",
                      (unsigned)src_width, (unsigned)dst_width);
        return;
    }
    uint32_t out = 0, used = 0;
    for (uint32_t i = 0; i < length; i++) {
        uint32_t byte = gba_read8(ctx, src + i);
        for (uint32_t shift = 0; shift < 8; shift += src_width) {
            uint32_t unit = (byte >> shift) & ((1u << src_width) - 1);
            if (unit || (offset >> 31))
                unit += offset & 0x7FFFFFFF;
            out |= unit << used;
            used += dst_width;
            if (used == 32) {
                gba_write32(ctx, dst, out);
                dst += 4;
                out = used = 0;
            }
        }
    }
    ctx->cycles += 20 + 8 * (uint64_t)length;
}

static void rotation(int32_t sx, int32_t sy, uint32_t angle, int32_t m[4])
{
    uint32_t theta = (angle & 0xFFFF) >> 8;
    int32_t sin = sine[theta], cos = sine[(theta + 64) & 0xFF];
    m[0] = (sx * cos) >> 14;
    m[1] = (sx * -sin) >> 14;
    m[2] = (sy * sin) >> 14;
    m[3] = (sy * cos) >> 14;
}

/* SWI 0x0E: r2 entries of 20 bytes at r0 (s32 texture centre x, y in 24.8; s16 screen
 * centre x, y; s16 scale x, y in 8.8; u16 angle) become 16-byte BG affine parameters at r1
 * (pa, pb, pc, pd, then the start point x, y in 24.8). */
void gba_bios_bg_affine_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1];
    for (uint32_t n = ctx->r[2]; n; n--, src += 20, dst += 16) {
        int32_t ox = (int32_t)gba_read32(ctx, src), oy = (int32_t)gba_read32(ctx, src + 4);
        int32_t cx = (int16_t)gba_read16(ctx, src + 8), cy = (int16_t)gba_read16(ctx, src + 10);
        int32_t m[4];
        rotation((int16_t)gba_read16(ctx, src + 12), (int16_t)gba_read16(ctx, src + 14),
                 gba_read16(ctx, src + 16), m);
        for (int k = 0; k < 4; k++)
            gba_write16(ctx, dst + 2 * k, (uint32_t)m[k] & 0xFFFF);
        gba_write32(ctx, dst + 8, (uint32_t)(ox - (m[0] * cx + m[1] * cy)));
        gba_write32(ctx, dst + 12, (uint32_t)(oy - (m[2] * cx + m[3] * cy)));
        ctx->cycles += 60;
    }
}

/* SWI 0x0F: r2 entries of 8 bytes at r0 (s16 scale x, y in 8.8; u16 angle) become pa, pb,
 * pc, pd, written r3 bytes apart (2 for a plain array, 8 to go straight into OAM). */
void gba_bios_obj_affine_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1], stride = ctx->r[3];
    for (uint32_t n = ctx->r[2]; n; n--, src += 8, dst += 4 * stride) {
        int32_t m[4];
        rotation((int16_t)gba_read16(ctx, src), (int16_t)gba_read16(ctx, src + 2),
                 gba_read16(ctx, src + 4), m);
        for (int k = 0; k < 4; k++)
            gba_write16(ctx, dst + k * stride, (uint32_t)m[k] & 0xFFFF);
        ctx->cycles += 40;
    }
}
