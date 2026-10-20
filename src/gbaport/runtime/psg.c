/* psg.c - the GBA's four Game Boy sound channels (the PSG) and their frame sequencer.
 *
 * Channels 1 and 2 play square waves: 8 steps a period, high for 1, 2, 4 or 6 of them
 * (the duty), each step 16 (2048 - frequency) cycles long. Every channel's level is 0-15,
 * the envelope's volume when the wave is high. The frame sequencer steps every 32768 cycles
 * from the game's start (512 times a second); its steps 0, 2, 4 and 6 count lengths down
 * (a channel with "stop" set ends when its length runs out), steps 2 and 6 move channel
 * 1's sweep, and step 7 moves the envelopes.
 *
 * Each register byte is one of the Game Boy's NRxx registers and is written on its own:
 * a halfword write is its low byte, then its high byte (so a 16-bit frequency write puts
 * bits 0-7 in before bits 8-10 and the restart, as on a Game Boy).
 *
 * The details GBATEK leaves open follow mGBA: a channel's level changes only when its wave
 * steps, it is restarted or its envelope moves (not when its registers are written); a
 * channel that stops keeps its last level; a square's wave keeps stepping from where it
 * was, in step with the game's start, while it plays or its registers are written; an
 * envelope that reaches 0 (or 15) stops moving; writing "stop" in the half of a frame
 * sequencer step that does not count lengths counts one more. */
#include <string.h>

#include "gba_runtime.h"

static const int DUTY[4][8] = {
    {0, 0, 0, 0, 0, 0, 0, 1}, {1, 0, 0, 0, 0, 0, 0, 1}, {1, 0, 0, 0, 0, 1, 1, 1}, {0, 1, 1, 1, 1, 1, 1, 0},
};

void gba_psg_reset(GbaPsg *p)
{
    memset(p, 0, sizeof *p);
    p->square[0].sweep_time = 8;
    for (int i = 0; i < 2; i++)
        p->square[i].env.dead = 2;
}

/* ---- envelopes and lengths ---- */

static void envelope_dead(GbaEnvelope *e)
{
    if (!e->step_time)
        e->dead = e->volume ? 1 : 2;
    else if (!e->up && !e->volume)
        e->dead = 2;
    else if (e->up && e->volume == 15)
        e->dead = 1;
    else if (e->dead) {
        e->next_step = e->step_time;
        e->dead = 0;
    }
}

/* NRx2; returns whether the channel can still sound (its DAC is on). */
static int envelope_write(GbaEnvelope *e, uint8_t value)
{
    e->step_time = value & 7;
    e->up = (value >> 3) & 1;
    e->initial = value >> 4;
    envelope_dead(e);
    return e->initial || e->up;
}

static int envelope_restart(GbaEnvelope *e)
{
    e->volume = e->initial;
    e->next_step = e->step_time;
    envelope_dead(e);
    return e->initial || e->up;
}

static void envelope_step(GbaEnvelope *e)
{
    e->volume += e->up ? 1 : -1;
    if (e->volume >= 15) {
        e->volume = 15;
        e->dead = 1;
    } else if (e->volume <= 0) {
        e->volume = 0;
        e->dead = 2;
    } else {
        e->next_step = e->step_time;
    }
}

/* NRx4's bit 6 ("stop") and bit 7 (restart) for a length of up to `full` steps: writing
 * stop in the half of a frame sequencer step that does not count lengths counts one at
 * once, and a restart with no length left starts a full one. */
static void length_control(int *length, int *stop, int *playing, uint8_t value, int full, int frame)
{
    int was_stop = *stop;
    *stop = (value >> 6) & 1;
    if (!was_stop && *stop && *length && !(frame & 1) && --*length == 0)
        *playing = 0;
    if ((value & 0x80) && !*length) {
        *length = full;
        if (*stop && !(frame & 1))
            --*length;
    }
}

/* ---- the squares ---- */

static void square_level(GbaSquare *s) { s->sample = DUTY[s->env.duty][s->index] * s->env.volume; }

/* Brings the wave's step up to time t (a silent channel waits, unless `forced`). */
static void square_run(GbaSquare *s, int64_t t, int forced)
{
    if (!forced && !(s->playing && s->env.dead != 2))
        return;
    int64_t period = 16 * (2048 - s->frequency), diff = t - s->last_update;
    if (diff >= period) {
        int64_t steps = diff / period;
        s->index = (int)((s->index + steps) & 7);
        s->last_update += steps * period;
        square_level(s);
    }
}

/* Channel 1's sweep: the next frequency; 0 when it goes past 2047 (the channel stops). */
static int sweep(GbaSquare *s, int initial)
{
    if (initial || s->sweep_time != 8) {
        int frequency = s->real_frequency;
        if (s->sweep_down) {
            frequency -= frequency >> s->sweep_shift;
            if (!initial && frequency >= 0) {
                s->frequency = frequency;
                s->real_frequency = frequency;
            }
        } else {
            frequency += frequency >> s->sweep_shift;
            if (frequency >= 2048)
                return 0;
            if (!initial && s->sweep_shift) {
                s->frequency = frequency;
                s->real_frequency = frequency;
                if (!sweep(s, 1))
                    return 0;
            }
        }
        s->swept = 1;
    }
    s->sweep_step = s->sweep_time;
    return 1;
}

