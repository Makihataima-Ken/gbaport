/* audio.c - the GBA's sound, as samples for the host.
 *
 * The GBA mixes its sound channels into one left and one right value 32768 times a second
 * (every 512 cycles). The runtime makes those samples late, in order: gba_audio_run makes
 * every sample that ends by a given cycle, from the state the channels are in then, and is
 * called before anything changes that state. The host takes the samples with
 * gba_audio_take; when it does not, the oldest are dropped. The levels are mGBA's:
 * the channels' sum plus SOUNDBIAS is clamped to 0-0x3FF, the bias taken away again and
 * the result multiplied by 48, which fits 16 bits for any bias from 0x156 to 0x2AA (mGBA
 * wraps around past that; here the level stops at the 16-bit limit).
 *
 * Direct Sound: FIFO A and B hold up to 8 words of signed 8-bit samples. When the timer
 * SOUNDCNT_H chooses for a FIFO overflows, the FIFO plays its next byte; when 3 words or
 * fewer are left, the DMA channel (1 or 2) that writes to it in special timing copies 4
 * more. The byte plays at 50% or 100% (SOUNDCNT_H bits 2 and 3), on the left and right as
 * SOUNDCNT_H says. A FIFO that runs dry keeps playing what is left of its last word.
 *
 * The PSG's four channels (psg.c) are added before the FIFOs, at 25%, 50% or 100% as
 * SOUNDCNT_H's bits 0-1 say. Its frame sequencer steps every 32768 cycles; a sample that
 * ends when a step comes is made before the step. While the sound hardware is off
 * (SOUNDCNT_X bit 7), the PSG's registers ignore writes; wave RAM does not. */
#include <string.h>

#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

void gba_audio_reset(GbaRuntime *rt)
{
    GbaAudio *a = &rt->audio;
    memset(a, 0, sizeof *a);
    a->start = rt->cpu.cycles;
    gba_psg_reset(&a->psg);
}

/* What a channel sum sounds like through SOUNDBIAS. */
static int16_t level(int value, int bias)
{
    value += bias;
    value = value < 0 ? 0 : value > 0x3FF ? 0x3FF : value;
    value = (value - bias) * 48;
    return (int16_t)(value < -32768 ? -32768 : value > 32767 ? 32767 : value);
}

static void emit(GbaAudio *a, int16_t left, int16_t right)
{
    uint32_t at = (a->first + a->count) % GBA_SOUND_BUFFER;
    if (a->count == GBA_SOUND_BUFFER)
        a->first = (a->first + 1) % GBA_SOUND_BUFFER;
    else
        a->count++;
    a->buffer[at][0] = left;
    a->buffer[at][1] = right;
}

static void mix(GbaRuntime *rt)
{
    GbaAudio *a = &rt->audio;
    uint16_t control = IO(rt, GBA_REG_SOUNDCNT_H);
    int left, right;
    gba_psg_mix(&a->psg, &left, &right);
    left >>= 4 - (control & 3);
    right >>= 4 - (control & 3);
    for (int i = 0; i < 2; i++) {
        int value = (a->fifo[i].sample * 4) >> !(control & (4 << i));
        if (control & (0x200 << 4 * i))
            left += value;
        if (control & (0x100 << 4 * i))
            right += value;
    }
    int bias = IO(rt, GBA_REG_SOUNDBIAS) & 0x3FE;
    emit(a, level(left, bias), level(right, bias));
}

void gba_audio_run(GbaRuntime *rt, uint64_t now)
{
    GbaAudio *a = &rt->audio;
    for (;;) {
        uint64_t end = a->start + (a->next + 1) * GBA_CYCLES_SAMPLE;
        uint64_t tick = a->start + a->tick * GBA_CYCLES_TICK;
        if (end <= tick && end <= now) {
            gba_psg_run(&a->psg, (int64_t)(a->next * GBA_CYCLES_SAMPLE), 0xF);
            mix(rt);
            a->next++;
        } else if (tick <= now) {
            gba_psg_tick(&a->psg, (int64_t)(tick - a->start));
            a->tick++;
        } else {
            return;
        }
    }
}

uint32_t gba_audio_take(GbaRuntime *rt, int16_t (*out)[2], uint32_t max)
{
    GbaAudio *a = &rt->audio;
    gba_audio_run(rt, rt->cpu.cycles);
    uint32_t n = a->count < max ? a->count : max;
    for (uint32_t i = 0; i < n; i++) {
        out[i][0] = a->buffer[(a->first + i) % GBA_SOUND_BUFFER][0];
        out[i][1] = a->buffer[(a->first + i) % GBA_SOUND_BUFFER][1];
    }
    a->first = (a->first + n) % GBA_SOUND_BUFFER;
    a->count -= n;
    return n;
}

static void push(GbaFifo *f, uint32_t value)
{
    f->data[f->write] = value;
    f->write = (f->write + 1) & 7;
}

void gba_audio_fifo_write(GbaRuntime *rt, int fifo, uint32_t value)
{
    uint32_t offset = GBA_REG_FIFO_A + 4u * (uint32_t)fifo;
    IO(rt, offset) = (uint16_t)value;
    IO(rt, offset + 2) = (uint16_t)(value >> 16);
    push(&rt->audio.fifo[fifo], value);
}

