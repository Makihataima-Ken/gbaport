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


def test_an_error_before_the_game_starts_is_shown_until_it_is_read(phone, tmp_path):
    phone.install(rom_apk("save_counter"))
    phone.stop(APP)
    phone.clear(APP)
    (tmp_path / "game.sav").write_bytes(b"12345")  # no save chip holds 5 bytes
    phone.put_file(APP, tmp_path / "game.sav")  # where the app keeps its save
    phone.clear_log()
    phone.start(APP)
    phone.wait_for(r"^error: \S+game\.sav: the save file has 5 bytes")
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


def counts(phone: Device) -> list[int]:
    """The save_counter ROM's counts so far."""
    return [int(m.group(1)) for line in phone.log() if (m := re.fullmatch(r"COUNT (\d+)", line))]


def test_the_save_survives_the_app_being_killed(phone):
    launch(phone, "save_counter")
    phone.wait_for(r"^COUNT 100$")
    time.sleep(1.5)  # the save is stored once a second while it changes
    phone.stop(APP)
    last = counts(phone)[-1]
    phone.clear_log()
    phone.start(APP)
    saved = int(phone.wait_for(r"^SAVED (\d+)$").group(1))
    assert last - 61 <= saved <= last  # a second's counts at most are lost
    phone.stop(APP)


def test_going_to_the_background_stores_the_save_and_pauses_the_game(phone):
    launch(phone, "save_counter")
    phone.wait_for(r"^COUNT 150$")
    phone.key("KEYCODE_HOME")
    time.sleep(2)
    paused = counts(phone)
    time.sleep(2)
    assert counts(phone) == paused  # no frames in the background
    phone.stop(APP)  # Android kills apps in the background when it needs their memory
    phone.clear_log()
    phone.start(APP)
    assert int(phone.wait_for(r"^SAVED (\d+)$").group(1)) == paused[-1]
    phone.stop(APP)


def test_the_app_keeps_the_gbas_frame_rate_and_says_so(phone):
    launch(phone, "keys_log")
    rate = r"^([\d.]+) frames a second; the game took ([\d.]+) ms a frame$"
    phone.wait_for(rate, timeout=30)
    deadline = time.monotonic() + 30
    while len(rates := [re.match(rate, line) for line in phone.log() if re.match(rate, line)]) < 2:
        assert time.monotonic() < deadline
        time.sleep(1)
    assert 59.2 <= float(rates[1].group(1)) <= 60.2  # the first ten seconds hold the start-up
    assert float(rates[1].group(2)) < 16.7
    phone.stop(APP)


def build_and_install(phone, tmp_path, monkeypatch, rom_name: str, *options: str) -> str:
    """gbaport build --host android --install, onto the emulator; what it printed."""
    monkeypatch.setenv("ANDROID_SERIAL", phone.serial)  # a phone may be connected too
    rom = build_test_rom(rom_name)
    (tmp_path / "game.gba").write_bytes(rom.data)
    (tmp_path / "game.toml").write_text(rom.config, encoding="utf-8")
    phone.clear_log()
    out = FOLDER / "cli"  # kept between runs: Gradle compiles only what changed
    assert main(["build", str(tmp_path / "game.gba"), "--config", str(tmp_path / "game.toml"),
                 "--host", "android", "--install", "--out", str(out), *options]) == 0
    return str(out)


def test_build_installs_the_app_on_the_device_and_starts_it(phone, tmp_path, monkeypatch, capsys):
    out = build_and_install(phone, tmp_path, monkeypatch, "hello")
    printed = capsys.readouterr().out
    assert f"built {out}" in printed and "ATST.apk (x86_64)" in printed  # the device's processor
    assert f"installed it on {phone.serial} and started it" in printed
    phone.wait_for(r"^DONE 1 passed, 0 failed$")
    phone.stop(APP)


def test_build_has_the_game_play_an_input_file_on_the_device(phone, tmp_path, monkeypatch):
    (tmp_path / "presses.input").write_text("﻿# A, then nothing\r\n120 A\r\n150 none\r\n",
                                            encoding="utf-8")
    build_and_install(phone, tmp_path, monkeypatch, "keys_log", "--input",
                      str(tmp_path / "presses.input"))
    phone.wait_for(r"^KEYS A$")
    deadline = time.monotonic() + 10
    while (keys := [line for line in phone.log() if line.startswith("KEYS")]) != \
            ["KEYS none", "KEYS A", "KEYS none"]:
        assert time.monotonic() < deadline, keys
        time.sleep(0.5)
    phone.stop(APP)


def test_an_input_file_plays_on_a_blank_save_and_leaves_the_games_own(phone, tmp_path, monkeypatch):
    launch(phone, "save_counter")
    phone.wait_for(r"^COUNT 100$")
    phone.key("KEYCODE_HOME")  # stores the save
    time.sleep(2)
    kept = counts(phone)[-1]
    (tmp_path / "presses.input").write_text("10 A\n", encoding="utf-8")
    build_and_install(phone, tmp_path, monkeypatch, "save_counter", "--input",
                      str(tmp_path / "presses.input"))
    assert int(phone.wait_for(r"^SAVED (\d+)$").group(1)) == 0  # as it was recorded
    phone.wait_for(r"^COUNT 100$")
    phone.stop(APP)
    phone.clear_log()
    phone.start(APP)
    assert int(phone.wait_for(r"^SAVED (\d+)$").group(1)) == kept
    phone.stop(APP)
