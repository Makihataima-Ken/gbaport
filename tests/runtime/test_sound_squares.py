"""The PSG's square channels (1 and 2), compared with mGBA: duties, envelopes, lengths,
channel 1's sweep, frequency changes while a note plays, SOUNDCNT_L's volumes and sides,
SOUNDCNT_H's PSG volume, the sound hardware switched off and on, and the squares over a
FIFO's steady level. Plus what SOUNDCNT_X and the square registers read back."""

import pytest
from romtest import run_test
from soundtest import assert_script_matches, byte, word

SOUND1CNT_L, SOUND1CNT_H, SOUND1CNT_X, SOUND2CNT_L, SOUND2CNT_H = 0x060, 0x062, 0x064, 0x068, 0x06C
SOUNDCNT_L, SOUNDCNT_H, SOUNDCNT_X = 0x080, 0x082, 0x084
PSG_100 = 0x0002


def tone(duty: int = 2, length: int = 0, volume: int = 15, up: bool = False, step: int = 0) -> int:
    """SOUND1CNT_H / SOUND2CNT_L: length (6 bits), duty, envelope step time, direction and
    start volume."""
    return length | duty << 6 | step << 8 | up << 11 | volume << 12


def note(frequency: int, stop: bool = False, restart: bool = True) -> int:
    """SOUND1CNT_X / SOUND2CNT_H."""
    return frequency | stop << 14 | restart << 15


def sides(left: int = 0x33, right: int = 0x33, volume_left: int = 7, volume_right: int = 7) -> int:
    """SOUNDCNT_L: left (bits 4-7 of the high byte) and right channel masks, as 0xLR."""
    return volume_right | volume_left << 4 | ((left & 0xF0) | (right & 0x0F)) << 8


ON = [(0, SOUNDCNT_X, 0x0080), (0, SOUNDCNT_L, sides()), (0, SOUNDCNT_H, PSG_100)]
SCENES = {
    "four-duties": ON + [
        (0, SOUND1CNT_H, tone(0)), (0, SOUND1CNT_X, note(1920)),
        (10, SOUND1CNT_H, tone(1)), (10, SOUND1CNT_X, note(1920)),
        (20, SOUND1CNT_H, tone(2)), (20, SOUND1CNT_X, note(1920)),
        (30, SOUND1CNT_H, tone(3)), (30, SOUND1CNT_X, note(1920)),
    ],
    "envelopes-down-and-up": ON + [
        (0, SOUND2CNT_L, tone(2, volume=15, step=1)), (0, SOUND2CNT_H, note(1750)),
        (20, SOUND2CNT_L, tone(1, volume=0, up=True, step=3)), (20, SOUND2CNT_H, note(1500)),
    ],
    "lengths-end-notes": ON + [
        (0, SOUND1CNT_H, tone(2, length=20)), (0, SOUND1CNT_X, note(1800, stop=True)),
        (2, SOUND2CNT_L, tone(3, length=50, volume=9)), (2, SOUND2CNT_H, note(1650, stop=True)),
        (25, SOUND2CNT_L, tone(1, length=0, volume=12)), (25, SOUND2CNT_H, note(1700, stop=True)),
    ],
    "sweep-up-down-and-past-the-top": ON + [
        (0, SOUND1CNT_L, 0x0022), (0, SOUND1CNT_H, tone(2)), (0, SOUND1CNT_X, note(1000)),
        (15, SOUND1CNT_L, 0x001B), (15, SOUND1CNT_X, note(1900)),
        (30, SOUND1CNT_L, 0x0011), (30, SOUND1CNT_X, note(1600)),
    ],
    "frequency-changes-while-playing": ON + [
        (0, SOUND2CNT_L, tone(2, volume=10)), (0, SOUND2CNT_H, note(1600)),
        (8, SOUND2CNT_H, note(1700, restart=False)), (16, SOUND2CNT_H, note(1850, restart=False)),
        (24, SOUND2CNT_H, note(1300, restart=False)),
    ],
    "volumes-and-sides": [(0, SOUNDCNT_X, 0x0080), (0, SOUNDCNT_H, PSG_100),
                          (0, SOUNDCNT_L, sides(left=0x10, right=0x02, volume_left=3, volume_right=6))] + [
        (0, SOUND1CNT_H, tone(2, volume=12)), (0, SOUND1CNT_X, note(1700)),
        (0, SOUND2CNT_L, tone(1, volume=8)), (0, SOUND2CNT_H, note(1400)),
        (12, SOUNDCNT_H, 0x0001), (24, SOUNDCNT_H, 0x0000), (30, SOUNDCNT_L, sides(volume_left=1)),
    ],
    "sound-off-clears-and-ignores-writes": ON + [
        (0, SOUND1CNT_H, tone(2)), (0, SOUND1CNT_X, note(1800)),
        (10, SOUNDCNT_X, 0), (12, SOUND1CNT_H, tone(3)), (12, SOUND1CNT_X, note(1500)),
        (20, SOUNDCNT_X, 0x0080), (22, SOUNDCNT_L, sides()), (22, SOUNDCNT_H, PSG_100),
        (22, SOUND1CNT_H, tone(1)), (22, SOUND1CNT_X, note(1750)),
    ],
    "a-byte-at-a-time-like-game-boy-code": ON + [
        byte(0, SOUND1CNT_H, 0x80), byte(0, SOUND1CNT_H + 1, 0xF0),
        byte(0, SOUND1CNT_X, 0x80), byte(0, SOUND1CNT_X + 1, 0x87),  # 0x780, restart
        byte(10, SOUND1CNT_X, 0x20),                                 # bits 0-7 only: 0x720
        byte(20, SOUND1CNT_X + 1, 0x86),                             # bits 8-10, restart: 0x620
        byte(30, SOUNDCNT_L + 1, 0x12),                              # sides only
    ],
    "stop-written-later-counts-a-step": ON + [
        (0, SOUND1CNT_H, tone(2, length=60)), (0, SOUND1CNT_X, note(1800)),
        (5, SOUND1CNT_X, note(1800, stop=True, restart=False)),
    ],
}


@pytest.mark.parametrize("writes", SCENES.values(), ids=SCENES.keys())
def test_square_channels_sound_like_mgba(writes):
    assert_script_matches(writes, frames=40)


def test_squares_over_a_steady_fifo_sound_like_mgba():
    """FIFO A holds one level (7 words of 0x30 bytes, a byte every 524288 cycles) under
    both squares, at 50% and then 100%."""
    steady = [word(0, 0x0A0, 0x30303030) for _ in range(7)]
    assert_script_matches(ON + [(0, SOUNDCNT_H, PSG_100 | 0x0B00)] + steady + [
        (0, 0x100, 0x10000 - 512), (0, 0x102, 0x0083),
        (4, SOUND1CNT_H, tone(2)), (4, SOUND1CNT_X, note(1920)),  # once the FIFO plays
        (4, SOUND2CNT_L, tone(1, volume=9)), (4, SOUND2CNT_H, note(1500)),
        (20, SOUNDCNT_H, PSG_100 | 0x0B04),
    ], frames=40)


def test_soundcnt_x_reads_which_channels_play_and_registers_read_their_readable_bits():
    run_test("sound_status", frames=30).assert_passed()
