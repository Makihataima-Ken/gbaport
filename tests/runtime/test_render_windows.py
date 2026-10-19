"""Windows, compared with mGBA: WIN0 and WIN1 (rectangles, wrapping, coordinates past the
screen), the OBJ window that sprites draw, and which window wins where they overlap."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG1CNT = 0x000, 0x008, 0x00A
WIN0H, WIN1H, WIN0V, WIN1V, WININ, WINOUT = 0x040, 0x042, 0x044, 0x046, 0x048, 0x04A
LAYERS = [(BG0CNT, 0x1000 | 1), (BG1CNT, 0x1204 | 2)]  # BG0 over BG1
SPRITES = [obj(20, 20, 0, 3, tile=0, priority=0), obj(150, 70, 1, 3, tile=64, priority=0),
           obj(90, 100, 0, 2, tile=200, priority=0)]
SHAPES = [obj(60, 40, 0, 3, tile=300, mode=2), obj(120, 10, 2, 3, tile=400, mode=2)]


def windows(dispcnt: int, *writes: tuple[int, int], objs=SPRITES) -> str:
    return scene([*LAYERS, *writes, (DISPCNT, dispcnt)], objs)


BASE = 0x1340  # mode 0, BG0, BG1, sprites, 1D tiles
SCENES = {
    "win0": windows(BASE | 0x2000, (WIN0H, 40 << 8 | 200), (WIN0V, 30 << 8 | 120),
                    (WININ, 0x0011), (WINOUT, 0x0002)),
    "win0-over-win1": windows(BASE | 0x6000, (WIN0H, 20 << 8 | 140), (WIN0V, 20 << 8 | 100),
                              (WIN1H, 100 << 8 | 220), (WIN1V, 60 << 8 | 150),
                              (WININ, 0x1201), (WINOUT, 0x0010)),
    "wrapped": windows(BASE | 0x2000, (WIN0H, 200 << 8 | 40), (WIN0V, 120 << 8 | 30),
                       (WININ, 0x0013), (WINOUT, 0x0000)),
    "past-the-edges": windows(BASE | 0x6000, (WIN0H, 100 << 8 | 250), (WIN0V, 10 << 8 | 200),
                              (WIN1H, 245 << 8 | 20), (WIN1V, 170 << 8 | 50),
                              (WININ, 0x0201), (WINOUT, 0x0010)),
    "obj-window": windows(BASE | 0x8000, (WINOUT, 0x1201), objs=SPRITES + SHAPES),
    "obj-window-under-win0": windows(BASE | 0xA000, (WIN0H, 0 << 8 | 100), (WIN0V, 0 << 8 | 160),
                                     (WININ, 0x0010), (WINOUT, 0x0302), objs=SHAPES + SPRITES),
    "nothing-inside": windows(BASE | 0x2000, (WIN0H, 50 << 8 | 190), (WIN0V, 40 << 8 | 120),
                              (WININ, 0x0000), (WINOUT, 0x001F)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_windows_look_like_mgba(data):
    assert_test_rom_matches("scene", data)
