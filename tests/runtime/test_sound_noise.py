"""The PSG's noise channel (4), compared with mGBA: 15-bit and 7-bit noise at several
rates (divider 0 among them), its envelope, a length that ends it, and next to a square.

The noise's timing starts at its restart, which can come a few cycles earlier or later
than in mGBA. At rates of a step every 1024 cycles or more (divider x 2 << shift >= 32),
that moves the noise in time; faster, it changes which of its steps the samples catch,
so faster rates cannot be compared sample by sample. For the same reason a noise that is
restarted (or stops) while it plays keeps a level that depends on that timing until its
next step, so each scene starts its noise from silence or after an envelope ended it."""

import pytest
from soundtest import assert_script_matches

SOUND1CNT_H, SOUND1CNT_X, SOUND4CNT_L, SOUND4CNT_H = 0x062, 0x064, 0x078, 0x07C
SOUNDCNT_L, SOUNDCNT_H, SOUNDCNT_X = 0x080, 0x082, 0x084
ON = [(0, SOUNDCNT_X, 0x0080), (0, SOUNDCNT_L, 0x8877), (0, SOUNDCNT_H, 0x0002)]


def envelope(volume: int = 15, up: bool = False, step: int = 0, length: int = 0) -> int:
    """SOUND4CNT_L."""
    return length | step << 8 | up << 11 | volume << 12


def noise(divider: int, shift: int, narrow: bool = False, stop: bool = False) -> int:
    """SOUND4CNT_H, restarting the noise."""
    return divider | narrow << 3 | shift << 4 | stop << 14 | 0x8000


SCENES = {  # each noise starts from silence (see above)
    "15-bit-noise": ON + [(0, SOUND4CNT_L, envelope()), (0, SOUND4CNT_H, noise(3, 4))],
    "15-bit-noise-divider-0": ON + [(0, SOUND4CNT_L, envelope()), (0, SOUND4CNT_H, noise(0, 5))],
    "7-bit-noise": ON + [
        (0, SOUND4CNT_L, envelope(volume=11)), (0, SOUND4CNT_H, noise(5, 6, narrow=True))],
    "an-envelope-fades-it-out-and-in-again": ON + [
        (0, SOUND4CNT_L, envelope(volume=15, step=1)), (0, SOUND4CNT_H, noise(2, 3)),
        (20, SOUND4CNT_L, envelope(volume=0, up=True, step=1)), (20, SOUND4CNT_H, noise(2, 3)),
    ],
    "a-length-ends-it": ON + [
        (0, SOUND4CNT_L, envelope(length=10)), (0, SOUND4CNT_H, noise(7, 6, stop=True)),
        (15, SOUND4CNT_L, envelope(volume=9, length=40)), (15, SOUND4CNT_H, noise(0, 5, stop=True)),
    ],
    "noise-on-the-right-square-on-the-left": [
        (0, SOUNDCNT_X, 0x0080), (0, SOUNDCNT_L, 0x1877), (0, SOUNDCNT_H, 0x0002),
        (0, SOUND4CNT_L, envelope(volume=12)), (0, SOUND4CNT_H, noise(1, 4)),
        (0, SOUND1CNT_H, 0xC080), (0, SOUND1CNT_X, 0x8000 | 1650),
    ],
}


@pytest.mark.parametrize("writes", SCENES.values(), ids=SCENES.keys())
def test_the_noise_channel_sounds_like_mgba(writes):
    assert_script_matches(writes, frames=40)
