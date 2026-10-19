"""Colour special effects, compared with mGBA: alpha blending, brightening, darkening,
semi-transparent sprites, the backdrop as a target, and windows that switch effects off."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG1CNT, WIN0H, WIN0V, WININ, WINOUT = 0x000, 0x008, 0x00A, 0x040, 0x044, 0x048, 0x04A
BLDCNT, BLDALPHA, BLDY = 0x050, 0x052, 0x054
BG0, BG1, BG2, BG3, OBJ, BD = 1, 2, 4, 8, 16, 32
ALPHA, BRIGHTEN, DARKEN = 1 << 6, 2 << 6, 3 << 6
LAYERS = [(BG0CNT, 0x1000 | 1), (BG1CNT, 0x1204 | 2)]  # BG0 over BG1
SPRITES = [obj(20, 20, 0, 3, tile=0, priority=0), obj(150, 70, 1, 3, tile=64, priority=1),
           obj(90, 100, 0, 2, tile=200, priority=0, mode=1), obj(60, 40, 0, 3, tile=300, mode=1)]


def effects(*writes: tuple[int, int], dispcnt: int = 0x1340, objs=SPRITES) -> str:
    return scene([*LAYERS, *writes, (DISPCNT, dispcnt)], objs)


SCENES = {
    "alpha": effects((BLDCNT, BG0 | ALPHA | BG1 << 8), (BLDALPHA, 6 << 8 | 10)),
    "alpha-past-16-saturates": effects((BLDCNT, BG0 | OBJ | ALPHA | (BG1 | BD) << 8),
                                       (BLDALPHA, 31 << 8 | 31)),
    "alpha-onto-a-layer-that-is-no-target": effects((BLDCNT, BG0 | ALPHA | BG3 << 8), (BLDALPHA, 8 << 8 | 8)),
    "brighten": effects((BLDCNT, BG0 | BD | BRIGHTEN), (BLDY, 9)),
    "darken-past-16": effects((BLDCNT, BG0 | BG1 | OBJ | DARKEN), (BLDY, 25)),
    "semi-transparent-sprites": effects((BLDCNT, BG1 << 8 | BD << 8), (BLDALPHA, 4 << 8 | 12)),
    "semi-transparent-sprites-with-brighten": effects((BLDCNT, OBJ | BRIGHTEN | (BG0 | BG1) << 8),
                                                      (BLDALPHA, 9 << 8 | 7), (BLDY, 12)),
    "window-switches-effects-off": effects(
        (BLDCNT, BG0 | OBJ | ALPHA | (BG1 | BD) << 8), (BLDALPHA, 10 << 8 | 6),
        (WIN0H, 40 << 8 | 180), (WIN0V, 30 << 8 | 130), (WININ, 0x001F), (WINOUT, 0x003F),
        dispcnt=0x3340),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_colour_effects_look_like_mgba(data):
    assert_test_rom_matches("scene", data)
