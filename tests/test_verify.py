"""``gbaport verify``: the native build's pictures against mGBA's, frame by frame."""

import struct
import time

import pytest
from romtest import build_test_rom, native_program
from test_mgba import INPUT

from gbaport import verify as verify_module
from gbaport.cli import main
from gbaport.verify import Comparison, compare, play, report, where_they_part


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


def test_a_build_that_shows_the_same_picture_on_is_where_they_part():
    """Ours stays on a picture (say, it missed a key) while mGBA goes on, or the other way
    round: they part where one shows the next picture and the other does not."""
    still = frames(("s", 1), ("a", 99))
    moving = frames(("s", 1), ("a", 9), ("b", 90))
    assert compare(still, moving).parted == (11, 11)
    assert compare(moving, still).parted == (11, 11)


def test_a_picture_only_one_shows_at_the_end_may_last_the_slack():
    ours = frames(("s", 1), ("a", 9), ("x", 1))
    mgba = frames(("s", 1), ("a", 10))
    assert compare(ours, mgba).parted is None
    assert compare(ours, mgba, slack=0).parted == (11, 11)
    assert compare(mgba, ours, slack=0).parted == (11, 11)


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


def test_verify_needs_a_frame_and_no_negative_slack(capsys):
    for option, value in (("--frames", "0"), ("--slack", "-1")):
        with pytest.raises(SystemExit) as exc:
            main(["verify", "game.gba", option, value])
        assert exc.value.code == 2
        assert f"argument {option}" in capsys.readouterr().err


def test_a_native_run_that_takes_too_long_is_an_error(tmp_path, monkeypatch, capsys):
    rom, _ = echo_files(tmp_path)
    monkeypatch.setattr(verify_module, "NATIVE_TIMEOUT", 0.001)
    assert main(["verify", str(rom), "--frames", "40", "--out", str(tmp_path / "v")]) == 1
    assert "error: the native build did not finish 40 frames in 0.001 s" in \
        capsys.readouterr().err


def test_verify_gives_both_the_input_file_as_python_reads_it(tmp_path, capsys):
    """However a line is spaced, both programs get the presses the input file names."""
    rom, input_file = echo_files(tmp_path)
    input_file.write_text("0 none\n10" + " " * 300 + "A\n20 B+UP\n30 none\n", encoding="utf-8")
    assert main(["verify", str(rom), "--frames", "40", "--input", str(input_file),
                 "--out", str(tmp_path / "v")]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == \
        "verified 40 frames: 4 pictures in the same order, at most 0 frames apart"


def test_a_native_run_that_fails_leaves_no_hashes_from_an_earlier_run(tmp_path):
    rom, _ = echo_files(tmp_path)
    (tmp_path / "ours.hashes").write_text("0123456789abcdef\n" * 40, encoding="utf-8")
    (tmp_path / "bad.input").write_text("10 A\n5 B\n", encoding="utf-8")
    run = play(native_program(build_test_rom("input_echo")), rom, 40, tmp_path / "bad.input",
               tmp_path)
    assert run.returncode == 2
    assert not (tmp_path / "ours.hashes").exists()


def test_the_native_builds_messages_reach_verify_whatever_the_path(tmp_path):
    """A message naming a path outside the ANSI code page (the host writes UTF-8)."""
    folder = tmp_path / "あ-ゲーム"
    folder.mkdir()
    rom, _ = echo_files(folder)
    run = play(native_program(build_test_rom("input_echo")), rom, 10, folder / "missing.input",
               folder)
    assert run.returncode == 2
    assert "あ-ゲーム" in run.stderr and "missing.input" in run.stderr

