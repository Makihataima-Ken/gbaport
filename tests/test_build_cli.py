import os

import pytest
from romtest import build_test_rom, run_program

from gbaport import cli
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
    env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy", "SDL_AUDIO_DRIVER": "dummy"}  # no window, no sound
    assert "[--scale N] [--fast]" in run_program([str(program)], env).stderr  # the window host
    result = run_program([str(program), rom_path, "--frames", "60"], env)
    assert result.returncode == 0  # a run limited by --frames ends at Stop, as headless does
    assert result.stdout.splitlines()[-1] == "DONE 1 passed, 0 failed"


def _android(tmp_path, monkeypatch, *options: str) -> dict:
    """gbaport build --host android, with stand-ins for the project and the APK (the real
    ones are built in test_android.py): what they were asked to make."""
    asked = {}

    def project(sources, rom, out, game_code, label, abis, sdl, sdk):
        asked.update(sources=sources, rom=rom, out=out, game_code=game_code, label=label,
                     abis=abis, sdl=sdl, sdk=sdk)
        return out

    def apk(project_folder, path, log=print):
        asked["apk"] = path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"an APK")
        return path

    monkeypatch.setattr(cli, "android_project", project)
    monkeypatch.setattr(cli, "build_apk", apk)
    monkeypatch.setattr(cli, "sdl3_source", lambda: tmp_path / "sdl")
    monkeypatch.setattr(cli, "android_sdk", lambda: tmp_path / "sdk")
    _build(tmp_path, "--host", "android", *options)
    return asked


def test_build_for_android_makes_the_games_app_for_phones(tmp_path, capsys, monkeypatch):
    asked = _android(tmp_path, monkeypatch)
    out = tmp_path / "out"
    assert asked["sources"] == out / "generated" and asked["out"] == out / "build" / "android"
    assert asked["rom"] == build_test_rom("hello").data
    assert (asked["game_code"], asked["label"], asked["abis"]) == ("ATST", "GBAPORTTEST", ("arm64-v8a",))
    assert (asked["sdl"], asked["sdk"]) == (tmp_path / "sdl", tmp_path / "sdk")
    assert asked["apk"] == out / "build" / "ATST.apk"
    assert f"built {out / 'build' / 'ATST.apk'} (arm64-v8a)" in capsys.readouterr().out


def test_build_for_android_takes_the_processors_asked_for(tmp_path, monkeypatch):
    asked = _android(tmp_path, monkeypatch, "--abi", "x86_64", "--abi", "arm64-v8a", "--abi", "x86_64")
    assert asked["abis"] == ("x86_64", "arm64-v8a")


@pytest.mark.parametrize("option", [["--abi", "x86_64"], ["--install"]])
def test_abi_and_install_are_for_android_only(tmp_path, capsys, option):
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    assert main(["build", str(rom_path), "--host", "headless", *option]) == 1
    printed = capsys.readouterr()
    assert "--abi and --install are for --host android" in printed.err
    assert "functions" not in printed.out  # it stopped before recompiling
