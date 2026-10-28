"""gbaport/native/device.py without a device: adb's answers and the emulator stood in for."""

import pytest

from gbaport.native import device
from gbaport.native.device import Device, DeviceError


def adb_says(monkeypatch, text: str) -> None:
    monkeypatch.delenv("ANDROID_SERIAL", raising=False)  # the stand-in adb names its own device
    monkeypatch.setattr(device, "adb", lambda *args, **kwargs: text)


@pytest.mark.parametrize("state, advice", [
    ("unauthorized", "allow USB debugging from this computer on the phone"),
    ("offline", "unplug it and plug it in again"),
])
def test_a_phone_adb_cannot_use_yet_is_named_with_what_to_do(monkeypatch, state, advice):
    adb_says(monkeypatch, f"List of devices attached\nR58N123\t{state}\n\n")
    with pytest.raises(DeviceError, match=f"R58N123 is {state}: {advice}"):
        device.the_device()


def test_the_files_of_an_app_that_is_not_there_say_so(monkeypatch):
    adb_says(monkeypatch, "run-as: unknown package: org.gbaport.atst\n")
    with pytest.raises(DeviceError, match="org.gbaport.atst is not installed on R58N123, or is "
                                          "not a debug build"):
        Device("R58N123").get_file("org.gbaport.atst", "game.session.input")


def test_a_file_the_app_does_not_have_is_none(monkeypatch):
    adb_says(monkeypatch, "ls: files/game.session.input: No such file or directory\n")
    assert Device("R58N123").get_file("org.gbaport.atst", "game.session.input") is None


def test_an_emulator_that_stops_at_once_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path / "cache"))
    sdk = tmp_path / "sdk"
    for package in ("emulator", device.SYSTEM_IMAGE):
        folder = sdk.joinpath(*package.split(";"))
        folder.mkdir(parents=True)
        (folder / "source.properties").write_text("Pkg.Revision=1\n", encoding="utf-8")
    monkeypatch.setattr(device, "android_sdk", lambda log=print: sdk)
    monkeypatch.setattr(device, "devices", list)  # no device yet
    stopped = []
    monkeypatch.setattr(device, "stop_emulator", lambda phone, process: stopped.append(process))

    class Exited:  # the emulator's process, gone before it booted (a locked AVD, say)
        pid, returncode = 0, 1

        def poll(self):
            return 1

    monkeypatch.setattr(device.subprocess, "Popen", lambda *args, **kwargs: Exited())
    with pytest.raises(DeviceError, match=r"the emulator stopped \(exit status 1\) before it "
                                          r"booted: see .*emulator\.log"):
        device.start_emulator(timeout=5)
    assert stopped == []  # nothing left to shut down
