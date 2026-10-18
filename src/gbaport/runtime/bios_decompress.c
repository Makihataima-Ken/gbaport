/* bios_decompress.c - the BIOS's decompressors: LZ77, Huffman, run-length and the
 * difference filters (GBATEK, "BIOS Decompression Functions").
 *
 * Every stream starts with a 32-bit header: the type in bits 4-7, a unit size in bits 0-3
 * (Huffman, filters) and the decompressed size in bytes in bits 8-31. The "Wram" variants
 * write bytes; the "Vram" variants collect two bytes and write halfwords, because VRAM
 * ignores byte writes. Huffman output goes out as 32-bit words. A stream of the wrong type
 * is ignored with a warning. */
#include "gba_runtime.h"

typedef struct {
    GbaCtx *ctx;
    uint32_t dst, size, written;
    int halfwords;
    uint32_t pending;           /* the low byte of a halfword not yet written */
    uint8_t window[0x1000];     /* the last 4 KiB written, for LZ77's back references */
} Output;

static void output_init(Output *out, GbaCtx *ctx, uint32_t dst, uint32_t size, int halfwords)
{
    out->ctx = ctx;
    out->dst = halfwords ? dst & ~1u : dst;
    out->size = size;
    out->written = 0;
    out->halfwords = halfwords;
    out->pending = 0;
}

static int output_full(const Output *out) { return out->written >= out->size; }

static void put(Output *out, uint32_t byte)
{
    if (output_full(out))
        return;
    byte &= 0xFF;
    out->window[out->written & 0xFFF] = (uint8_t)byte;
    if (!out->halfwords) {
        gba_write8(out->ctx, out->dst + out->written, byte);
    } else if (out->written & 1) {
        gba_write16(out->ctx, out->dst + out->written - 1, out->pending | byte << 8);
    } else {
        out->pending = byte;
    }
    out->written++;
}

static int check_type(GbaRuntime *rt, uint32_t header, uint32_t type, const char *name)
{
    if (((header >> 4) & 0xF) == type)
        return 1;
    gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "%s ignored a stream of type %u",
                  name, (unsigned)((header >> 4) & 0xF));
    return 0;
}

/* SWI 0x11 (Wram) and 0x12 (Vram). Flag bytes, MSB first: 0 = a literal byte, 1 = two
 * bytes giving a length of 3-18 and a distance of 1-4096 back into the output. */
void gba_bios_lz77(GbaRuntime *rt, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 1, "LZ77UnComp"))
        return;
    Output out;
    output_init(&out, ctx, ctx->r[1], header >> 8, halfwords);
    src += 4;
    while (!output_full(&out)) {
        uint32_t flags = gba_read8(ctx, src++);
        for (int bit = 7; bit >= 0 && !output_full(&out); bit--) {
            if (flags & (1u << bit)) {
                uint32_t a = gba_read8(ctx, src), b = gba_read8(ctx, src + 1);
                src += 2;
                uint32_t length = (a >> 4) + 3, distance = (((a & 0xF) << 8) | b) + 1;
                for (uint32_t k = 0; k < length; k++)
                    put(&out, out.window[(out.written - distance) & 0xFFF]);
            } else {
                put(&out, gba_read8(ctx, src++));
            }
        }
    }
    ctx->cycles += 30 + 6 * (uint64_t)out.size;
}

/* SWI 0x14 (Wram) and 0x15 (Vram). Flag byte: bit 7 set = the next byte repeated
 * (flag & 0x7F) + 3 times, clear = the next (flag & 0x7F) + 1 bytes as they are. */
void gba_bios_rl(GbaRuntime *rt, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 3, "RLUnComp"))
        return;
    Output out;
    output_init(&out, ctx, ctx->r[1], header >> 8, halfwords);
    src += 4;
    while (!output_full(&out)) {
        uint32_t flag = gba_read8(ctx, src++);
        if (flag & 0x80) {
            uint32_t byte = gba_read8(ctx, src++);
            for (uint32_t k = 0; k < (flag & 0x7F) + 3; k++)
                put(&out, byte);
        } else {
            for (uint32_t k = 0; k <= (flag & 0x7F); k++)
                put(&out, gba_read8(ctx, src++));
        }
    }
    ctx->cycles += 30 + 4 * (uint64_t)out.size;
}

/* SWI 0x16 (8-bit units, Wram), 0x17 (8-bit, Vram) and 0x18 (16-bit units): each unit is
 * the previous one plus the stored difference. */
void gba_bios_diff(GbaRuntime *rt, int unit, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 8, "DiffUnFilter"))
        return;
    uint32_t size = header >> 8;
    src += 4;
    if (unit == 2) {
        uint32_t dst = ctx->r[1] & ~1u, value = 0;
        for (uint32_t i = 0; i + 1 < size; i += 2) {
            value = (value + gba_read16(ctx, (src + i) & ~1u)) & 0xFFFF;
            gba_write16(ctx, dst + i, value);
        }
    } else {
        Output out;
        output_init(&out, ctx, ctx->r[1], size, halfwords);
        uint32_t value = 0;
        for (uint32_t i = 0; i < size; i++) {
            value = (value + gba_read8(ctx, src + i)) & 0xFF;
            put(&out, value);
        }
    }
    ctx->cycles += 30 + 3 * (uint64_t)size;
}

/* SWI 0x13. After the header: the tree size byte (the bit stream starts (size + 1) * 2
 * bytes after it), then the tree, root first. A node's children are at
 * (node address & ~1) + (node & 0x3F) * 2 + 2 and one further; bit 7 (child 0) and bit 6
 * (child 1) mark children that are data. The bit stream is in 32-bit words, bit 31 first.
 * Units (4 or 8 bits) fill 32-bit output words from the low end. */
void gba_bios_huffman(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0] & ~3u, dst = ctx->r[1] & ~3u, header = gba_read32(ctx, src);
    if (!check_type(rt, header, 2, "HuffUnComp"))
        return;
    uint32_t bits = header & 0xF, size = header >> 8;
    if (bits != 4 && bits != 8) {
        gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "HuffUnComp ignored %u-bit units", (unsigned)bits);
        return;
    }
    uint32_t root = src + 5, stream = src + 4 + (gba_read8(ctx, src + 4) + 1) * 2;
    uint32_t node = root, word = 0, word_bits = 0, written = 0;
    while (written < size) {
        uint32_t code = gba_read32(ctx, stream);
        stream += 4;
        for (int k = 31; k >= 0 && written < size; k--) {
            uint32_t bit = (code >> k) & 1, value = gba_read8(ctx, node);
            uint32_t child = (node & ~1u) + (value & 0x3F) * 2 + 2 + bit;
            if (!(value & (0x80u >> bit))) {
                node = child;
                continue;
            }
            word |= gba_read8(ctx, child) << word_bits;
            word_bits += bits;
            node = root;
            if (word_bits == 32) {
                gba_write32(ctx, dst + written, word);
                written += 4;
                word = word_bits = 0;
            }
        }
    }
    ctx->cycles += 30 + 10 * (uint64_t)size;
}
