"""Mosaic, compared with mGBA: text, rotation/scaling and bitmap backgrounds, and sprites
(plain and rotating), including groups cut by a window."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG2CNT, BG0HOFS, BG0VOFS = 0x000, 0x008, 0x00C, 0x010, 0x012
BG2PA, BG2PB, BG2PC, BG2PD, BG2X, BG2Y = 0x020, 0x022, 0x024, 0x026, 0x028, 0x02C
WIN0H, WIN0V, WININ, WINOUT, MOSAIC = 0x040, 0x044, 0x048, 0x04A, 0x04C


def mosaic(bg_h: int, bg_v: int, obj_h: int = 1, obj_v: int = 1) -> tuple[int, int]:
    return MOSAIC, (bg_h - 1) | (bg_v - 1) << 4 | (obj_h - 1) << 8 | (obj_v - 1) << 12


ROTATE = [(BG2PA, 0xDD), (BG2PB, 0xFF80), (BG2PC, 0x80), (BG2PD, 0xDD),
          (BG2X, 0xD800), (BG2X + 2, 0xFFFF), (BG2Y, 0xEC00), (BG2Y + 2, 0xFFFF)]  # (-40, -20)
SPRITES = [obj(3, 10, 0, 3, tile=0), obj(70, 20, 1, 3, tile=64, hflip=True),
           obj(150, 30, 2, 3, tile=128, vflip=True), obj(201, 100, 0, 2, tile=200),
           obj(40, 250, 0, 3, tile=300)]
SPRITES = [(a0 | 0x1000, a1, a2) for a0, a1, a2 in SPRITES]  # all with mosaic
TURNING = [(a0 | 0x1000, a1, a2) for a0, a1, a2 in [
    obj(10, 10, 0, 2, tile=0, affine=0), obj(80, 30, 0, 3, tile=64, affine=1, double=True),
    obj(160, 70, 1, 3, tile=128, affine=0),
]]
MATRICES = [(0xDD, -0x80, 0x80, 0xDD), (0x80, 0x20, -0x20, 0x80)]

SCENES = {
    "text": scene([(BG0CNT, 0x1040), (BG0HOFS, 5), (BG0VOFS, 3), mosaic(4, 3), (DISPCNT, 0x0100)]),
    "text-cut-by-a-window": scene([
        (BG0CNT, 0x1040), mosaic(6, 5), (WIN0H, 37 << 8 | 150), (WIN0V, 21 << 8 | 130),
        (WININ, 0x0001), (WINOUT, 0x0001), (DISPCNT, 0x2100),
    ]),
    "rotation-scaling": scene([(BG2CNT, 0x1040), *ROTATE, mosaic(5, 5), (DISPCNT, 0x0402)]),
    "bitmap": scene([(BG2CNT, 0x0040), (BG2PA, 0x90), (BG2PD, 0xC0), mosaic(7, 2), (DISPCNT, 0x0403)]),
    "sprites": scene([(BG0CNT, 0x1000 | 1), mosaic(1, 1, 4, 4), (DISPCNT, 0x1140)], SPRITES),
    "sprites-wide-groups": scene([mosaic(1, 1, 9, 2), (DISPCNT, 0x1040)], SPRITES),
    "turning-sprites": scene([mosaic(1, 1, 3, 5), (DISPCNT, 0x1040)], TURNING, MATRICES),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_mosaic_looks_like_mgba(data):
    assert_test_rom_matches("scene", data)
