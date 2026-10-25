"""gbaport learn: a recorded run that stopped at code the recompiler did not find is played
again natively, and each address it stops at is learned (games/<game_code>/learned.toml),
until the replay gets through."""

import os
import re

from romtest import build_test_rom, run_program, run_rom

from gbaport.analysis.config import learned_path, load_learned, write_learned
from gbaport.cli import main
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom


def game(tmp_path, monkeypatch, name: str = "calls"):
    """A test ROM as game.gba with its game.toml in games/ATST; tmp_path is the working folder."""
    monkeypatch.chdir(tmp_path)
    rom = build_test_rom(name)
    (tmp_path / "game.gba").write_bytes(rom.data)
    (tmp_path / "games" / "ATST").mkdir(parents=True)
    (tmp_path / "games" / "ATST" / "game.toml").write_text(rom.config, encoding="utf-8")
    return rom


RECORDING = "game.session.input"  # where the window records game.gba's play


def built(tmp_path) -> str:
    """gbaport build --host headless's program for game.gba (learned.toml goes in too)."""
    assert main(["build", "game.gba", "--host", "headless"]) == 0
    return str(tmp_path / "games" / "ATST" / "build" / ("ATST-headless" + (".exe" if os.name == "nt" else "")))


def learned_lines(out: str) -> list[tuple[int, str, int]]:
    found = re.findall(r"learned (0x[0-9a-f]{8}) \((Thumb|ARM)\), missing at frame (\d+)", out)
    return [(int(addr, 16), mode, int(frame)) for addr, mode, frame in found]


def test_play_learn_build_and_play_on(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch)
    thumb, arm, pressed = (rom.symbols[name] for name in ("hidden_thumb", "hidden_arm", "hidden_pressed"))
    stopped = run_rom(rom, frames=30, args=("--press", "5:A", "--record", RECORDING)).stderr
    assert re.search(rf"no recompiled code at 0x{thumb:08x} \(Thumb state, lr = 0x[0-9a-f]{{8}}, "
                     r"frame 0\): gbaport learn", stopped)  # at once: the A press never came
    assert main(["learn", "game.gba"]) == 0
    out = capsys.readouterr().out
    assert learned_lines(out) == [(thumb, "Thumb", 0), (arm, "ARM", 0)]
    assert f"2 addresses learned into {learned_path('ATST')}" in out
    played = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30",
                          "--record", RECORDING])
    assert f"no recompiled code at 0x{pressed:08x}" in played.stderr  # further this time
    capsys.readouterr()
    assert main(["learn", "game.gba"]) == 0
    (addr, mode, frame), = learned_lines(capsys.readouterr().out)
    assert (addr, mode) == (pressed, "Thumb") and frame >= 5
    sha1 = inspect_rom(RomImage(rom.data)).sha1
    assert load_learned(learned_path("ATST"), sha1) == ((arm,), (thumb, pressed))
    run = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30"])
    assert run.stdout.splitlines()[-1] == "DONE 3 passed, 0 failed"


def test_learn_says_when_the_replay_stops_at_nothing(tmp_path, monkeypatch, capsys):
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


def test_learn_stops_when_learning_does_not_help(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "err_missing")  # jumps past the end of the ROM
    run_rom(rom, frames=30, args=("--record", RECORDING))
    assert main(["learn", "game.gba"]) == 1
    captured = capsys.readouterr()
    assert "learned 0x08100000 (Thumb)" in captured.out
    assert "has 0x08100000 already, but it is still missing" in captured.err
