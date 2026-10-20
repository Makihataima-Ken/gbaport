"""File names outside ASCII: Windows hands programs their arguments in UTF-16."""

import os

import pytest
from romtest import build_test_rom, native_program, run_program


@pytest.mark.parametrize("host", ["headless", "sdl"])
def test_rom_and_save_paths_may_have_any_characters(tmp_path, host):
    rom = build_test_rom("save_sram")
    folder = tmp_path / "jeu-é-ゲーム"  # not in the ANSI code page
    folder.mkdir()
    path = folder / "game.gba"
    path.write_bytes(rom.data)
    env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy", "SDL_AUDIO_DRIVER": "dummy"}  # no window, no sound
    result = run_program([str(native_program(rom, host)), str(path), "--frames", "600"], env)
    assert result.returncode == 0, result.stderr
    assert (folder / "game.sav").stat().st_size == 0x8000  # next to the ROM, by default
