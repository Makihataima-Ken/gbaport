"""Test ROMs' apps on gbaport's Android emulator (no window, no sound; the first boot takes
a minute or two, and the tests shut it down after them if they started it)."""

import re
import time

import pytest
from androidkit import APP, FOLDER, rom_apk
from romtest import build_test_rom

from gbaport.cli import main
from gbaport.native.device import Device, start_emulator, stop_emulator


@pytest.fixture(scope="module")
def phone():
    device, process = start_emulator()
    yield device
    if process:
        stop_emulator(device, process)


def launch(phone: Device, rom: str, args: str = "") -> None:
    """The test ROM's app, installed afresh with a blank save, started."""
    phone.install(rom_apk(rom))
    phone.stop(APP)
    phone.clear(APP)
    phone.clear_log()
    phone.start(APP, args)


def test_a_test_rom_runs_as_an_app(phone):
    launch(phone, "hello")
    phone.wait_for(r"^DONE 1 passed, 0 failed$")
    assert "hello from the GBA" in phone.log()
    phone.stop(APP)


def test_a_runtime_error_is_printed_and_shown_until_it_is_read(phone):
    launch(phone, "err_missing")
    phone.wait_for(r"^error: no recompiled code at 0x08100000 ")
    time.sleep(3)
    assert phone.running(APP)  # the message waits on the screen
    phone.stop(APP)


def test_the_app_ends_when_the_game_does_and_starts_afresh(phone):
    launch(phone, "hello", "--frames 600")  # a run limited by --frames ends at Stop
    phone.wait_for(r"^DONE 1 passed, 0 failed$")
    deadline = time.monotonic() + 20
    while phone.running(APP) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not phone.running(APP)
    phone.clear_log()
    phone.start(APP)
    phone.wait_for(r"^DONE 1 passed, 0 failed$")
    phone.stop(APP)


def test_the_buttons_on_the_screen_press_the_keys(phone):
    launch(phone, "keys_log")
    layout = phone.wait_for(r"^touch layout: .*").group(0)
    phone.wait_for(r"^KEYS none$")
    a = [float(v) for v in re.search(r" A at (\d+),(\d+)", layout).groups()]
    x, y, radius = (float(v) for v in re.search(r"D-pad at (\d+),(\d+) radius (\d+)", layout).groups())
    phone.hold(*a, 500)
    phone.hold(x + 0.6 * radius, y - 0.6 * radius, 500)  # up and to the right
    deadline = time.monotonic() + 10
    while (keys := [line for line in phone.log() if line.startswith("KEYS")])[-1:] != ["KEYS none"] \
            or len(keys) < 5:
        assert time.monotonic() < deadline, keys
        time.sleep(0.5)
    assert keys == ["KEYS none", "KEYS A", "KEYS none", "KEYS RIGHT+UP", "KEYS none"]
    phone.stop(APP)


def test_build_installs_the_app_on_the_device_and_starts_it(phone, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANDROID_SERIAL", phone.serial)  # a phone may be connected too
    rom = build_test_rom("hello")
    (tmp_path / "hello.gba").write_bytes(rom.data)
    (tmp_path / "game.toml").write_text(rom.config, encoding="utf-8")
    phone.stop(APP)
    phone.clear_log()
    out = FOLDER / "cli"  # kept between runs: Gradle compiles only what changed
    assert main(["build", str(tmp_path / "hello.gba"), "--config", str(tmp_path / "game.toml"),
                 "--host", "android", "--install", "--out", str(out)]) == 0
    assert f"built {out / 'build' / 'ATST.apk'} (x86_64)" in capsys.readouterr().out
    phone.wait_for(r"^DONE 1 passed, 0 failed$")
    phone.stop(APP)
