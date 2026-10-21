"""An Android phone or emulator, driven through the SDK's adb: install a game's app, start
it, read what it prints (logcat, tag "gbaport"), touch its screen, kill it.

``the_device`` is the one device adb sees (or the one ``ANDROID_SERIAL`` names).
``start_emulator`` boots gbaport's own virtual device from the SDK in the cache folder:
a 720x1280 phone (Android 15, x86_64) drawn by the PC's graphics card, with no window
and no sound. It makes the device the first time (``android-avd`` in the cache folder)
and needs the PC's hypervisor (Windows Hypervisor Platform). ``stop_emulator`` shuts it
down again.
"""

import os
import re
import shlex
import signal
import subprocess
import time
from pathlib import Path

from gbaport.native.android import android_sdk, install_packages, installed, java_environment
from gbaport.native.sdl3 import cache_folder

ACTIVITY = "org.gbaport.game.GameActivity"
SYSTEM_IMAGE = "system-images;android-35;google_apis;x86_64"
AVD = "gbaport"
EMULATOR_PORT = 5584
LOG_LINE = re.compile(r"^\S+\s+\S+\s+\d+\s+\d+\s+\w\s+gbaport\s*: (.*)$")  # logcat -v threadtime


class DeviceError(OSError):
    """adb failed, or the device did not do what was asked in time."""


def adb(*args: str, serial: str | None = None, timeout: float = 120) -> str:
    program = android_sdk() / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    command = [str(program), *(("-s", serial) if serial else ()), *args]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        raise DeviceError(f"adb {' '.join(args)} took more than {timeout} s") from error
    if result.returncode != 0:
        raise DeviceError(f"adb {' '.join(args)} failed: {(result.stdout + result.stderr).strip()}")
    return result.stdout


def devices() -> list[str]:
    """The serial numbers of the devices adb sees, ready to use."""
    lines = adb("devices").splitlines()[1:]
    return [line.split()[0] for line in lines if line.strip().endswith("\tdevice")]


def the_device() -> "Device":
    """The one device adb sees; with several, the one ANDROID_SERIAL names."""
    found = devices()
    serial = os.environ.get("ANDROID_SERIAL")
    if serial:
        if serial not in found:
            raise DeviceError(f"ANDROID_SERIAL is {serial}, but adb sees "
                              f"{', '.join(found) or 'no device'}")
        return Device(serial)
    if not found:
        raise DeviceError("no Android device: connect a phone with USB debugging on, or "
                          "start an emulator")
    if len(found) > 1:
        raise DeviceError(f"several Android devices ({', '.join(found)}): set ANDROID_SERIAL "
                          "to the one to use")
    return Device(found[0])


class Device:
    def __init__(self, serial: str):
        self.serial = serial

    def adb(self, *args: str, timeout: float = 120) -> str:
        return adb(*args, serial=self.serial, timeout=timeout)

    def shell(self, *words: str) -> str:
        """Runs a command on the device; each word reaches it as one argument."""
        return self.adb("shell", " ".join(shlex.quote(word) for word in words))

    def abi(self) -> str:
        """The device's processor, as the NDK names it (arm64-v8a, x86_64)."""
        return self.shell("getprop", "ro.product.cpu.abi").strip()

    def install(self, apk: Path) -> None:
        self.adb("install", "-r", str(apk), timeout=300)

    def start(self, app: str, args: str = "") -> None:
        """Starts the game's app, with ``args`` as on the desktop host's command line."""
        extra = ("--es", "gbaport.args", args) if args else ()
        self.shell("am", "start", "-W", "-n", f"{app}/{ACTIVITY}", *extra)

    def stop(self, app: str) -> None:
        """Kills the app, as Android kills apps in the background when it needs memory."""
        self.shell("am", "force-stop", app)

    def clear(self, app: str) -> None:
        """Deletes the app's files, its save among them."""
        self.shell("pm", "clear", app)

    def running(self, app: str) -> bool:
        return bool(self.adb("shell", f"pidof {shlex.quote(app)} || true").strip())

    def key(self, name: str) -> None:
        """Presses one of Android's keys (KEYCODE_HOME: leave the app for the home screen)."""
        self.shell("input", "keyevent", name)

    def hold(self, x: float, y: float, ms: int) -> None:
        """A finger on the screen at (x, y) pixels for ``ms`` milliseconds."""
        self.shell("input", "swipe", *(str(round(v)) for v in (x, y, x, y)), str(ms))

    def clear_log(self) -> None:
        self.adb("logcat", "-c")

    def log(self) -> list[str]:
        """What the game's app printed since the log was last cleared, a line each."""
        lines = self.adb("logcat", "-d", "-v", "threadtime", "-s", "gbaport:V").splitlines()
        return [m.group(1) for line in lines if (m := LOG_LINE.match(line))]

    def wait_for(self, pattern: str, timeout: float = 60) -> re.Match:
        """The first line the app printed that matches ``pattern``, waiting for it."""
        deadline = time.monotonic() + timeout
        while True:
            lines = self.log()
            for line in lines:
                if found := re.search(pattern, line):
                    return found
            if time.monotonic() > deadline:
                raise DeviceError(f"the app printed no line matching {pattern!r} in {timeout} s; "
                                  "its last lines:\n" + "\n".join(lines[-30:]))
            time.sleep(0.5)


