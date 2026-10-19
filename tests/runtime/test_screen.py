"""The picture the hosts show, for the bitmap modes (the other layers: test_render_*.py)."""

import pytest
from romtest import read_bmp, run_test

BACKDROP = 0x7C00  # blue, palette entry 0 (bitmap.c)


def rgb(color: int) -> int:
    r, g, b = color & 31, (color >> 5) & 31, (color >> 10) & 31
    return ((r << 3 | r >> 2) << 16) | ((g << 3 | g >> 2) << 8) | (b << 3 | b >> 2)


def expected(dispcnt: int) -> list[int]:
    """What bitmap.c draws, by the same formulas."""
    mode = dispcnt & 7
    pixels = []
    for y in range(160):
        for x in range(240):
            color = BACKDROP
            if dispcnt & 0x400 and mode == 3:
                color = (x & 31) | (y & 31) << 5
            elif dispcnt & 0x400 and mode == 4 and (x + y) & 255:
                color = ((x + y) & 255) * 0x0421 & 0x7FFF
            elif dispcnt & 0x400 and mode == 5 and x < 160 and y < 128:
                color = (x ^ y) & 0x7FFF
            pixels.append(0xFFFFFF if dispcnt & 0x80 else rgb(color))
    return pixels


@pytest.mark.parametrize("dispcnt", [
    0x0403,  # mode 3
    0x0404,  # mode 4, page 0
    0x0414,  # mode 4, page 1 (bitmap.c draws only the page it shows)
    0x0415,  # mode 5, page 1: 160x128, the rest is backdrop
    0x0003,  # mode 3 with BG2 off: backdrop
    0x0483,  # forced blank: white
])
def test_the_screen_shows_the_bitmap_modes(tmp_path, dispcnt):
    shot = tmp_path / "screen.bmp"
    data = f"#define DISPCNT 0x{dispcnt:04x}\n"
    run = run_test("bitmap", frames=10, data=data, args=("--screenshot", str(shot)))
    assert run.status == 4, run.stderr
    assert read_bmp(shot) == expected(dispcnt)
