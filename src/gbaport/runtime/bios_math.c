/* bios_math.c - the BIOS's arithmetic: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq.
 *
 * Results follow GBATEK. Where the BIOS has no defined result (division by zero hangs it)
 * the runtime answers as mGBA's HLE BIOS does and warns once. The arctangents use the
 * BIOS's own polynomial, in 32-bit wrapping arithmetic like the ARM code it replaces. */
#include <math.h>

#include "gba_runtime.h"

static int32_t mul32(int32_t a, int32_t b) { return (int32_t)((uint32_t)a * (uint32_t)b); }

/* SWI 0x06 (and 0x07 with the operands swapped). */
void gba_bios_div(GbaRuntime *rt, int32_t num, int32_t den)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t quot, rem;
    if (den == 0) {
        gba_warn_once(rt, GBA_WARN_DIV_ZERO, "Div of %d by zero (the BIOS would hang)", (int)num);
        quot = num < 0 ? -1 : 1;
        rem = num;
        ctx->r[3] = 1;
    } else if (den == -1 && num == INT32_MIN) {
        quot = INT32_MIN;
        rem = 0;
        ctx->r[3] = 0x80000000u;
    } else {
        quot = num / den;
        rem = num % den;
        ctx->r[3] = quot < 0 ? 0u - (uint32_t)quot : (uint32_t)quot;
    }
    ctx->r[0] = (uint32_t)quot;
    ctx->r[1] = (uint32_t)rem;
    ctx->cycles += 100;
}

/* SWI 0x08: the integer square root. */
void gba_bios_sqrt(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t value = ctx->r[0], root = 0;
    for (uint32_t bit = 1u << 15; bit; bit >>= 1) {
        uint32_t trial = root | bit;
        if ((uint64_t)trial * trial <= value)
            root = trial;
    }
    ctx->r[0] = root;
    ctx->cycles += 60;
}

/* The BIOS's arctangent polynomial for a 1.14 fixed-point tangent. */
static int32_t arctan(int32_t i, int32_t *r1, int32_t *r3)
{
    int32_t a = -(mul32(i, i) >> 14);
    int32_t b = (mul32(0xA9, a) >> 14) + 0x390;
    static const int32_t terms[] = {0x91C, 0xFB6, 0x16AA, 0x2081, 0x3651, 0xA2F9};
    for (int k = 0; k < 6; k++)
        b = (mul32(b, a) >> 14) + terms[k];
    if (r1)
        *r1 = a;
    if (r3)
        *r3 = b;
    return mul32(i, b) >> 16;
}

/* SWI 0x09. */
void gba_bios_arctan(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t a, b;
    ctx->r[0] = (uint32_t)arctan((int32_t)ctx->r[0], &a, &b);
    ctx->r[1] = (uint32_t)a;
    ctx->r[3] = (uint32_t)b;
    ctx->cycles += 40;
}

static int32_t tangent(int32_t n, int32_t d) { return (int32_t)(((int64_t)n << 14) / d); }

/* SWI 0x0A: the angle of (x, y) as 0x0000-0xFFFF for 0 <= theta < 2 pi. */
void gba_bios_arctan2(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t x = (int32_t)ctx->r[0], y = (int32_t)ctx->r[1], angle;
    if (y == 0)
        angle = x >= 0 ? 0 : 0x8000;
    else if (x == 0)
        angle = y >= 0 ? 0x4000 : 0xC000;
    else if (y >= 0) {
        if (x >= 0 && x >= y)
            angle = arctan(tangent(y, x), NULL, NULL);
        else if (x < 0 && -x >= y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x8000;
        else
            angle = 0x4000 - arctan(tangent(x, y), NULL, NULL);
    } else {
        if (x <= 0 && -x > -y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x8000;
        else if (x > 0 && x >= -y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x10000;
        else
            angle = 0xC000 - arctan(tangent(x, y), NULL, NULL);
    }
    ctx->r[0] = (uint32_t)angle & 0xFFFF;
    ctx->cycles += 60;
}

/* SWI 0x1F: r0 = WaveData.freq / 2^((180 - key - fine/256) / 12), the WaveData at r0. */
void gba_bios_midi_key_to_freq(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    double freq = gba_read32(ctx, ctx->r[0] + 4);
    double semitones = 180.0 - (ctx->r[1] & 0xFF) - (ctx->r[2] & 0xFF) / 256.0;
    ctx->r[0] = (uint32_t)(freq / pow(2.0, semitones / 12.0));
    ctx->cycles += 80;
}
