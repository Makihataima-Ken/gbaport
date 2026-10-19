"""Raster effects, compared with mGBA: HBlank DMA writing a scroll register or a colour
line after line, and an interrupt switching modes halfway down the screen."""

import pytest
from rendertest import assert_test_rom_matches

BG0HOFS, BACKDROP = 0x04000010, 0x05000000


def raster(dispcnt: int, split: int, target: int) -> str:
    """testdata.h for raster.c."""
    return (f"#define DISPCNT 0x{dispcnt:04x}\n#define SPLIT {split}\n"
            f"#define TARGET 0x{target:08x}\n")


SCENES = {
    "hblank-dma-wave": raster(0x0500, 0, BG0HOFS),
    "hblank-dma-backdrop-colours": raster(0x0100, 0, BACKDROP),
    "mode-switch-at-line-80": raster(0x0500, 1, BG0HOFS),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_raster_effects_look_like_mgba(data):
    assert_test_rom_matches("raster", data)
