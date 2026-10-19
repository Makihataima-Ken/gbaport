import os

from romtest import build_test_rom, run_program

from gbaport.cli import main


def _build(tmp_path, *host: str) -> tuple[str, list]:
    rom = build_test_rom("hello")
    rom_path, config = tmp_path / "hello.gba", tmp_path / "game.toml"
    rom_path.write_bytes(rom.data)
    config.write_text(rom.config, encoding="utf-8")
    out = tmp_path / "out"
    assert main(["build", str(rom_path), "--config", str(config), "--out", str(out), *host]) == 0
    assert (out / "generated" / "gba_rom.c").exists()
    return str(rom_path), [p for p in (out / "build").iterdir() if p.is_file()]


def test_build_writes_sources_and_a_headless_program_that_runs(tmp_path, capsys):
    rom_path, files = _build(tmp_path, "--host", "headless")
    printed = capsys.readouterr().out
    assert "lift issues  0" in printed
    (program,) = [p for p in files if p.stem == "ATST-headless"]
    assert f"built {program}" in printed
    result = run_program([str(program), rom_path])
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "DONE 1 passed, 0 failed"


def test_build_makes_the_window_program_by_default(tmp_path, capsys):
    rom_path, files = _build(tmp_path)
    (program,) = [p for p in files if p.stem == "ATST"]
    assert f"built {program}" in capsys.readouterr().out
    env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy"}  # no window opens
    assert "[--scale N] [--fast]" in run_program([str(program)], env).stderr  # the window host
    result = run_program([str(program), rom_path, "--frames", "60"], env)
    assert result.returncode == 0  # a run limited by --frames ends at Stop, as headless does
    assert result.stdout.splitlines()[-1] == "DONE 1 passed, 0 failed"
