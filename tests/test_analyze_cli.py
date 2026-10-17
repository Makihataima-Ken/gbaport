import json

from ksasm import assemble
from progkit import CRT0, program_rom

from gbaport.cli import main


def write(tmp_path, rom):
    path = tmp_path / "game.gba"
    path.write_bytes(rom.data)
    return path


def test_prints_summary_and_writes_json(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "analysis.json"
    assert main(["analyze", str(write(tmp_path, program_rom(CRT0))), "--out", str(out)]) == 0
    assert "functions    4 (0 veneers)" in capsys.readouterr().out
    assert json.loads(out.read_text())["format"] == "gbaport-analysis/1"


def test_lists_issues(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["analyze", str(write(tmp_path, program_rom("ldr r0, [r1]\nbx r0")))]) == 0
    assert "080000c4  unresolved_jump" in capsys.readouterr().out


def test_uses_games_config_by_default(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = program_rom("bx lr", patches={0x200: assemble("bx lr", thumb=True, addr=0x08000200)})
    config = tmp_path / "games" / "ATST" / "game.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[code]\nthumb_entries = [0x08000200]\n")
    assert main(["analyze", str(write(tmp_path, rom))]) == 0
    out = capsys.readouterr().out
    assert "game.toml" in out and "functions    2 (0 veneers)" in out


def test_bad_config_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.toml"
    bad.write_text("[code]\nbogus = 1\n")
    args = ["analyze", str(write(tmp_path, program_rom("bx lr"))), "--config", str(bad)]
    assert main(args) == 1
    assert "unknown key(s): bogus" in capsys.readouterr().err