def start_emulator(timeout: float = 600) -> tuple[Device, subprocess.Popen | None]:
    """gbaport's emulator, booted, and its process if this call started it (None if it
    was running already). It boots afresh each time (no quick-boot snapshot to load or
    save), so it starts the same way and shuts down at once."""
    serial = f"emulator-{EMULATOR_PORT}"
    device = Device(serial)
    if serial in devices():
        try:
            device.adb("shell", "echo running", timeout=20)
        except DeviceError as error:
            raise DeviceError(f"{serial} is there but does not answer: end its "
                              "qemu-system-x86_64 process and try again") from error
        return device, None
    sdk = android_sdk()
    missing = [p for p in ("emulator", SYSTEM_IMAGE) if not installed(sdk, p)]
    if missing:
        install_packages(sdk, missing)
    home = cache_folder() / "android-avd"
    _make_avd(home)
    env = {**java_environment(), "ANDROID_AVD_HOME": str(home), "ANDROID_HOME": str(sdk)}
    program = sdk / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")
    with open(home / "emulator.log", "wb") as log:
        process = subprocess.Popen(
            [str(program), "-avd", AVD, "-port", str(EMULATOR_PORT), "-no-window", "-no-audio",
             "-no-boot-anim", "-no-snapshot", "-gpu", "host"],
            stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if serial in devices() and device.shell("getprop", "sys.boot_completed").strip() == "1":
                # Android's "viewing full screen" notice would cover the app the first time
                device.shell("settings", "put", "secure", "immersive_mode_confirmations", "confirmed")
                return device, process
        except DeviceError:
            pass  # still booting
        time.sleep(2)
    stop_emulator(device, process)
    raise DeviceError(f"the emulator did not boot in {timeout} s (see {home / 'emulator.log'})")


def stop_emulator(device: Device, process: subprocess.Popen) -> None:
    """Shuts down an emulator that start_emulator started, and waits until it has gone."""
    try:
        device.adb("emu", "kill", timeout=30)
        process.wait(timeout=60)
    except (DeviceError, subprocess.TimeoutExpired):
        if os.name == "nt":  # the launcher and the qemu it runs
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=60)


def _make_avd(home: Path) -> None:
    folder = home / f"{AVD}.avd"
    if (folder / "config.ini").exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    config = {
        "avd.ini.encoding": "UTF-8", "abi.type": "x86_64", "hw.cpu.arch": "x86_64",
        "hw.cpu.ncore": "4", "hw.ramSize": "2048", "disk.dataPartition.size": "4G",
        "image.sysdir.1": "/".join(SYSTEM_IMAGE.split(";")) + "/", "tag.id": "google_apis",
        "target": "android-35", "hw.lcd.width": "720", "hw.lcd.height": "1280",
        "hw.lcd.density": "320", "hw.screen": "multi-touch", "hw.keyboard": "yes",
        "hw.gpu.enabled": "yes", "hw.gpu.mode": "host", "hw.audioInput": "no",
        "hw.audioOutput": "no", "hw.camera.back": "none", "hw.camera.front": "none",
    }
    (folder / "config.ini").write_text("".join(f"{k}={v}\n" for k, v in config.items()),
                                       encoding="utf-8")
    (home / f"{AVD}.ini").write_text(
        f"avd.ini.encoding=UTF-8\npath={folder}\ntarget=android-35\n", encoding="utf-8")
