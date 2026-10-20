"""The hosts play an input file (--input) and write each frame's picture hash (--hashes),
as gbaport-mgba does: the same keys give the same pictures, frame for frame."""

import pytest
from romtest import build_test_rom, run_rom
from test_mgba import INPUT, picture_hash

from gbaport.native.mgba import run_mgba


@pytest.mark.parametrize("host", ["headless", "sdl"])
def test_the_hosts_show_what_mgba_shows_for_an_input_file(tmp_path, host):
    rom = build_test_rom("input_echo")
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    (tmp_path / "echo.gba").write_bytes(rom.data)
    run = run_rom(rom, frames=40, host=host, args=(
        "--input", str(tmp_path / "game.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    run_mgba(tmp_path / "echo.gba", 40, input=tmp_path / "game.input",
             hashes=tmp_path / "mgba.hashes")
    ours = (tmp_path / "ours.hashes").read_text(encoding="utf-8").split("\n")
    mgba = (tmp_path / "mgba.hashes").read_text(encoding="utf-8").split("\n")
    assert len(ours) == len(mgba) == 41
    assert ours[1:] == mgba[1:]  # (the start-up frame begins in line 126)


def test_an_input_file_holds_more_presses_than_a_command_line_could(tmp_path):
    presses = "".join(f"{frame} {'A' if frame % 2 else 'B'}\n" for frame in range(10, 210))
    (tmp_path / "many.input").write_text(presses + "210 UP+L\n", encoding="utf-8")
    run = run_rom(build_test_rom("input_echo"), frames=215, args=(
        "--input", str(tmp_path / "many.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    hashes = (tmp_path / "ours.hashes").read_text(encoding="utf-8").split()
    assert len(hashes) == 215
    # line k is the picture drawn after VBlank k, with the keys held from that VBlank on
    assert hashes[101] == picture_hash([0x0001] * 38400)  # A: frame 101 is odd
    assert hashes[-1] == picture_hash([0x0240] * 38400)  # UP, L


def test_a_bad_input_file_stops_the_host_with_its_line(tmp_path):
    (tmp_path / "bad.input").write_text("# fine\n10 A\n10 JUMP\n", encoding="utf-8")
    run = run_rom(build_test_rom("input_echo"), frames=20, args=(
        "--input", str(tmp_path / "bad.input")))
    assert run.status == 2
    assert "bad.input, line 3: expected 'FRAME KEYS', frames in order" in run.stderr


def test_an_input_file_from_a_windows_editor_plays_the_same(tmp_path):
    """A UTF-8 byte order mark and CRLF line ends, as Notepad may write them."""
    (tmp_path / "game.input").write_bytes(b"\xef\xbb\xbf# keys\r\n0 none\r\n10 R\r\n")
    run = run_rom(build_test_rom("input_echo"), frames=15, args=(
        "--input", str(tmp_path / "game.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    assert (tmp_path / "ours.hashes").read_text(encoding="utf-8").split()[-1] == \
        picture_hash([0x0100] * 38400)  # R
