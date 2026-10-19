"""mGBA as the renderer's reference (tests/mgbaref.py, tests/rendertest.py).

The bitmap modes already reach the screen (Plan 4c), so their pictures match mGBA's from
the start; the other renderer tests compare their own test ROMs the same way.
"""

from pathlib import Path

import pytest
import rendertest
from romtest import build_test_rom


@pytest.mark.parametrize("dispcnt", [0x0403, 0x0404, 0x0414, 0x0415, 0x0483])
def test_the_bitmap_modes_match_mgba(dispcnt):
    rendertest.assert_test_rom_matches("bitmap", f"#define DISPCNT 0x{dispcnt:04x}\n", frames=10)


def test_a_different_picture_names_the_pixels_and_shows_them_side_by_side(monkeypatch):
    monkeypatch.setattr(rendertest, "our_picture", lambda rom, frames: [0] * 38400)
    monkeypatch.setattr(rendertest, "mgba_picture", lambda data, frames: [0] * 38399 + [0x7FFF])
    with pytest.raises(AssertionError) as failure:
        rendertest.assert_same_picture(build_test_rom("bitmap", "#define DISPCNT 0x0403\n"))
    message = str(failure.value)
    assert message.startswith("1 pixels differ from mGBA's picture, the first at (239, 159): "
                              "0x0000 instead of 0x7fff (see ")
    picture = message.split("(see ")[1].rstrip(")")
    assert Path(picture).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