/* The FIFO's timer overflowed: the next byte plays, and DMA may top the FIFO up. */
static void play(GbaRuntime *rt, int i)
{
    GbaFifo *f = &rt->audio.fifo[i];
    uint32_t size = (f->write - f->read) & 7;
    if (!f->remaining && size) {
        f->word = (int32_t)f->data[f->read];
        f->remaining = 4;
        f->read = (f->read + 1) & 7;
    }
    f->sample = (int8_t)f->word;
    if (f->remaining) {
        f->word >>= 8;
        f->remaining--;
    }
    if (size < 4)
        gba_dma_fifo(rt, i);
}

void gba_audio_timer(GbaRuntime *rt, int n, uint64_t when)
{
    if (!rt->audio.enable)
        return;
    uint16_t control = IO(rt, GBA_REG_SOUNDCNT_H);
    for (int i = 0; i < 2; i++) {
        if ((control & (0x300 << 4 * i)) && ((control >> (10 + 4 * i)) & 1) == n) {
            gba_audio_run(rt, when);
            play(rt, i);
        }
    }
}

uint16_t gba_audio_write(GbaRuntime *rt, uint32_t offset, uint16_t value, uint16_t mask)
{
    GbaAudio *a = &rt->audio;
    uint16_t old = IO(rt, offset);
    gba_audio_run(rt, rt->cpu.cycles);
    int64_t t = (int64_t)(rt->cpu.cycles - a->start);
    if (offset >= GBA_REG_SOUND_FIRST && offset <= GBA_REG_SOUNDCNT_L) {
        if (!a->enable)
            return old;
        uint16_t bits = gba_psg_write(&a->psg, t, offset, value, mask) & mask;
        return (uint16_t)((old & ~mask) | (value & bits));
    }
    value = (uint16_t)((old & ~mask) | (value & mask));
    switch (offset) {
    case GBA_REG_SOUNDCNT_H:
        for (int i = 0; i < 2; i++)
            if (value & (0x0800 << 4 * i))  /* reset: the FIFO is empty */
                a->fifo[i].read = a->fifo[i].write = 0;
        return value & 0x770F;
    case GBA_REG_SOUNDCNT_X:
        a->enable = (value >> 7) & 1;
        gba_psg_enable(&a->psg, t, a->enable);
        if (!a->enable) {  /* the sound hardware off: its registers clear */
            for (uint32_t r = GBA_REG_SOUND_FIRST; r < GBA_REG_SOUNDCNT_H; r += 2)
                IO(rt, r) = 0;
            IO(rt, GBA_REG_SOUNDCNT_H) &= 0xFF00;
        }
        return (uint16_t)((value & 0x0080) | gba_psg_status(&a->psg));
    case GBA_REG_SOUNDBIAS:
        return value & 0xC3FE;
    case GBA_REG_WAVE_RAM: case GBA_REG_WAVE_RAM + 2: case GBA_REG_WAVE_RAM + 4:
    case GBA_REG_WAVE_RAM + 6: case GBA_REG_WAVE_RAM + 8: case GBA_REG_WAVE_RAM + 10:
    case GBA_REG_WAVE_RAM + 12: case GBA_REG_WAVE_RAM + 14: {  /* with the other half stored */
        uint32_t low = offset & ~3u;
        uint32_t word = offset & 2 ? IO(rt, low) | (uint32_t)value << 16
                                   : value | (uint32_t)IO(rt, low + 2) << 16;
        gba_psg_wave_write(&a->psg, t, (int)(offset - GBA_REG_WAVE_RAM) / 4, word);
        return value;
    }
    case GBA_REG_FIFO_A:
    case GBA_REG_FIFO_A + 2:
    case GBA_REG_FIFO_B:
    case GBA_REG_FIFO_B + 2: {  /* a halfword: a whole word goes in, the other half as stored */
        uint32_t low = offset & ~3u;
        uint32_t word = offset & 2 ? IO(rt, low) | (uint32_t)value << 16
                                   : value | (uint32_t)IO(rt, low + 2) << 16;
        push(&a->fifo[(offset - GBA_REG_FIFO_A) / 4], word);
        return value;
    }
    default:
        return value;
    }
}

uint16_t gba_audio_read(GbaRuntime *rt, uint32_t offset)
{
    gba_audio_run(rt, rt->cpu.cycles);
    if (offset >= GBA_REG_WAVE_RAM && offset < GBA_REG_WAVE_RAM + 16) {
        int64_t t = (int64_t)(rt->cpu.cycles - rt->audio.start);
        uint32_t word = gba_psg_wave_read(&rt->audio.psg, t, (int)(offset - GBA_REG_WAVE_RAM) / 4);
        return (uint16_t)(offset & 2 ? word >> 16 : word);
    }
    if (offset == GBA_REG_SOUNDCNT_X)
        return (uint16_t)((IO(rt, offset) & 0x0080) | gba_psg_status(&rt->audio.psg));
    return IO(rt, offset);
}

void gba_audio_clear(GbaRuntime *rt)
{
    memset(rt->audio.psg.wave.ram, 0, sizeof rt->audio.psg.wave.ram);
    for (uint32_t r = GBA_REG_SOUND_FIRST; r <= GBA_REG_SOUNDCNT_X; r += 2)
        IO(rt, r) = gba_audio_write(rt, r, 0, 0xFFFF);
    IO(rt, GBA_REG_SOUNDBIAS) = gba_audio_write(rt, GBA_REG_SOUNDBIAS, 0x200, 0xFFFF);
}
