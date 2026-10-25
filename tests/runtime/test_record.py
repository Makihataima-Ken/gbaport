"""Recording play (host_common.c's --record): the keys the game was given, frame by frame,
as an input file, and the save it started from next to it, so the same play can be
replayed (gbaport learn)."""

from romtest import build_test_rom, run_rom, run_test

from gbaport.inputs import format_input, load_input

PRESSES = ("--press", "30:A", "--press", "40:none", "--press", "60:RIGHT+B", "--press", "75:none")


def presses(path):
    return [line for line in format_input(load_input(path)).splitlines() if line]


def test_a_recording_replays_as_the_run_it_records(tmp_path):
    record = tmp_path / "play.input"
    first = run_test("keys_log", frames=100,
                     args=(*PRESSES, "--record", str(record), "--hashes", str(tmp_path / "1")))
    assert record.read_text(encoding="utf-8").startswith("# recorded by gbaport")
    assert presses(record) == ["30 A", "40 none", "60 B+RIGHT", "75 none"]
    replay = run_test("keys_log", frames=100,
                      args=("--input", str(record), "--hashes", str(tmp_path / "2")))
    assert replay.lines == first.lines
    assert first.lines[1:] == ("KEYS A", "KEYS none", "KEYS B+RIGHT", "KEYS none")
    assert (tmp_path / "1").read_bytes() == (tmp_path / "2").read_bytes()


def test_a_key_that_wakes_the_game_from_stop_is_recorded_for_the_wake(tmp_path):
    record = tmp_path / "play.input"
    run_test("stop_wake", args=("--press", "30:START", "--record", str(record))).assert_passed()
    assert presses(record) == ["1 START"]  # after the frame it stopped in, which no frame ends
    replay = run_test("stop_wake", args=("--input", str(record)))
    replay.assert_passed()
    assert replay.lines[:2] == ("stopping", "woke")


def test_the_save_the_game_started_from_goes_next_to_the_recording(tmp_path):
    rom = build_test_rom("save_sram")
    save, record = tmp_path / "game.sav", tmp_path / "play.input"
    run_rom(rom, save=save, args=("--record", str(record)))
    assert not (tmp_path / "play.input.sav").exists()  # it started blank
    started = save.read_bytes()
    run_rom(rom, save=save, args=("--record", str(record)))
    assert (tmp_path / "play.input.sav").read_bytes() == started
    save.unlink()
    run_rom(rom, save=save, args=("--record", str(record)))
    assert not (tmp_path / "play.input.sav").exists()  # not an older one


def test_the_window_records_next_to_its_save_and_headless_only_when_asked(tmp_path):
    rom = build_test_rom("hello")
    run_rom(rom, host="sdl", frames=60, save=tmp_path / "game.sav")
    assert (tmp_path / "game.session.input").read_text(encoding="utf-8").startswith("# recorded")
    run_rom(rom, frames=60, save=tmp_path / "other.sav")
    assert not (tmp_path / "other.session.input").exists()


def test_the_window_plays_on_when_it_cannot_record_next_to_its_save(tmp_path):
    run = run_rom(build_test_rom("hello"), host="sdl", frames=60,
                  save=tmp_path / "no such folder" / "game.sav")
    assert run.status == 0, run.stderr  # as before the window recorded
    assert run.lines[-1] == "DONE 1 passed, 0 failed"
    assert "warning: cannot record the play" in run.stderr
