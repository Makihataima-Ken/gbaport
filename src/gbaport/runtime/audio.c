/* audio.c - the GBA's sound, as samples for the host.
 *
 * The GBA mixes its sound channels into one left and one right value 32768 times a second
 * (every 512 cycles). The runtime makes those samples late, in order: gba_audio_run makes
 * every sample that ends by a given cycle, from the state the channels are in then, and is
 * called before anything changes that state. The host takes the samples with
 * gba_audio_take; when it does not, the oldest are dropped. */
#include <string.h>

#include "gba_runtime.h"

void gba_audio_reset(GbaRuntime *rt)
{
    GbaAudio *a = &rt->audio;
    memset(a, 0, sizeof *a);
    a->start = rt->cpu.cycles;
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

void gba_audio_run(GbaRuntime *rt, uint64_t now)
{
    GbaAudio *a = &rt->audio;
    while (a->start + (a->next + 1) * GBA_CYCLES_SAMPLE <= now) {
        emit(a, 0, 0);
        a->next++;
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
