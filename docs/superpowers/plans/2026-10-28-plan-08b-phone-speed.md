# Plan 8b: Phone Speed and Fixes — Implementation Plan

> Carry this plan out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user's game leaves more of each frame free on their phone, and the phone says where the frame's time goes. The deferred findings of Plans 8 and 7c that a user meets are fixed.

**Architecture:**
- **Measured first.**
  - simpleperf on the user's phone (Samsung SM-A165F: two Cortex-A76 cores and six A55s) and on the emulator found the renderer taking 56–78% of the game's thread.
  - The phone runs that thread on its slow cores, or on its fast cores at 1.2–1.6 of their 2.2 GHz.
  - Handing a frame to the screen took a steady 4.5–5 ms on the phone. Nearest-neighbour scaling, switching vsync off and the texture's pixel format changed none of it.
- **The report (`host_sdl.c`, phones).** The ten-second frame-rate line splits the game's time into running the game, drawing the picture and handing it to the screen: `59.73 frames a second; the game took 9.6 ms a frame (running 4.32, drawing 0.48, showing 4.81)`.
- **The renderer (`render.c`).**
  - Text backgrounds are drawn a tile at a time. A 16-colour tile's row is read as one word.
  - Compositing works out the layer order once a line instead of for every pixel.
  - On a line with no window, no colour effect that a layer takes, and no semi-transparent sprite, compositing paints the layers bottom-up instead of searching each pixel's layers. BT4E's fight is such a line throughout: BLDCNT 0x1040 names no 1st target.
  - On the PC, 20000 frames of `walk-right.input` went from 13.3 s to 5.3 s, and the fight from 0.65 to 0.43 ms a frame. On the phone, the fight's running time went from 6.9–8.5 ms to 4.3–5.3 ms.
