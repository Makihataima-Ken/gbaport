"""Sprites, compared with mGBA: shapes and sizes, colour depths, 1D and 2D tile mapping,
flips, rotation/scaling and double size, the screen's edges, priorities among sprites and
against backgrounds, the bitmap modes, and how many sprites a line has time for."""

import pytest
from rendertest import IDENTITY, assert_test_rom_matches, obj


def scene(dispcnt: int, objs: list[tuple[int, int, int]], matrices=(IDENTITY,), bgcnt0: int = 0) -> str:
    """testdata.h for sprites.c."""
    rows = ", ".join(f"{{{a}, {b}, {c}}}" for a, b, c in objs)
    mats = ", ".join(f"{{{a}, {b}, {c}, {d}}}" for a, b, c, d in matrices)
    return (f"#define DISPCNT 0x{dispcnt:04x}\n#define BGCNT0 0x{bgcnt0:04x}\n"
            f"#define OBJS {{{rows}}}\n#define MATRICES {{{mats}}}\n")


ALL_SIZES = [(shape, size) for shape in range(3) for size in range(4)]
GRID = [(8 + 58 * (i % 4), 4 + 52 * (i // 4)) for i in range(12)]

SCENES = {
    "shapes-16-colours-1d": scene(0x1040, [
        obj(x, y, shape, size, tile=24 * i, palette=i, hflip=i % 3 == 1, vflip=i % 4 == 2)
        for i, ((shape, size), (x, y)) in enumerate(zip(ALL_SIZES, GRID))
    ]),
    "shapes-256-colours-2d": scene(0x1000, [
        obj(x, y, shape, size, tile=37 * i + 1, colors256=True, hflip=i % 2 == 1)
        for i, ((shape, size), (x, y)) in enumerate(zip(ALL_SIZES, GRID))
    ]),
    "screen-edges": scene(0x1040, [
        obj(500, 20, 0, 2, tile=10), obj(230, 60, 1, 3, tile=200), obj(40, 250, 0, 3, tile=300),
        obj(100, 140, 2, 3, tile=400, colors256=True), obj(240, 10, 0, 1, tile=5),
        obj(10, 160, 0, 1, tile=6), obj(470, 200, 1, 3, tile=50),
    ]),
    "rotation-scaling": scene(0x1040, [
        obj(10, 10, 0, 2, tile=64, affine=0), obj(60, 10, 0, 2, tile=96, affine=1, double=True),
        obj(140, 20, 1, 3, tile=128, affine=2, colors256=True), obj(20, 90, 2, 3, tile=256, affine=3),
        obj(100, 90, 0, 3, tile=512, affine=0, double=True), obj(200, 120, 0, 1, tile=7, affine=1),
    ], matrices=[(0xDD, -0x80, 0x80, 0xDD), (0x80, 0, 0, 0x80), (0x100, 0x60, 0, 0x100),
                 (-0x120, 0x30, -0x30, 0x150)]),
    "matrices-that-make-no-picture": scene(0x1040, [
        obj(10, 10, 0, 2, tile=64, affine=0), obj(60, 10, 0, 3, tile=96, affine=1, double=True),
        obj(140, 40, 1, 3, tile=128, affine=2), obj(20, 90, 0, 3, tile=200, affine=3, double=True),
    ], matrices=[(0, 0, 0, 0), (0x7FFF, 0x7FFF, -0x8000, 0x7FFF), (-0x8000, 0, 0, -0x8000),
                 (1, 0, 0, 1)]),
    "priorities": scene(0x1140, [
        obj(20, 20, 0, 3, tile=0, priority=2), obj(50, 40, 0, 3, tile=64, priority=0),
        obj(90, 30, 0, 3, tile=128, priority=1), obj(120, 60, 0, 3, tile=192, priority=3),
        obj(30, 90, 1, 3, tile=256, priority=1), obj(40, 100, 1, 3, tile=320, priority=1),
    ], bgcnt0=0x1000 | 1),
    "bitmap-mode-keeps-low-tiles-for-the-picture": scene(0x1443, [
        obj(20, 20, 0, 3, tile=100), obj(100, 20, 0, 3, tile=600), obj(40, 90, 1, 3, tile=511),
        obj(140, 90, 1, 3, tile=700, colors256=True),
    ]),
    "line-time-runs-out": scene(0x1040, [
        obj(8 * i, 30 + i, 0, 3, tile=64 * (i % 8), affine=i % 2, double=True) for i in range(16)
    ], matrices=[(0x100, 0, 0, 0x100), (0xC0, 0x40, -0x40, 0xC0)]),
    "hblank-free-has-less-time": scene(0x1060, [
        obj(8 * i, 30 + i, 0, 3, tile=64 * (i % 8), affine=i % 2, double=True) for i in range(16)
    ], matrices=[(0x100, 0, 0, 0x100), (0xC0, 0x40, -0x40, 0xC0)]),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_sprites_look_like_mgba(data):
    assert_test_rom_matches("sprites", data)
