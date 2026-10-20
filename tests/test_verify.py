"""``gbaport verify``: the native build's pictures against mGBA's, frame by frame."""

import struct
import time

from romtest import build_test_rom
from test_mgba import INPUT

from gbaport.cli import main
from gbaport.verify import Comparison, compare, report, where_they_part


def frames(*pictures: tuple[str, int]) -> list[str]:
    """('a', 3), ('b', 2) -> the hashes of five frames."""
    return [name for name, count in pictures for _ in range(count)]


def test_the_same_pictures_on_the_same_frames_agree():
    hashes = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(hashes, hashes) == Comparison(11, 2, 0, None)


def test_a_picture_a_frame_late_is_within_the_slack():
    ours = frames(("start", 1), ("a", 6), ("b", 4))
    mgba = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, mgba) == Comparison(11, 2, 1, None)


def test_a_picture_two_frames_late_is_where_they_part():
    ours = frames(("start", 1), ("a", 7), ("b", 3))
    mgba = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, mgba).parted == (9, 7)  # frames counted from 1
    assert compare(ours, mgba, slack=2).parted is None


def test_a_picture_only_one_shows_may_last_a_frame():
    ours = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, frames(("start", 1), ("a", 5), ("x", 1), ("b", 4))).parted is None
    assert compare(ours, frames(("start", 1), ("a", 5), ("x", 2), ("b", 3))).parted == (7, 7)


def test_the_first_frame_is_left_out():
    assert compare(frames(("ours", 1), ("a", 5)), frames(("mgba", 1), ("a", 5))).parted is None


def test_a_build_that_stopped_is_compared_over_the_frames_it_played():
    assert compare(frames(("s", 1), ("a", 3)), frames(("s", 1), ("a", 5), ("b", 5))) == \
        Comparison(4, 1, 0, None)


def test_the_report_says_how_far_apart_or_where_they_part():
    assert report(Comparison(900, 472, 1, None)) == \
        "verified 900 frames: 472 pictures in the same order, at most 1 frame apart"
    assert report(Comparison(40, 4, 0, None)).endswith("at most 0 frames apart")
    assert report(Comparison(4200, 1500, 1, (3837, 3836))) == \
        "the pictures part at frame 3837 (mGBA's frame 3836)"


def echo_files(tmp_path):
    rom = tmp_path / "echo.gba"
    rom.write_bytes(build_test_rom("input_echo").data)
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    return rom, tmp_path / "game.input"


def test_verify_plays_a_game_both_ways_and_agrees(tmp_path, capsys):
    rom, input_file = echo_files(tmp_path)
    out = tmp_path / "verify"
    assert main(["verify", str(rom), "--frames", "40", "--input", str(input_file),
                 "--out", str(out)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == \
        "verified 40 frames: 4 pictures in the same order, at most 0 frames apart"
    assert len((out / "ours.hashes").read_text().split()) == 40


def test_verify_shows_where_the_pictures_part(tmp_path, capsys):
    rom, input_file = echo_files(tmp_path)
    out = tmp_path / "verify"
    main(["verify", str(rom), "--frames", "12", "--out", str(out)])
    program = next((out / "build").glob("*-verify*"))
    png = where_they_part(program, rom, (15, 25), input_file, out)  # A, then B and UP
    data = png.read_bytes()
    assert png.name == "frame-15.png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (484, 160)  # ours, a gap, mGBA's


def test_verify_says_when_the_native_build_stopped(tmp_path, capsys):
    rom = tmp_path / "missing.gba"
    rom.write_bytes(build_test_rom("err_missing").data)
    assert main(["verify", str(rom), "--frames", "30", "--out", str(tmp_path / "v")]) == 1
    assert "the native build stopped (exit status 3): error: no recompiled code at" in \
        capsys.readouterr().out


def test_a_long_replay_that_parts_early_is_compared_at_once():
    """An hour of frames, every one a new picture, apart from the second on."""
    ours = [f"ours-{frame}" for frame in range(216000)]
    mgba = [f"mgba-{frame}" for frame in range(216000)]
    start = time.perf_counter()
    assert compare(ours, mgba).parted == (2, 2)
    assert compare(ours, ours).parted is None
    assert time.perf_counter() - start < 2


def test_verify_says_when_the_game_stopped_itself(tmp_path, capsys):
    """hello executes Stop before its first VBlank: no frame to compare, so no agreement."""
    rom = tmp_path / "hello.gba"
    rom.write_bytes(build_test_rom("hello").data)
    assert main(["verify", str(rom), "--frames", "30", "--out", str(tmp_path / "v")]) == 1
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "the native build stopped at frame 0: the game executed Stop and nothing woke it",
        "verified 0 frames: 0 pictures in the same order, at most 0 frames apart",
    ]
