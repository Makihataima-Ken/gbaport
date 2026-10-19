"""Rotation/scaling backgrounds (BG2 in modes 1 and 2, BG3 in mode 2), compared with
mGBA: sizes, wrap-around or transparency outside, matrices, and stacking."""

import pytest
from rendertest import assert_test_rom_matches


def bg(char: int = 0, screen: int = 16, size: int = 0, wrap: bool = False,
       priority: int = 0) -> int:
    return priority | char << 2 | screen << 8 | (0x2000 if wrap else 0) | size << 14


IDENTITY = (0x100, 0, 0, 0x100)


def scene(dispcnt: int, bg2: int = 0, m2=IDENTITY, p2=(0, 0), bg3: int = 0, m3=IDENTITY,
          p3=(0, 0), bg0: int = 0) -> str:
    """testdata.h for affine_bg.c."""
    values = {"DISPCNT": dispcnt, "BGCNT0": bg0, "BGCNT2": bg2, "BGCNT3": bg3}
    for name, value in zip(("PA2", "PB2", "PC2", "PD2"), m2):
        values[name] = value
    for name, value in zip(("PA3", "PB3", "PC3", "PD3"), m3):
        values[name] = value
    values |= {"X2": p2[0], "Y2": p2[1], "X3": p3[0], "Y3": p3[1]}
    return "".join(f"#define {name} {value}\n" for name, value in values.items())


ROTATE = (0xDD, -0x80, 0x80, 0xDD)  # about 30 degrees
SCENES = {
    "128-clear-outside": scene(0x0402, bg2=bg(screen=16), m2=ROTATE, p2=(-40 << 8, -20 << 8)),
    "256-wrap": scene(0x0402, bg2=bg(screen=18, size=1, wrap=True), m2=(0x180, 0x30, -0x30, 0x80),
                      p2=(100 << 8, -30 << 8)),
    "512": scene(0x0402, bg2=bg(char=1, screen=20, size=2), m2=(0x300, 0, 0, 0x300),
                 p2=(5 << 8, 7 << 8)),
    "1024-wrap": scene(0x0402, bg2=bg(screen=24, size=3, wrap=True), m2=(-0xC0, 0x90, -0x90, -0xC0),
                       p2=(700 << 8, 900 << 8)),
    "bg2-and-bg3": scene(0x0C02, bg2=bg(screen=16, size=1, priority=1), m2=ROTATE,
                         bg3=bg(char=1, screen=26, size=1, wrap=True), m3=(0x100, 0, 0x40, 0x100),
                         p3=(-8 << 8, 0)),
    "mode1-text-and-affine": scene(0x0501, bg0=0x1E00 | 1, bg2=bg(char=1, screen=16, size=1),
                                   m2=(0x80, 0, 0, 0x80)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_rotation_scaling_backgrounds_look_like_mgba(data):
    assert_test_rom_matches("affine_bg", data)
