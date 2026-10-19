"""jsmolka's PPU test ROMs (tests/jsmolka.py), recompiled: their pictures match mGBA's."""

import pytest
from jsmolka import jsmolka_rom
from rendertest import assert_same_picture


@pytest.mark.parametrize("name", ["hello", "shades", "stripes"])
def test_jsmolka_ppu_rom_looks_like_mgba(name):
    assert_same_picture(jsmolka_rom(name), frames=60)
