"""gbaport learn: a recorded run whose code ran partly in the interpreter is played again
natively, and every place the replay runs interpreted is learned (games/<game_code>/
learned.toml), until nothing does."""

import dataclasses
import os
import re

from romtest import build_test_rom, run_program, run_rom

import gbaport.learn as learning
from gbaport.analysis.config import learned_path, load_learned, write_learned
from gbaport.cli import main
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom


def game(tmp_path, monkeypatch, name: str = "calls", ram_code: bool = True):
    """A test ROM as game.gba with its game.toml in games/ATST; tmp_path is the working folder.
    Without ``ram_code`` the game.toml does not say where the code it copies to IWRAM is from."""
    monkeypatch.chdir(tmp_path)
    rom = build_test_rom(name)
    if not ram_code:
        rom = dataclasses.replace(rom, config=rom.config.split("[[ram_code]]")[0])
    (tmp_path / "game.gba").write_bytes(rom.data)
    (tmp_path / "games" / "ATST").mkdir(parents=True)
    (tmp_path / "games" / "ATST" / "game.toml").write_text(rom.config, encoding="utf-8")
    return rom


RECORDING = "game.session.input"  # where the window records game.gba's play
INTERPRETED = re.compile(r"^interpreted \d+ instructions at (\d+) places", re.MULTILINE)


def built(tmp_path) -> str:
    """gbaport build --host headless's program for game.gba (learned.toml goes in too)."""
    assert main(["build", "game.gba", "--host", "headless"]) == 0
    return str(tmp_path / "games" / "ATST" / "build" / ("ATST-headless" + (".exe" if os.name == "nt" else "")))


def learned_lines(out: str) -> list[tuple[int, str, int]]:
    found = re.findall(r"learned (0x[0-9a-f]{8}) \((Thumb|ARM)\), which first ran interpreted at "
                       r"frame (\d+)", out)
    return [(int(addr, 16), mode, int(frame)) for addr, mode, frame in found]


def test_play_learn_build_and_play_recompiled(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch)
    thumb, arm, pressed = (rom.symbols[name] for name in ("hidden_thumb", "hidden_arm", "hidden_pressed"))
    played = run_rom(rom, frames=30, args=("--press", "5:A", "--record", RECORDING))
    played.assert_passed()  # the code the build missed ran in the interpreter
    assert INTERPRETED.search(played.stderr).group(1) == "3"
    assert main(["learn", "game.gba"]) == 0
    out = capsys.readouterr().out
    first, second, (addr, mode, frame) = learned_lines(out)  # all of it in one replay
    assert [first, second] == [(thumb, "Thumb", 0), (arm, "ARM", 0)]
    assert (addr, mode) == (pressed, "Thumb") and frame >= 5
    assert f"3 places learned into {learned_path('ATST')}" in out
    sha1 = inspect_rom(RomImage(rom.data)).sha1
    assert load_learned(learned_path("ATST"), sha1) == ((arm,), (thumb, pressed))
    run = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30"])
    assert run.stdout.splitlines()[-1] == "DONE 3 passed, 0 failed"
    assert not INTERPRETED.search(run.stderr)  # all of it recompiled now


def test_learn_says_when_the_replay_runs_nothing_interpreted(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "hello")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    assert main(["learn", "game.gba"]) == 0
    assert "the replay played to its end: nothing to learn" in capsys.readouterr().out
    assert not learned_path("ATST").exists()


def test_learn_needs_a_recording(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    assert main(["learn", "game.gba"]) == 1
    assert "no recording game.session.input: play the game in the window first" in \
        capsys.readouterr().err


def test_learned_addresses_belong_to_the_rom_they_were_learned_from(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    write_learned(learned_path("ATST"), "0" * 40, (), (0x08000100,))
    assert main(["recompile", "game.gba"]) == 1
    assert f"learned.toml is for ROM sha1 {'0' * 40}" in capsys.readouterr().err


def test_device_is_instead_of_input_and_save(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    assert main(["learn", "game.gba", "--device", "--input", "x.input"]) == 1
    assert "--device takes the recording from the phone" in capsys.readouterr().err


def test_code_the_analysis_cannot_recompile_stays_interpreted(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "interrupts", ram_code=False)  # IWRAM code it copies
    run_rom(rom, frames=600, args=("--record", RECORDING)).assert_passed()
    assert main(["learn", "game.gba"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"0x03[0-9a-f]{6} \(ARM\) still runs interpreted: the game runs it from "
                     r"RAM", out)
    learned = learned_path("ATST")
    assert "0x03" not in (learned.read_text(encoding="utf-8") if learned.exists() else "")


def test_learn_stops_at_a_jump_to_where_there_can_be_no_code(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "err_missing")  # jumps past the end of the ROM
    run_rom(rom, frames=30, args=("--record", RECORDING))
    assert main(["learn", "game.gba"]) == 1
    err = capsys.readouterr().err
    assert "the replay stopped: no recompiled code at 0x08100000" in err
    assert "it is past the end of the ROM" in err
    assert not learned_path("ATST").exists()


def test_learn_says_when_the_replay_cannot_run(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "save_sram")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    (tmp_path / "wrong.sav").write_bytes(bytes(100))  # no save chip holds 100 bytes
    assert main(["learn", "game.gba", "--save", "wrong.sav"]) == 1
    err = capsys.readouterr().err
    assert "the replay could not run (exit status 2)" in err and "has 100 bytes" in err


def test_learn_plays_to_where_the_recorded_play_ended(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "late_call")  # calls missed code 2000 frames in
    run_rom(rom, frames=2100, args=("--record", RECORDING))
    ended = (tmp_path / RECORDING).read_text(encoding="utf-8").splitlines()[-1]
    assert re.fullmatch(r"# ended at frame \d+", ended)
    assert main(["learn", "game.gba"]) == 0
    assert [addr for addr, _, _ in learned_lines(capsys.readouterr().out)] == [
        rom.symbols["hidden_late"]]


def test_learn_says_when_the_replay_does_not_stop_where_the_play_did(tmp_path, monkeypatch,
                                                                     capsys):
    rom = game(tmp_path, monkeypatch, "hello")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    with open(tmp_path / RECORDING, "a", encoding="utf-8") as recording:  # another build's play
        recording.write("# ended at frame 20: undefined instruction at 0x08000400\n")
    assert main(["learn", "game.gba"]) == 1
    assert "the replay did not stop where the recorded play did (frame 20" in \
        capsys.readouterr().err


def test_a_replay_that_takes_too_long_says_so(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "hello")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    monkeypatch.setattr(learning, "REPLAY_TIMEOUT", 0.001)
    assert main(["learn", "game.gba"]) == 1
    assert "the replay took more than 0.001 s" in capsys.readouterr().err
