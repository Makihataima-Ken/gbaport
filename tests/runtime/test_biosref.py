"""The BIOS references against GBATEK's examples, and the compressors against their own
decompressors (so the streams the runtime tests feed it are valid)."""

import random

import biosref
import pytest


def test_div_follows_gbatek_and_c_truncation():
    assert biosref.div(-1234, 10) == (biosref.u32(-123), biosref.u32(-4), 123)  # GBATEK's example
    assert biosref.div(7, -2) == (biosref.u32(-3), 1, 3)
    assert biosref.div(0x80000000, -1) == (0x80000000, 0, 0x80000000)
    assert biosref.div(5, 0) == (1, 5, 1)  # mGBA's answer; the BIOS itself would hang


def test_sqrt_and_arctangents_at_known_points():
    assert [biosref.sqrt(v) for v in (0, 1, 15, 16, 0xFFFFFFFF)] == [0, 1, 3, 4, 0xFFFF]
    assert biosref.arctan(0)[0] == 0
    assert abs(biosref.arctan(0x4000)[0] - 0x2000) <= 8  # tan = 1: pi/4 is 0x2000
    axes = [biosref.arctan2(x, y) for x, y in ((5, 0), (0, 5), (-5, 0), (0, -5))]
    assert axes == [0x0000, 0x4000, 0x8000, 0xC000]
    for x, y, want in ((1, 1, 0x2000), (-1, 1, 0x6000), (-1, -1, 0xA000), (1, -1, 0xE000)):
        assert abs(biosref.arctan2(x * 0x1000, y * 0x1000) - want) <= 8


def test_affine_identity_and_quarter_turn():
    assert biosref.obj_affine(0x100, 0x100, 0) == (0x100, 0, 0, 0x100)
    assert biosref.obj_affine(0x100, 0x100, 0x4000) == (0, 0xFF00, 0x100, 0)  # 90 degrees
    assert biosref.bg_affine(0x1000, 0x2000, 0, 0, 0x100, 0x100, 0)[4:] == (0x1000, 0x2000)


def test_bit_unpack_adds_the_offset_to_non_zero_units():
    assert biosref.bit_unpack(bytes([0b11100100]), 2, 8, 0x10, False) == [0x13121100]
    assert biosref.bit_unpack(bytes([0b11100100]), 2, 8, 0x10, True) == [0x13121110]


@pytest.mark.parametrize("seed", range(6))
def test_compressors_round_trip(seed):
    rng = random.Random(seed)
    alphabet = rng.sample(range(256), 12)
    data = bytes(rng.choice(alphabet) if rng.random() < 0.7 else 0x55 for _ in range(rng.randrange(1, 900)))
    assert biosref.lz77_decompress(biosref.lz77_compress(data)) == data
    assert biosref.rl_decompress(biosref.rl_compress(data)) == data
    assert biosref.huffman_decompress(biosref.huffman_compress(data, 8)) == data
    assert biosref.huffman_decompress(biosref.huffman_compress(data, 4)) == data
