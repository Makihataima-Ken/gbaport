"""mGBA as gbaport's reference (gbaport/native/mgba.py): it plays a ROM with the keys an
input file names and writes a hash of each frame's picture."""

import pytest
from mgbaref import mgba_picture
from romtest import build_test_rom

from gbaport.native.mgba import MgbaError, run_mgba

INPUT = "0 none\n10 A\n20 B+UP\n30 none\n"


def picture_hash(colours: list[int]) -> str:
    """A picture's FNV-1a hash, as gbaport-mgba and the hosts write it."""
    h = 0xCBF29CE484222325
    for colour in colours:
        for byte in (colour & 0xFF, colour >> 8 & 0x7F):
            h = (h ^ byte) * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def echo(tmp_path):
    rom, path = build_test_rom("input_echo"), tmp_path / "echo.gba"
    path.write_bytes(rom.data)
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    return rom, path


def test_mgba_holds_the_keys_the_input_file_names(tmp_path):
    rom, _ = echo(tmp_path)
    # keys held from the 10th VBlank on are read at it and drawn in the picture after it
    assert set(mgba_picture(rom.data, 15, INPUT)) == {0x0001}  # A
    assert set(mgba_picture(rom.data, 25, INPUT)) == {0x0042}  # B, UP
    assert set(mgba_picture(rom.data, 35, INPUT)) == {0x0000}


def test_mgba_writes_a_hash_of_each_frames_picture(tmp_path):
    _, path = echo(tmp_path)
    run_mgba(path, 40, input=tmp_path / "game.input", hashes=tmp_path / "mgba.hashes")
    hashes = (tmp_path / "mgba.hashes").read_text(encoding="utf-8").split("\n")
    black, a, b_up = (picture_hash([colour] * 38400) for colour in (0, 0x0001, 0x0042))
    # a line a frame; the first is the start-up frame, which begins in line 126
    assert hashes[1:] == [black] * 9 + [a] * 10 + [b_up] * 10 + [black] * 10 + [""]


def test_a_bad_input_file_stops_mgba_with_its_line(tmp_path):
    _, path = echo(tmp_path)
    (tmp_path / "bad.input").write_text("10 A\n5 B\n", encoding="utf-8")
    with pytest.raises(MgbaError, match=r"exit status 2\): error: .*bad\.input, line 2"):
        run_mgba(path, 10, input=tmp_path / "bad.input")


def test_mgba_takes_any_file_names_and_an_input_file_from_a_windows_editor(tmp_path):
    """Paths outside the ANSI code page (Windows hands them to programs in UTF-16), and an
    input file with a UTF-8 byte order mark and CRLF line ends."""
    folder = tmp_path / "jeu-é-ゲーム"
    folder.mkdir()
    rom = build_test_rom("input_echo")
    (folder / "echo.gba").write_bytes(rom.data)
    (folder / "game.input").write_bytes(b"\xef\xbb\xbf0 none\r\n10 B\r\n")
    run_mgba(folder / "echo.gba", 15, input=folder / "game.input", picture=folder / "p.raw",
             hashes=folder / "h.hashes")
    assert (folder / "h.hashes").read_text(encoding="utf-8").split()[-1] == \
        picture_hash([0x0002] * 38400)
    assert (folder / "p.raw").stat().st_size == 2 * 38400
