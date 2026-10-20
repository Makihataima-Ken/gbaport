"""The PSG's wave channel (3), compared with mGBA: its five volumes, 32 samples from one
bank or 64 from both, lengths, switching banks and writing the other bank while it plays,
rate changes, switching it off and on, and next to a square."""

import pytest
from soundtest import assert_script_matches, word

SOUND1CNT_H, SOUND1CNT_X = 0x062, 0x064
SOUND3CNT_L, SOUND3CNT_H, SOUND3CNT_X, SOUNDCNT_L, SOUNDCNT_H, SOUNDCNT_X = (
    0x070, 0x072, 0x074, 0x080, 0x082, 0x084)
WAVE_RAM = 0x090
ON = [(0, SOUNDCNT_X, 0x0080), (0, SOUNDCNT_L, 0x7777), (0, SOUNDCNT_H, 0x0002)]
RAMP = [0x01234567, 0x89ABCDEF, 0xFEDCBA98, 0x76543210]
PULSES = [0xFF00FF00, 0x80808080, 0x0F0F0F0F, 0xC3C3C3C3]
FULL, HALF, QUARTER, THREE_QUARTERS, MUTE = 0x2000, 0x4000, 0x6000, 0x8000, 0x0000


def load(bank: int, words: list[int], frame: int = 0) -> list[tuple[int, int, int]]:
    """Writes `words` into wave RAM bank `bank`: the game writes the bank not selected."""
    return [(frame, SOUND3CNT_L, 0x40 if bank == 0 else 0x00)] + [
        word(frame, WAVE_RAM + 4 * i, value) for i, value in enumerate(words)]


def play(frame: int, rate: int, select: int = 0x80, volume: int = FULL, stop_after: int | None = None):
    length = 0 if stop_after is None else 256 - stop_after
    return [(frame, SOUND3CNT_L, select), (frame, SOUND3CNT_H, volume | length),
            (frame, SOUND3CNT_X, 0x8000 | (0x4000 if stop_after is not None else 0) | rate)]


SCENES = {
    "five-volumes": ON + load(0, RAMP) + play(0, 1800) + [
        (8, SOUND3CNT_H, HALF), (16, SOUND3CNT_H, QUARTER), (24, SOUND3CNT_H, THREE_QUARTERS),
        (32, SOUND3CNT_H, MUTE)],
    "64-samples-from-both-banks": ON + load(0, RAMP) + load(1, PULSES) + play(0, 1900, select=0xA0),
    "a-length-ends-it": ON + load(0, PULSES) + play(0, 1850, stop_after=150),
    "the-other-bank-written-then-chosen": ON + load(0, RAMP) + play(0, 1700) + [
        word(10, WAVE_RAM + 4 * i, value) for i, value in enumerate(PULSES)] + [
        (20, SOUND3CNT_L, 0xC0)],
    "rate-changes-and-a-restart": ON + load(0, RAMP) + play(0, 1600) + [
        (10, SOUND3CNT_X, 1750), (20, SOUND3CNT_X, 0x8000 | 1500)],
    "switched-off-and-on-by-bit-7": ON + load(0, RAMP) + play(0, 1800) + [
        (15, SOUND3CNT_L, 0x00)] + play(25, 1900),
    "wave-on-the-left-square-on-the-right": ON + load(0, RAMP) + play(0, 1950, volume=HALF) + [
        (0, SOUNDCNT_L, 0x4177), (0, SOUND1CNT_H, 0xA080), (0, SOUND1CNT_X, 0x8000 | 1700)],
}


@pytest.mark.parametrize("writes", SCENES.values(), ids=SCENES.keys())
def test_the_wave_channel_sounds_like_mgba(writes):
    assert_script_matches(writes, frames=40)
