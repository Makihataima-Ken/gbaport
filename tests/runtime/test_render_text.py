"""Text backgrounds (modes 0 and 1), compared with mGBA: colour depths, map sizes,
scrolling, flips, palette banks, and how four layers stack by priority."""

import pytest
from rendertest import assert_test_rom_matches


def bg(char: int = 0, screen: int = 16, size: int = 0, colors256: bool = False,
       priority: int = 0) -> int:
    """A BGnCNT value: char block (16 KiB), screen block (2 KiB), size 0-3."""
    return priority | char << 2 | (0x80 if colors256 else 0) | screen << 8 | size << 14


def scene(dispcnt: int, *bgs: tuple[int, int, int]) -> str:
    """testdata.h for text_bg.c: DISPCNT, then (BGnCNT, HOFS, VOFS) for BG0 upwards."""
    rows = list(bgs) + [(0, 0, 0)] * (4 - len(bgs))
    lines = [f"#define DISPCNT 0x{dispcnt:04x}"]
    for n, (control, hofs, vofs) in enumerate(rows):
        lines += [f"#define BGCNT{n} 0x{control:04x}", f"#define HOFS{n} {hofs}",
                  f"#define VOFS{n} {vofs}"]
    return "\n".join(lines) + "\n"


SCENES = {
    "4bpp-256x256": scene(0x0100, (bg(screen=16), 13, 7)),
    "8bpp-512x256": scene(0x0100, (bg(char=1, screen=18, size=1, colors256=True), 300, 20)),
    "256x512": scene(0x0200, (0, 0, 0), (bg(screen=20, size=2), 5, 300)),
    "512x512": scene(0x0400, (0, 0, 0), (0, 0, 0), (bg(char=1, screen=24, size=3), 400, 450)),
    "four-layers": scene(
        0x0F00,
        (bg(screen=16, priority=3), 3, 1),
        (bg(char=1, screen=18, priority=1), 100, 50),
        (bg(screen=20, colors256=True, priority=1), 7, 9),
        (bg(char=1, screen=22, priority=0), 250, 130),
    ),
    "mode1": scene(0x0301, (bg(screen=16, priority=1), 0, 0), (bg(char=1, screen=18), 33, 44)),
    "mode2-has-no-text-backgrounds": scene(0x0302, (bg(screen=16), 0, 0), (bg(screen=18), 0, 0)),
    "tiles-past-bg-vram": scene(0x0100, (bg(char=3, screen=16), 0, 0)),
    "scroll-past-511": scene(0x0100, (bg(screen=16, size=3), 0xFFFF, 0xFE01)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_text_backgrounds_look_like_mgba(data):
    assert_test_rom_matches("text_bg", data)
