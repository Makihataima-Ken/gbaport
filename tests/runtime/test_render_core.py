"""The renderer's core: a line at a time, the bitmap modes through BG2's rotation/scaling,
and reference points that restart every frame and follow writes (compared with mGBA)."""

import pytest
from rendertest import assert_test_rom_matches


def scene(dispcnt: int, pa=0x100, pb=0, pc=0, pd=0x100, x=0, y=0, wave=0, restart=0) -> str:
    return (
        f"#define DISPCNT 0x{dispcnt:04x}\n#define PA {pa}\n#define PB {pb}\n#define PC {pc}\n"
        f"#define PD {pd}\n#define X {x}\n#define Y {y}\n#define WAVE {wave}\n"
        f"#define RESTART {restart}\n"
    )


@pytest.mark.parametrize("data", [
    scene(0x0403, pa=0x80, pd=0x80),                                   # mode 3, twice the size
    scene(0x0403, pa=0xB5, pb=-0xB5, pc=0xB5, pd=0xB5, x=60 << 8),    # 45 degrees
    scene(0x0404, pa=0x200, pb=0x40, pc=-0x40, pd=0x180, x=-20 << 8, y=30 << 8),
    scene(0x0405, pa=-0x100, pd=-0x100, x=159 << 8, y=127 << 8),        # mode 5, turned round
    scene(0x0083),                                                      # forced blank
], ids=["scaled", "rotated", "sheared", "mode5-flipped", "forced-blank"])
def test_the_bitmap_modes_rotate_and_scale_like_mgba(data):
    assert_test_rom_matches("affine_bitmap", data)


@pytest.mark.parametrize("mode", [6, 7])
def test_the_modes_that_do_not_exist_show_what_mgba_shows(mode):
    assert_test_rom_matches("affine_bitmap", scene(0x0400 | mode))


def test_a_reference_point_written_between_lines_moves_the_lines_below():
    assert_test_rom_matches("affine_bitmap", scene(0x0403, pd=0x100, x=8 << 8, wave=1))


def test_writing_bg2y_mid_frame_restarts_the_walk_there():
    assert_test_rom_matches("affine_bitmap", scene(0x0403, pa=0x100, pd=0x80, y=10 << 8, restart=1))
