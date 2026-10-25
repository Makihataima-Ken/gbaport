import subprocess

from liftkit import clang
from progkit import CRT0, program_rom

from gbaport.cli import main


def test_recompile_writes_sources_that_compile(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(program_rom(CRT0).data)
    assert main(["recompile", str(rom)]) == 0
    out = capsys.readouterr().out
    assert "functions    4" in out and "lift issues  0" in out
    generated = tmp_path / "games" / "ATST" / "generated"
    names = sorted(path.name for path in generated.iterdir())
    assert names == ["gba_code_08000000.c", "gba_cpu.h", "gba_dispatch.c", "gba_rom.c"]
    for source in ("gba_code_08000000.c", "gba_dispatch.c", "gba_rom.c"):
        command = [clang(), "-std=c11", "-Wall", "-Werror", "-Wno-unused-label", "-c",
                   str(generated / source), "-o", str(tmp_path / f"{source}.o")]
        subprocess.run(command, check=True, capture_output=True)


def test_recompile_replaces_old_code_files(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(program_rom(CRT0).data)
    out = tmp_path / "gen"
    out.mkdir()
    (out / "gba_code_007.c").write_text("stale")
    (out / "notes.txt").write_text("mine")
    assert main(["recompile", str(rom), "--out", str(out)]) == 0
    assert not (out / "gba_code_007.c").exists()
    assert (out / "notes.txt").read_text() == "mine"
