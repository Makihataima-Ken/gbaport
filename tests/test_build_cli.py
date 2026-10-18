from romtest import build_test_rom, run_program

from gbaport.cli import main


def test_build_writes_sources_and_a_program_that_runs(tmp_path, capsys):
    rom = build_test_rom("hello")
    rom_path, config = tmp_path / "hello.gba", tmp_path / "game.toml"
    rom_path.write_bytes(rom.data)
    config.write_text(rom.config, encoding="utf-8")
    out = tmp_path / "out"
    assert main(["build", str(rom_path), "--config", str(config), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "lift issues  0" in printed
    assert (out / "generated" / "gba_rom.c").exists()
    (program,) = [p for p in (out / "build").iterdir() if p.stem == "ATST" and p.is_file()]
    assert f"built {program}" in printed
    result = run_program([str(program), str(rom_path)])
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "DONE 1 passed, 0 failed"