- **The fixes,** each with its test:
  - **Android:**
    - the drawn buttons come back when the gamepad goes away (the state moves into `touch.c`);
    - odd titles and game codes are escaped in the Gradle and resource files;
    - a phone adb lists but cannot use (unauthorized, offline) is named with what to do;
    - `--install` checks the device's processor before the long build;
    - an emulator that stops at once says so;
    - `get_file` tells a missing or non-debug app from a missing file.
  - **Build tools:** sdkmanager's output is decoded as UTF-8 with replacements, downloads time out, and the compiler's version is part of the object cache's key.
  - **`learn`:** a replay that takes too long is an error, not a traceback. An address learning cannot help is taken out of `learned.toml`, with what might help instead. The sweep steps over the nops GNU as pads Thumb code with.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime (clang, the NDK's clang for phones); the Android emulator for the phone tests; simpleperf from the NDK for profiling.

**Spec:** `docs/superpowers/specs/2026-10-28-any-rom-design.md` (section 8 and the roadmap's first row), on top of `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - The roadmap's P8 acceptance, verbatim: "APK runs on device at 60 fps; save survives app kill". This plan keeps both, with more of each frame free.
  - "Emulators are dev-time test oracles only."
  - "No ROM-derived bytes in git."
  - The renderer's rules: "Scanline software renderer in C reproducing GBA compositing (modes 0–5, sprites, affine, windows, blending, mosaic), with per-scanline register latching so raster effects work." The renderer tests (comparing every pixel with mGBA) must pass unchanged.
- **From the any-ROM design:** "BT4E getting slower on the phone once its code is native, or `gbaport verify` getting worse than today for BT4E (3600 frames: 1211 pictures in the same order, at most 1 frame apart)" is a failure. This plan goes first so that the interpreter of Plan 12 is measured against a fast native build.
- **Where this plan comes from.** The user chose it on 2026-10-25 ("Phone speed + fixes") and skipped the design questions. The any-ROM design, approved on 2026-10-28, puts it first in its roadmap. My calls:
  - **Performance hints and pinning left out.** Android's performance hints (`APerformanceHint`, tried and measured on the phone) and pinning the game's thread to the fast cores are not in it. Both moved the thread to the fast cores, but the fight's running time barely changed (5.7–6.9 ms against 5.2–6.5): the cores ran at 1.2–1.6 GHz.
  - **Two minors stay deferred.** `fsync` before the save's rename, and redrawing after the phone loses its graphics context. No test can observe either.
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer, and nothing in a commit or a committed file names the tools that wrote it.
  - Never commit a `.gba` file.
  - Tests never open a window and never play sound.
  - Whoever carries out or reviews this plan never reads or prints bytes of `roms/` or `build/`.
- **Commands:**
  - Smart App Control blocks `uv.exe` and the `gbaport.exe` launcher, so every command runs the project's Python directly: `.venv/Scripts/python.exe -m gbaport.cli ...`, `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/python.exe -m ruff check src tests`, from the repository's root.
  - Run the tests and ruff as separate commands.
  - Never run two test runs at once.
  - Write code that holds backslashes with the Edit or Write tools, never a shell heredoc.
  - Smart App Control sometimes refuses freshly built test programs. A test that fails with "Windows refused to start" passes when run again.

## Review Focus

1. **A line that has a window, an effect or a semi-transparent sprite.** It must still take the slow path; the fast path is right only without them. Pinned in Task 2 by the renderer tests: windows, alpha and brightness, semi-transparent sprites, compared with mGBA.
2. **A text background whose tile row runs past background VRAM.** It must stay transparent there, as before. Pinned in Task 2 (`tests/runtime/test_render_text.py`'s VRAM-end case runs both the word path and the byte path).
3. **A phone waiting for "Allow USB debugging?".** The message must say what to do, not "no Android device". Pinned in Task 3 (`test_a_phone_adb_cannot_use_yet_is_named_with_what_to_do`).
4. **A gamepad unplugged mid-game.** The drawn buttons must come back. Pinned in Task 3 (`test_a_gamepad_hides_the_buttons_until_a_finger_comes_down_or_it_is_unplugged`).
5. **An address learning cannot help.** It must not stay in `learned.toml` to fail every later run. Pinned in Task 5 (`test_learn_stops_when_learning_does_not_help`).

## Known limitations (deliberate; later plans)

- **The phone's cores and clock.** Android keeps the game's thread on the slow cores in light scenes, and the fast cores run at 1.2–1.6 GHz in the fight. The same code headless on a fast core at full clock takes about a third of the time. Performance hints and pinning did not raise the clock (Global Constraints).
- **Handing the frame to the screen** takes 4.5–5 ms on the user's phone whatever the picture. It does not grow with the game's work, so it limits the frame to about 11.5 ms of running.
- **Lines with windows or effects** still take the per-pixel path.

---

### Task 1: Where the phone's frame time goes

**Files:**
- Modify: `src/gbaport/runtime/host_sdl.c`
- Test: `tests/test_android_device.py`

**Interfaces:**
- Produces: the log line `F frames a second; the game took T ms a frame (running R, drawing D, showing S)`, with R + D + S = T to the rounding.

- [ ] **Step 1: Write the failing test**

In `tests/test_android_device.py`, replace:
```python

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


```
with:
```python

def test_the_app_keeps_the_gbas_frame_rate_and_says_so(phone):
    launch(phone, "keys_log")
    rate = (r"^([\d.]+) frames a second; the game took ([\d.]+) ms a frame "
            r"\(running ([\d.]+), drawing ([\d.]+), showing ([\d.]+)\)$")
    phone.wait_for(rate, timeout=30)
    deadline = time.monotonic() + 30
    while len(rates := [re.match(rate, line) for line in phone.log() if re.match(rate, line)]) < 2:
        assert time.monotonic() < deadline
        time.sleep(1)
    assert 59.2 <= float(rates[1].group(1)) <= 60.2  # the first ten seconds hold the start-up
    took, parts = float(rates[1].group(2)), [float(rates[1].group(n)) for n in (3, 4, 5)]
    assert took < 16.7
    assert abs(sum(parts) - took) < 0.15  # where the time went: the game, the picture, the screen
    phone.stop(APP)


```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_android_device.py -k frame_rate`
Expected: FAIL: 1 failed, 11 deselected, `DeviceError: the app printed no line matching ... (running ...` in 30 s. The emulator boots for it.

- [ ] **Step 3: Split the frame's time in `host_sdl.c`**

- **The counts.** Next to `busy`: `static Uint64 running, drawing, showing;`.
- **The timestamps.** `on_frame` (phones) takes three:
  - `ran`, at its start, before the events are read;
  - `drawn`, after `present()`;
  - `waited`, after `SDL_RenderPresent`, as now.
- **`report_rate(Uint64 ran, Uint64 drawn, Uint64 waited)`.** When `awake` is set, it adds `waited - awake` to `busy`, `ran - awake` to `running`, `drawn - ran` to `drawing` and `waited - drawn` to `showing`.
  - Every 600 frames it prints `"%.2f frames a second; the game took %.1f ms a frame (running %.2f, drawing %.2f, showing %.2f)\n"` and clears all four.
  - Its comment says what the three parts are.
- **The file's comment** for phones gains "(running the game, drawing the picture, handing it to the screen)".

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 955 passed.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_sdl.c tests/test_android_device.py
git commit -m "feat: the phone says where each frame's time goes: running, drawing, showing"
```

---

### Task 2: A faster renderer

The renderer tests compare every pixel with mGBA: windows, blending, brightness, semi-transparent sprites, mosaic, affine and bitmap modes. They pin this task's behaviour. It changes how lines are drawn, not what is drawn, so it adds no test. The benchmark below shows the speed.

**Files:**
- Modify: `src/gbaport/runtime/render.c`

- [ ] **Step 1: The speed before**

```bash
.venv/Scripts/python.exe -m gbaport.cli build roms/mygame.gba --host headless --out build/BT4E-h
```

Then time `build/BT4E-h/build/BT4E-headless.exe roms/mygame.gba --input games/BT4E/walk-right.input --frames 20000 --save build/t.sav` three times, deleting `build/t.sav` before each run.
Expected: about 13 s each.

- [ ] **Step 2: Text backgrounds a tile at a time**

In `text_line`, one map entry per tile instead of per pixel:
- **Per tile.** Read the entry, then the tile row's address `base`: `char_base + tile * 64 + ty * 8` for 256 colours, `char_base + tile * 32 + ty * 4` for 16, with `ty` flipped by bit 11. Also `flip` (7 when bit 10 is set, else 0) and `bank` (`(entry >> 12) * 16` for 16 colours).
- **The pixels.** From `in_x & 7` to the tile's end (or the line's), each pixel's column is `from ^ flip`.
- **16 colours inside background VRAM** (`base + 4 <= 0x10000`): read the row as one little-endian word. Pixel `tx`'s colour is `(word >> (tx * 4)) & 15`; 0 is CLEAR, else palette entry `bank + colour`.
- **Otherwise,** the per-pixel path as now: an address at or past 0x10000 is CLEAR.
- **The next tile** starts at `in_x = ((in_x | 7) + 1) & 0x1FF`.

- [ ] **Step 3: Compositing: the order once a line, and the painter's way where nothing else applies**

In `compose`, before the pixel loop, build `order[]` once a line: for each priority from 0 to 3, the sprites (layer 4, with that priority, when they are on), then the backgrounds of that priority in BG0–BG3 order. The pixel loop walks `order[]` instead of re-reading BGnCNT for every pixel. Before the pixel loop:

```c
    int effects = effect != 0 && (targets & 0x3F) != 0;  /* an effect with a 1st target */
    if (!(IO(rt, GBA_REG_DISPCNT) & 0xE000) && !effects && !memchr(layers->obj_semi, 1, W)) {
        /* no windows, no colour effect any layer takes, no semi-transparent sprite on this
         * line: each pixel is the topmost colour there, so paint the layers from the bottom up */
        for (int x = 0; x < W; x++)
            row[x] = backdrop;
        for (int i = count - 1; i >= 0; i--) {
            if (order[i] == 4) {
                for (int x = 0; x < W; x++)
                    if (layers->obj_priority[x] == order_priority[i] && layers->obj[x] != CLEAR)
                        row[x] = layers->obj[x];
            } else {
                const uint16_t *line = layers->bg[order[i]];
                for (int x = 0; x < W; x++)
                    if (line[x] != CLEAR)
                        row[x] = line[x];
            }
        }
        return;
    }
```

The module's comment gains: "Lines are drawn a tile at a time, and composed by painting the layers bottom-up where no window, colour effect or semi-transparent sprite is on the line."

- [ ] **Step 4: Run the renderer's tests, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime -k "render or screen"`
Expected: 81 passed, 214 deselected.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 955 passed.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: The speed after, and the user's game against mGBA**

Rebuild with the Step 1 command and time the same 20000 frames.
Expected: about 5.3 s each, 2.5 times faster.

Run: `.venv/Scripts/python.exe -m gbaport.cli verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input`
Expected: `verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart`, as before.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/runtime/render.c
git commit -m "perf: the renderer draws text backgrounds a tile at a time and composes most lines bottom-up"
```

---

### Task 3: Android fixes

**Files:**
- Modify: `src/gbaport/runtime/touch.h`, `touch.c`, `host_sdl.c`, `src/gbaport/native/android.py`, `device.py`, `src/gbaport/cli.py`
- Create: `tests/test_device.py`
- Test: `tests/runtime/test_touch.py` (and `tests/touchhost.c`), `tests/test_build_cli.py`, `tests/test_android.py`

**Interfaces:**
- Produces:
  - **`touch.h`:** `TouchState.hidden`, `touch_gamepad_pressed(TouchState *)`, `touch_gamepad_removed(TouchState *)`.
  - **`device.py`:** `ADVICE`, `device_states() -> dict[str, str]`, and `Device.get_file` raising `DeviceError` for a missing or non-debug app.

- [ ] **Step 1: Write the failing tests**

In `tests/runtime/test_touch.py`, replace:
```python
    out = touch(PHONE, *resting, f"down 10 {sx} {sy}", "keys", "up 10", "up 3",
                f"down 11 {ax} {ay}", "keys")
    assert out[-2:] == ["none", "A"]
```
with:
```python
    out = touch(PHONE, *resting, f"down 10 {sx} {sy}", "keys", "up 10", "up 3",
                f"down 11 {ax} {ay}", "keys")
    assert out[-2:] == ["none", "A"]


def test_a_gamepad_hides_the_buttons_until_a_finger_comes_down_or_it_is_unplugged():
    seen = touch(PHONE, "shown", "gamepad", "shown", "down 1 1200 540", "shown", "up 1",
                 "gamepad", "unplug", "shown")
    assert seen[-4:] == ["shown", "hidden", "shown", "shown"]
```

In `tests/test_android.py`, replace:
```python
        assert zipped.getinfo("assets/game.gba").compress_type == zipfile.ZIP_STORED
        dex = b"".join(zipped.read(name) for name in names if name.endswith(".dex"))
    assert b"Lorg/gbaport/game/GameActivity;" in dex
```
with:
```python
        assert zipped.getinfo("assets/game.gba").compress_type == zipfile.ZIP_STORED
        dex = b"".join(zipped.read(name) for name in names if name.endswith(".dex"))
    assert b"Lorg/gbaport/game/GameActivity;" in dex


def test_odd_titles_and_game_codes_go_into_the_project_safely(tmp_path):
    out = android.android_project(generated(tmp_path, "gba_code_08000000.c"), b"1", tmp_path / "p",
                                  'A"\\B', '@Mo\\ "Best"\x01?', ("x86_64",), fake_sdl(tmp_path),
                                  tmp_path / "sdk")
    assert 'rootProject.name = "AB"' in (out / "settings.gradle").read_text(encoding="utf-8")
    strings = out / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    assert '<string name="app_name">\\@Mo\\\\ \\"Best\\"?</string>' in \
        strings.read_text(encoding="utf-8")
```

In `tests/test_build_cli.py`, replace:
```python
    command = ["build", str(rom_path), "--host", "android", "--input", str(tmp_path / "game.input")]
    assert main(command) == 1
    assert "--input is for --install" in capsys.readouterr().err
```
with:
```python
    command = ["build", str(rom_path), "--host", "android", "--input", str(tmp_path / "game.input")]
    assert main(command) == 1
    assert "--input is for --install" in capsys.readouterr().err


class Phone:
    """A device that says which processor it has, and nothing more."""
    serial = "R58N123"

    def __init__(self, abi: str):
        self.processor = abi

    def abi(self) -> str:
        return self.processor


@pytest.mark.parametrize("abi, options, message", [
    ("armeabi-v7a", (), "R58N123 runs armeabi-v7a code; gbaport builds for arm64-v8a and x86_64"),
    ("arm64-v8a", ("--abi", "x86_64"),
     "R58N123 runs arm64-v8a code: build with --abi arm64-v8a, or with no --abi"),
])
def test_install_checks_the_devices_processor_before_the_long_build(tmp_path, capsys, monkeypatch,
                                                                    abi, options, message):
    monkeypatch.setattr(cli, "the_device", lambda: Phone(abi))
    monkeypatch.setattr(cli, "android_project", lambda *args: tmp_path / "project")
    monkeypatch.setattr(cli, "build_apk", lambda project, path, log=print: path)
    monkeypatch.setattr(cli, "sdl3_source", lambda: tmp_path / "sdl")
    monkeypatch.setattr(cli, "android_sdk", lambda: tmp_path / "sdk")
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    command = ["build", str(rom_path), "--host", "android", "--install", "--out", str(tmp_path / "out")]
    assert main([*command, *options]) == 1
    printed = capsys.readouterr()
    assert message in printed.err
    assert "functions" not in printed.out  # it stopped before recompiling
```

Create `tests/test_device.py`:
```python
"""gbaport/native/device.py without a device: adb's answers and the emulator stood in for."""

import pytest

from gbaport.native import device
from gbaport.native.device import Device, DeviceError


def adb_says(monkeypatch, text: str) -> None:
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
```

In `tests/touchhost.c`, replace:
```c
 *                              prints the picture's box, the D-pad and each button's box
 *     down ID X Y | move ID X Y | up ID
 *     keys                     prints the keys held, "A+RIGHT" or "none"
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
```
with:
```c
 *                              prints the picture's box, the D-pad and each button's box
 *     down ID X Y | move ID X Y | up ID
 *     keys                     prints the keys held, "A+RIGHT" or "none"
 *     gamepad | unplug         a gamepad's button pressed, the gamepad gone
 *     shown                    prints whether the drawn buttons show: "shown" or "hidden"
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
```

In `tests/touchhost.c`, replace:
```c
            touch_move(&touch, id, a, b);
        } else if (strcmp(command, "up") == 0 && sscanf(line, "%*s %llu", &id) == 1) {
            touch_up(&touch, id);
        } else if (strcmp(command, "keys") == 0) {
            unsigned keys = touch_keys(&touch);
            int first = 1;
```
with:
```c
            touch_move(&touch, id, a, b);
        } else if (strcmp(command, "up") == 0 && sscanf(line, "%*s %llu", &id) == 1) {
            touch_up(&touch, id);
        } else if (strcmp(command, "gamepad") == 0) {
            touch_gamepad_pressed(&touch);
        } else if (strcmp(command, "unplug") == 0) {
            touch_gamepad_removed(&touch);
        } else if (strcmp(command, "shown") == 0) {
            printf("%s\n", touch.hidden ? "hidden" : "shown");
        } else if (strcmp(command, "keys") == 0) {
            unsigned keys = touch_keys(&touch);
            int first = 1;
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_touch.py tests/test_device.py tests/test_build_cli.py tests/test_android.py`
Expected: FAIL: 9 failed:
- the gamepad test (`touchhost.c` does not compile against the old `touch.h`);
- the two device-state messages ("no Android device");
- `get_file` (the real adb's "device 'R58N123' not found" twice);
- the emulator's "did not boot in 5 s";
- the two processor checks (the build reaches "functions" and the stand-in device);
- the project's `rootProject.name`.

- [ ] **Step 3: The fixes**

- **`touch.h`, `touch.c`.**
  - `int hidden;` in `TouchState` ("a gamepad is in use: the drawn buttons are out of the way").
  - `touch_down` sets it to 0 first, the 11th finger included.
  - `touch_gamepad_pressed` sets it to 1; `touch_gamepad_removed` sets it to 0.
- **`host_sdl.c`.**
  - `touch_hidden` goes; drawing uses `touch.hidden`.
  - `SDL_EVENT_GAMEPAD_BUTTON_DOWN` calls `touch_gamepad_pressed`.
  - A new case, `SDL_EVENT_GAMEPAD_REMOVED`, calls `touch_gamepad_removed`.
- **`android.py`.**
  - `NAME` is the game code's ASCII letters and digits, or `game`.
  - `_xml` becomes `_resource_string(text)`: printable characters only, then `&`, `<`, `>` as XML entities, then `\`, `"` and `'` backslashed, and a leading `@` or `?` backslashed.
- **`device.py`.**
  - `device_states()` parses `adb devices` into serial → state. `devices()` is the serials whose state is `device`.
  - `ADVICE` maps `unauthorized` to "allow USB debugging from this computer on the phone (if it does not ask, unplug it and plug it in again)" and `offline` to "unplug it and plug it in again".
  - `the_device()`: with no ready device but listed ones, raise `DeviceError` joining `f"{serial} is {state}: {advice}"` (`adb cannot use it yet` for other states). With `ANDROID_SERIAL` naming a listed device that is not ready, give the same message for it.
  - `get_file` lists `files/NAME` with `2>&1`:
    - a reply starting `run-as:` raises `DeviceError(f"{app} is not installed on {serial}, or is not a debug build ({reply})")`;
    - a reply other than the path returns None.
  - `start_emulator`: when the process has exited when the wait ends, raise `DeviceError(f"the emulator stopped (exit status {process.returncode}) before it booted: see {home / 'emulator.log'}")` without calling `stop_emulator`.
  - `stop_emulator`'s `os.killpg` ignores `ProcessLookupError`.
- **`cli.py`.** Right after `the_device()`, and before recompiling, check the device's ABI:
  - not in `ANDROID_ABIS`: `f"{serial} runs {abi} code; gbaport builds for arm64-v8a and x86_64"`;
  - `--abi` given without the device's ABI: `f"{serial} runs {abi} code: build with --abi {abi}, or with no --abi"`.

  The old check in `_build_android` goes.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 964 passed (955 + 9).

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/touch.h src/gbaport/runtime/touch.c src/gbaport/runtime/host_sdl.c src/gbaport/native/android.py src/gbaport/native/device.py src/gbaport/cli.py tests/test_device.py tests/runtime/test_touch.py tests/touchhost.c tests/test_build_cli.py tests/test_android.py
git commit -m "fix: buttons back when a gamepad goes, odd titles, phones adb cannot use yet, the processor checked first, clearer device errors"
```

---

### Task 4: Build tool fixes

**Files:**
- Modify: `src/gbaport/native/android.py`, `src/gbaport/native/build.py`
- Test: `tests/test_android.py`, `tests/test_native_build.py`

**Interfaces:**
- Produces: `android.DOWNLOAD_TIMEOUT = 120` (seconds); `build.compiler_version(clang: str) -> str` (cached).

- [ ] **Step 1: Write the failing tests**

In `tests/test_android.py`, replace:
```python
        calls.write(f"{len(answers)} answers:")
        for package in Path(args["--package_file"]).read_text(encoding="utf-8").split():
            calls.write(" " + package)
            if "broken" not in package:
                folder = sdk.joinpath(*package.split(";"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "source.properties").write_text("Pkg.Revision=1\\n", encoding="utf-8")
```
with:
```python
        calls.write(f"{len(answers)} answers:")
        for package in Path(args["--package_file"]).read_text(encoding="utf-8").split():
            calls.write(" " + package)
            if "broken" in package:  # says why in bytes that are not text in any code page
                sys.stdout.buffer.write(b"\\x81\\x8d cannot install " + package.encode() + b"\\n")
            else:
                folder = sdk.joinpath(*package.split(";"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "source.properties").write_text("Pkg.Revision=1\\n", encoding="utf-8")
```

In `tests/test_android.py`, replace:
```python
def test_a_package_that_does_not_install_is_named(cache, monkeypatch):
    fake_sdk(cache)
    monkeypatch.setattr(android, "SDK_PACKAGES", ("platform-tools", "broken;1"))
    with pytest.raises(ToolchainError, match=r"installing broken;1 failed"):
        android.android_sdk(log=quiet)


def test_a_download_must_match_its_published_digest(tmp_path):
```
with:
```python
def test_a_package_that_does_not_install_is_named(cache, monkeypatch):
    fake_sdk(cache)
    monkeypatch.setattr(android, "SDK_PACKAGES", ("platform-tools", "broken;1"))
    with pytest.raises(ToolchainError, match=r"installing broken;1 failed[\s\S]*cannot install broken;1"):
        android.android_sdk(log=quiet)  # its words, whatever bytes they come in


def test_a_download_must_match_its_published_digest(tmp_path):
```

In `tests/test_android.py`, replace:
```python
    assert not (tmp_path / "x.zip.partial").exists()


def test_gradle_and_sdl3s_source_come_unpacked_into_the_cache(cache, monkeypatch, tmp_path):
    gradle_zip = io.BytesIO()
    with zipfile.ZipFile(gradle_zip, "w") as zipped:
```
with:
```python
    assert not (tmp_path / "x.zip.partial").exists()


def test_a_download_gives_up_on_a_server_that_stops_answering(tmp_path, monkeypatch):
    asked = {}

    def stalls(url, timeout=None):
        asked["timeout"] = timeout
        raise TimeoutError("timed out")

    monkeypatch.setattr(android.urllib.request, "urlopen", stalls)
    with pytest.raises(ToolchainError, match="cannot download .*timed out"):
        android._download("https://dl.google.com/x.zip", tmp_path / "x.zip", "0" * 64)
    assert asked["timeout"] == android.DOWNLOAD_TIMEOUT  # a stalled server ends it, not hangs it


def test_gradle_and_sdl3s_source_come_unpacked_into_the_cache(cache, monkeypatch, tmp_path):
    gradle_zip = io.BytesIO()
    with zipfile.ZipFile(gradle_zip, "w") as zipped:
```

In `tests/test_native_build.py`, replace:
```python
    assert program.exists()


def test_writing_the_same_sources_again_leaves_their_files_alone(tmp_path):
    native.write_sources({"gba_code_08000000.c": "a", "gba_code_08002000.c": "b",
                          "gba_dispatch.c": "c"}, tmp_path)
```
with:
```python
    assert program.exists()


def test_another_compiler_compiles_everything_again(tmp_path, monkeypatch):
    _sources(tmp_path)
    said = []
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    monkeypatch.setattr(native, "compiler_version", lambda clang: "clang version 99.0.0")
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    total = int(said[0].split()[3])
    assert said[-1] == f"compiled {total} of {total} files"  # an LLVM update in place, say


def test_writing_the_same_sources_again_leaves_their_files_alone(tmp_path):
    native.write_sources({"gba_code_08000000.c": "a", "gba_code_08002000.c": "b",
                          "gba_dispatch.c": "c"}, tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_android.py tests/test_native_build.py`
Expected: FAIL: 3 failed:
- `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'`: the output reader died on the bytes;
- `AttributeError: ... 'DOWNLOAD_TIMEOUT'`;
- `AttributeError: ... 'compiler_version'`.

- [ ] **Step 3: The fixes**

- **`install_packages`.** Runs sdkmanager with `encoding="utf-8", errors="replace"`.
- **`_download`.** Opens the URL with `timeout=DOWNLOAD_TIMEOUT`: "seconds a stalled download waits for the next bytes".
- **`build.py`.**
  - `@functools.cache def compiler_version(clang)` is the first line of `clang --version` ("" if none).
  - `compile_native` starts its header digest with it: `hashlib.sha1(compiler_version(clang).encode())`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 966 passed (964 + 2).

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/native/android.py src/gbaport/native/build.py tests/test_android.py tests/test_native_build.py
git commit -m "fix: sdkmanager's bytes, stalled downloads, and a new compiler's objects"
```

---

### Task 5: learn and sweep fixes

**Files:**
- Modify: `src/gbaport/learn.py`, `src/gbaport/analysis/discover.py`
- Test: `tests/test_learn.py`, `tests/analysis/test_discover.py`, `tests/progkit.py`

**Interfaces:**
- Produces: `discover.THUMB_NOP = 0x46C0`; `learn._why_missing(addr, rom_size) -> str`.

- [ ] **Step 1: Write the failing tests**

In `tests/analysis/test_discover.py`, replace:
```python
    KNOWN_JUMP,
    RECURSION,
    SWEEP,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
```
with:
```python
    KNOWN_JUMP,
    RECURSION,
    SWEEP,
    SWEEP_NOP,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
```

In `tests/analysis/test_discover.py`, replace:
```python
    assert ex.issues == []


def test_the_sweep_never_reads_a_switch_table_as_code():
    ex = explore(program_space(HALFWORD_TABLE, thumb=True), [(0x080000C0, Mode.THUMB, "seed")],
                 sweep=True)
```
with:
```python
    assert ex.issues == []


def test_the_sweep_skips_the_nops_gnu_as_pads_with():
    ex = explore(program_space(SWEEP_NOP, thumb=True), [(0x080000C0, Mode.THUMB, "seed")],
                 sweep=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000CC: "neighbour"}
    assert ex.issues == []


def test_the_sweep_never_reads_a_switch_table_as_code():
    ex = explore(program_space(HALFWORD_TABLE, thumb=True), [(0x080000C0, Mode.THUMB, "seed")],
                 sweep=True)
```

In `tests/progkit.py`, replace:
```python
    pop {pc}
"""

# The ARM compiler's Thumb switch through a table of halfwords: offsets, in halfwords,
# from what the `add pc` reads as pc.
#   cc dispatch (reads pc as d0)   d0 table 3, 4, 5   d6 c0   d8 c1   da c2   dc dflt
```
with:
```python
    pop {pc}
"""

# GNU as pads Thumb code with nops (mov r8, r8) to align a literal pool: the function after
# the pool is found past them.
#   c0 main (loads c8)   c6 nop   c8 literal   cc next
SWEEP_NOP = """
main:
    movs r1, #0
    ldr r0, lit
    bx lr
    .hword 0x46c0
lit: .word 0x12345678
next:
    movs r0, #1
    bx lr
"""

# The ARM compiler's Thumb switch through a table of halfwords: offsets, in halfwords,
# from what the `add pc` reads as pc.
#   cc dispatch (reads pc as d0)   d0 table 3, 4, 5   d6 c0   d8 c1   da c2   dc dflt
```

In `tests/test_learn.py`, replace:
```python

from romtest import build_test_rom, run_program, run_rom

from gbaport.analysis.config import learned_path, load_learned, write_learned
from gbaport.cli import main
from gbaport.rom.image import RomImage
```
with:
```python

from romtest import build_test_rom, run_program, run_rom

import gbaport.learn as learning
from gbaport.analysis.config import learned_path, load_learned, write_learned
from gbaport.cli import main
from gbaport.rom.image import RomImage
```

In `tests/test_learn.py`, replace:
```python
    captured = capsys.readouterr()
    assert "learned 0x08100000 (Thumb)" in captured.out
    assert "has 0x08100000 already, but it is still missing" in captured.err


def test_learn_says_when_the_replay_cannot_run(tmp_path, monkeypatch, capsys):
```
with:
```python
    captured = capsys.readouterr()
    assert "learned 0x08100000 (Thumb)" in captured.out
    assert "has 0x08100000 already, but it is still missing" in captured.err
    assert "it is past the end of the ROM" in captured.err  # nothing there to recompile
    assert "0x08100000" not in learned_path("ATST").read_text(encoding="utf-8")  # not kept


def test_learn_says_when_the_replay_cannot_run(tmp_path, monkeypatch, capsys):
```

In `tests/test_learn.py`, replace:
```python
    assert main(["learn", "game.gba"]) == 1
    assert "the replay did not stop where the recorded play did (frame 20" in \
        capsys.readouterr().err
```
with:
```python
    assert main(["learn", "game.gba"]) == 1
    assert "the replay did not stop where the recorded play did (frame 20" in \
        capsys.readouterr().err


def test_a_replay_that_takes_too_long_says_so(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "hello")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    monkeypatch.setattr(learning, "REPLAY_TIMEOUT", 0.001)
    assert main(["learn", "game.gba"]) == 1
    assert "the replay took more than 0.001 s" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/analysis/test_discover.py tests/test_learn.py -k "gnu_as or takes_too_long or does_not_help"`
Expected: FAIL: 3 failed:
- the sweep finds only the seed;
- the "past the end of the ROM" hint is missing;
- `subprocess.TimeoutExpired` escapes.

- [ ] **Step 3: The fixes**

- **`discover.py`.** `THUMB_NOP = 0x46C0` ("mov r8, r8: what GNU as pads Thumb code with"). `_neighbours` skips halfwords that are 0 or `THUMB_NOP`.
- **`learn.py`, `_replay`.** Catches `subprocess.TimeoutExpired` and raises `LearnError(f"the replay took more than {REPLAY_TIMEOUT} s")`.
- **`learn.py`, an address learned already but still missing.** It is removed from its list and `learned.toml` written again, then: `LearnError(f"{learned} has 0x{addr:08x} already, but it is still missing: {_why_missing(addr, len(rom.data))} ({stopped})")`.
- **`_why_missing`.**
  - For RAM (regions 0x02, 0x03): "the game runs it from RAM: add a [[ram_code]] entry to game.toml for the ROM bytes it copies there".
  - For ROM regions 0x08–0x0D with `addr & 0x01FFFFFF >= rom_size`: "it is past the end of the ROM, so there is no code there: the game went somewhere it should not have (a recording made with another build can do that)".
  - Otherwise: "the analysis cannot decode code there".

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 968 passed (966 + 2).

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/learn.py src/gbaport/analysis/discover.py tests/test_learn.py tests/analysis/test_discover.py tests/progkit.py
git commit -m "fix: learn's replay timeout and the addresses learning cannot help; the sweep steps over Thumb nops"
```

---

### Task 6: The docs, and the user's game on the PC and the phone

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, `.gitignore`

- [ ] **Step 1: The README, the spec and `.gitignore`**

In `.gitignore`, replace:
```
roms/
*.gba
*.sav
games/*/generated/
build/

```
with:
```
roms/
*.gba
*.sav
# recordings of play the window and the phone make (key presses only)
*.session.input
games/*/generated/
build/

```

In `README.md`, replace:
```markdown
- A and B on the right (a finger between them holds both);
- L and R in the top corners, Select and Start at the bottom.

A gamepad works as on the desktop. Pressing one of its buttons hides the drawn ones, and
touching the screen brings them back. The back button leaves the app as the home button
does.

The save lives in the app's own storage. It is stored once a second while the game
changes it, when the game stops (the BIOS Stop call), when the app goes to the
```
with:
```markdown
- A and B on the right (a finger between them holds both);
- L and R in the top corners, Select and Start at the bottom.

A gamepad works as on the desktop. Pressing one of its buttons hides the drawn ones;
touching the screen, or the gamepad going away, brings them back. The back button leaves
the app as the home button does.

The save lives in the app's own storage. It is stored once a second while the game
changes it, when the game stops (the BIOS Stop call), when the app goes to the
```

In `README.md`, replace:
```markdown
background the game is paused. Uninstalling the app deletes its save.

What the game and the runtime print goes to Android's log, with the frame rate every ten
seconds:

    %LOCALAPPDATA%\gbaport\android-sdk\platform-tools\adb logcat -s gbaport

    59.73 frames a second; the game took 3.1 ms a frame

A runtime error, or one that stops the game from starting (a save file of the wrong
size), shows its message on the screen; the app ends when it is closed.
```
with:
```markdown
background the game is paused. Uninstalling the app deletes its save.

What the game and the runtime print goes to Android's log, with the frame rate every ten
seconds and where each frame's time went: running the game, drawing the picture, and
handing it to the screen (which can wait there for the display):

    %LOCALAPPDATA%\gbaport\android-sdk\platform-tools\adb logcat -s gbaport

    59.73 frames a second; the game took 2.6 ms a frame (running 1.20, drawing 0.22, showing 1.17)

A runtime error, or one that stops the game from starting (a save file of the wrong
size), shows its message on the screen; the app ends when it is closed.
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
data = [[0x08100000, 0x08180000]]           # ranges that are never code
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
scan_pointers = true           # guess entries from ROM words pointing at function starts

[[ram_code]]                   # blobs copied from ROM to RAM and executed there
rom = 0x080F0000
```
with:
```markdown
data = [[0x08100000, 0x08180000]]           # ranges that are never code
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
scan_pointers = true           # guess entries from ROM words pointing at function starts
sweep = true                   # guess the code that follows code (default false; Plan 7c)

[[ram_code]]                   # blobs copied from ROM to RAM and executed there
rom = 0x080F0000
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
GDB server while someone plays) live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
CpuSet is detected and needs a `[[ram_code]]` entry only when detection misses it.

## Verification strategy

```
with:
```markdown
GDB server while someone plays) live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
CpuSet is detected and needs a `[[ram_code]]` entry only when detection misses it.
`games/<game_code>/learned.toml`, which `gbaport learn` writes (the ROM's sha1 and the
entries it learned by replaying recorded play), is read together with `game.toml`.

## Verification strategy

```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 968 passed.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 3: The user's game on the phone**

This step needs the user's phone over USB. If it is not there, ledger that and carry on.

```bash
.venv/Scripts/python.exe -m gbaport.cli build roms/mygame.gba --host android --install --input games/BT4E/first-fight.input --out build/BT4E-android
```

After 80 seconds, run `adb logcat -d -s gbaport | grep "frames a second"`.
Expected: seven lines at 59.5 to 60.0 frames a second. In the fight (the third line on), running is about 4.3 to 5.3 ms (it was 6.9 to 8.5 before this plan) and showing about 4.5 to 5 ms. Record the lines in the ledger.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md .gitignore
git commit -m "docs: the phone's frame time, gamepads, sweep and learned.toml in the spec; recordings ignored"
```

---

## Done criteria for Plan 8b

- `.venv/Scripts/python.exe -m pytest` passes 968 tests and `.venv/Scripts/python.exe -m ruff check src tests` is clean.
- **The phone's frame-rate line** says where each frame's time goes.
- **The renderer:**
  - BT4E's 20000 frames headless take about 2.5 times less time;
  - the renderer tests and `verify` over 3600 frames are unchanged;
  - on the phone the fight's running time is about 35% lower.
- **The Android, build-tool, `learn` and sweep fixes** each pass the test that pins them.