/* NR14 / NR24: frequency bits 8-10, stop, restart. */
static void square_control(GbaPsg *p, int n, uint8_t value)
{
    GbaSquare *s = &p->square[n];
    s->frequency = (s->frequency & 0xFF) | (value & 7) << 8;
    length_control(&s->length, &s->stop, &s->playing, value, 64, p->frame);
    if (value & 0x80) {
        s->playing = envelope_restart(&s->env);
        if (n == 0) {
            s->real_frequency = s->frequency;
            s->sweep_step = s->sweep_time;
            s->sweep_on = s->sweep_step != 8 || s->sweep_shift;
            s->swept = 0;
            if (s->playing && s->sweep_shift)
                s->playing = sweep(s, 1);
        }
        square_level(s);
    }
}

/* ---- the PSG ---- */

void gba_psg_run(GbaPsg *p, int64_t t, int channels)
{
    if (!p->enable)
        return;
    for (int n = 0; n < 2; n++)
        if (channels & (1 << n))
            square_run(&p->square[n], t, channels == 1 << n);
}

void gba_psg_tick(GbaPsg *p, int64_t t)
{
    if (!p->enable)
        return;
    gba_psg_run(p, t, 0x7);
    p->frame = (p->frame + 1) & 7;
    GbaSquare *s1 = &p->square[0];
    switch (p->frame) {
    case 2:
    case 6:
        if (s1->sweep_on && --s1->sweep_step == 0 && !sweep(s1, 0))
            s1->playing = 0;
        /* fall through */
    case 0:
    case 4:
        for (int n = 0; n < 2; n++) {
            GbaSquare *s = &p->square[n];
            if (s->length && s->stop && --s->length == 0)
                s->playing = 0;
        }
        break;
    case 7:
        for (int n = 0; n < 2; n++) {
            GbaSquare *s = &p->square[n];
            if (s->playing && !s->env.dead && --s->env.next_step == 0) {
                envelope_step(&s->env);
                square_level(s);
            }
        }
        break;
    default:
        break;
    }
}

/* One register byte (0x060-0x081), as its NRxx register; the channel it belongs to is
 * brought up to time first. */
static void write_byte(GbaPsg *p, int64_t t, uint32_t offset, uint8_t value)
{
    GbaSquare *s1 = &p->square[0];
    switch (offset) {
    case 0x060: {  /* NR10: sweep */
        gba_psg_run(p, t, 1);
        int was_down = s1->sweep_down;
        s1->sweep_shift = value & 7;
        s1->sweep_down = (value >> 3) & 1;
        if (s1->swept && was_down && !s1->sweep_down)
            s1->playing = 0;
        s1->swept = 0;
        s1->sweep_time = (value >> 4) & 7;
        if (!s1->sweep_time)
            s1->sweep_time = 8;
        break;
    }
    case 0x062:  /* NR11, NR21: length, duty */
    case 0x068: {
        int k = offset == 0x068;
        gba_psg_run(p, t, 1 << k);
        p->square[k].env.duty = value >> 6;
        p->square[k].length = 64 - (value & 0x3F);
        break;
    }
    case 0x063:  /* NR12, NR22: envelope */
    case 0x069: {
        int k = offset == 0x069;
        gba_psg_run(p, t, 1 << k);
        if (!envelope_write(&p->square[k].env, value))
            p->square[k].playing = 0;
        break;
    }
    case 0x064:  /* NR13, NR23: frequency bits 0-7 */
    case 0x06C: {
        int k = offset == 0x06C;
        gba_psg_run(p, t, 1 << k);
        p->square[k].frequency = (p->square[k].frequency & 0x700) | value;
        break;
    }
    case 0x065:  /* NR14, NR24 */
    case 0x06D:
        gba_psg_run(p, t, offset == 0x065 ? 1 : 2);
        square_control(p, offset == 0x06D, value);
        break;
    case 0x080:  /* NR50: volumes */
        gba_psg_run(p, t, 0xF);
        p->volume_right = value & 7;
        p->volume_left = (value >> 4) & 7;
        break;
    case 0x081:  /* NR51: sides */
        gba_psg_run(p, t, 0xF);
        p->sides = value;
        break;
    default:
        break;
    }
}

/* The bits of each register (0x060-0x080, by halfword) that read back. */
static uint16_t readable(uint32_t offset)
{
    switch (offset) {
    case 0x060: return 0x007F;
    case 0x062: case 0x068: return 0xFFC0;
    case 0x064: case 0x06C: return 0x4000;
    case 0x080: return 0xFF77;
    default: return 0;
    }
}

uint16_t gba_psg_write(GbaPsg *p, int64_t t, uint32_t offset, uint16_t value, uint16_t mask)
{
    if (mask & 0x00FF)
        write_byte(p, t, offset, (uint8_t)value);
    if (mask & 0xFF00)
        write_byte(p, t, offset + 1, (uint8_t)(value >> 8));
    return readable(offset);
}

void gba_psg_enable(GbaPsg *p, int64_t t, int on)
{
    if (!on) {
        for (int n = 0; n < 2; n++)
            p->square[n].playing = 0;
        p->enable = 0;
        for (uint32_t r = 0x060; r <= 0x080; r += 2)
            gba_psg_write(p, t, r, 0, 0xFFFF);
    } else if (!p->enable) {
        p->enable = 1;
        p->frame = 7;
    }
}

int gba_psg_status(const GbaPsg *p)
{
    return p->square[0].playing | p->square[1].playing << 1;
}

void gba_psg_mix(const GbaPsg *p, int *left, int *right)
{
    int levels[2] = {p->square[0].sample, p->square[1].sample};
    int l = 0, r = 0;
    for (int n = 0; n < 2; n++) {
        if (p->sides & (0x10 << n))
            l += levels[n];
        if (p->sides & (0x01 << n))
            r += levels[n];
    }
    *left = (l << 3) * (1 + p->volume_left);
    *right = (r << 3) * (1 + p->volume_right);
}
