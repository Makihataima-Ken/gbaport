"""Direct Sound, compared with mGBA: FIFO A and B fed by DMA at timer rates, volumes and
sides, SOUNDBIAS, a FIFO fed by the CPU running dry, FIFO resets, the sound hardware
switched off and on, a FIFO paced by a count-up timer, a timer that overflows every cycle,
and SOUNDBIAS's resolution bits.

The waves the DMA reads are 16 KiB, so a scene plays at most 16384 bytes a FIFO."""

import time

import pytest
from mgbaref import mgba_sound
from romtest import build_test_rom, run_rom
from soundtest import assert_script_matches, our_sound, script, sound_difference, word

SOUNDCNT_H, SOUNDCNT_X, SOUNDBIAS, FIFO_A, FIFO_B = 0x082, 0x084, 0x088, 0x0A0, 0x0A4
DMA1DAD, DMA1CNT_H, DMA2DAD, DMA2CNT_H = 0x0C0, 0x0C6, 0x0CC, 0x0D2
TM0CNT_L, TM0CNT_H, TM1CNT_L, TM1CNT_H = 0x100, 0x102, 0x104, 0x106
A_RIGHT, A_LEFT, A_TIMER1, A_RESET = 0x0100, 0x0200, 0x0400, 0x0800
B_RIGHT, B_LEFT, B_TIMER1, B_RESET = 0x1000, 0x2000, 0x4000, 0x8000
A_FULL, B_FULL = 0x0004, 0x0008
FIFO_DMA = 0xB640  # on, special timing, repeat, 32-bit, destination fixed


def feed(channel: int, fifo: int) -> list[tuple[int, int, int]]:
    """DMA `channel` (1 or 2) feeding FIFO `fifo` (its source is the ROM's wave)."""
    dad, cnt = (DMA1DAD, DMA1CNT_H) if channel == 1 else (DMA2DAD, DMA2CNT_H)
    return [(0, dad, fifo), (0, dad + 2, 0x0400), (0, cnt, FIFO_DMA)]


def rate(timer: int, cycles: int, frame: int = 0, control: int = 0x0080) -> list[tuple[int, int, int]]:
    low, high = (TM0CNT_L, TM0CNT_H) if timer == 0 else (TM1CNT_L, TM1CNT_H)
    return [(frame, low, 0x10000 - cycles), (frame, high, control)]


ON = [(0, SOUNDCNT_X, 0x0080)]
SCENES = {
    "fifo-a-16khz-both-sides": ON + [(0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET)]
    + feed(1, FIFO_A) + rate(0, 1024),
    "fifo-b-half-volume-right-on-timer-1": ON + [(0, SOUNDCNT_H, B_RIGHT | B_TIMER1 | B_RESET)]
    + feed(2, FIFO_B) + rate(1, 2048),
    "both-fifos-on-one-timer-and-a-low-bias": ON + [  # both change at once
        (0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET | B_FULL | B_RIGHT | B_RESET),
        (0, SOUNDBIAS, 0x0180),
    ] + feed(1, FIFO_A) + feed(2, FIFO_B) + rate(0, 1024),
    "a-fifo-the-cpu-fills-runs-dry": ON + [
        (0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET),
        word(0, FIFO_A, 0xC0807F40), word(0, FIFO_A, 0x10203040),
    ] + rate(0, 4000),
    "a-fifo-reset-mid-way": ON + [(0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET)]
    + feed(1, FIFO_A) + rate(0, 4096) + [(12, SOUNDCNT_H, A_FULL | A_LEFT | A_RESET)],
    "sound-off-and-on-again": ON + [(0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET)]
    + feed(1, FIFO_A) + rate(0, 1024) + [(10, SOUNDCNT_X, 0), (20, SOUNDCNT_X, 0x0080)],
    "fifo-b-on-a-count-up-timer": ON + [(0, SOUNDCNT_H, B_FULL | B_LEFT | B_RIGHT | B_TIMER1 | B_RESET)]
    + feed(2, FIFO_B) + rate(0, 300) + rate(1, 3, control=0x0084),
}


@pytest.mark.parametrize("writes", SCENES.values(), ids=SCENES.keys())
def test_direct_sound_sounds_like_mgba(writes):
    assert_script_matches(writes, frames=40)


@pytest.mark.parametrize("fifos", [1, 2], ids=["one-fifo", "both-fifos"])
def test_a_fifo_timer_that_overflows_every_cycle_does_not_slow_the_game(fifos):
    """A timer reloaded with 0xFFFF overflows every cycle, a game's mistake: the game keeps
    running (its write at frame 5 silences the sound), the sound keeps time with the
    frames, and the run takes less time than the GBA would."""
    control = A_FULL | A_LEFT | A_RIGHT | A_RESET
    feeds = feed(1, FIFO_A)
    if fifos == 2:
        control |= B_FULL | B_LEFT | B_RIGHT | B_RESET
        feeds += feed(2, FIFO_B)
    rom = build_test_rom("sound", script(
        ON + [(0, SOUNDCNT_H, control)] + feeds + rate(0, 1) + [(5, SOUNDCNT_H, 0)]))
    run_rom(rom, frames=1)  # builds the program
    start = time.perf_counter()
    run = run_rom(rom, frames=60)
    assert run.status == 4, run.stderr
    assert time.perf_counter() - start < 60 / 59.73  # faster than the GBA plays it
    sound = our_sound(rom, 60)
    # up to the last frame's VBlank, as test_sound_reference counts it
    assert len(sound) == ((160 - 126) * 1232 - (1008 - 117) + 59 * 280896) // 512
    assert any(s != (0, 0) for s in sound[:4 * 549])  # the FIFOs played
    assert set(sound[-30 * 549:]) == {(0, 0)}  # and the game's later write ran


def test_soundbias_resolution_bits_keep_the_pitch():
    """SOUNDBIAS bits 14-15 ask for more samples a second: mGBA then mixes 65536 (here),
    the runtime still 32768: every other one of mGBA's, from the first sound on."""
    rom = build_test_rom("sound", script(ON + [
        (0, SOUNDBIAS, 0x4200), (0, SOUNDCNT_H, A_FULL | A_LEFT | A_RIGHT | A_RESET),
    ] + feed(1, FIFO_A) + rate(0, 2048)))
    ours, reference = our_sound(rom, 40), mgba_sound(rom.data, 40)
    a = next(i for i, s in enumerate(ours) if s != (0, 0))
    b = next(i for i, s in enumerate(reference) if s != (0, 0))
    assert sound_difference(ours[a - 32:], reference[b - 64::2]) is None
