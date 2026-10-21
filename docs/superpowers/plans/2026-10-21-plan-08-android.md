# Plan 8: Android — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gbaport build ROM --host android --install` turns a game into an Android app and starts it on the phone connected over USB. The app fills the screen, held sideways, draws the GBA's buttons over the picture, takes a gamepad, keeps the save through the app being sent to the background or killed, and holds the GBA's 59.73 frames a second. Test ROMs prove all of it on gbaport's own Android emulator. The user's game runs at full speed into its first fight on the emulator and on the user's phone.

**Architecture:**
- **One host for the desktop and phones.** The spec's key decision 7 is "SDL3 platform layer ... so one host codebase serves all three". `host_sdl.c` gains a phone branch (`#if MOBILE`, set for SDL's Android platform):
  - **Screen and output.** It opens a full-screen window and lays out the picture and the buttons with the new `touch.c`. Its stdout and stderr go to logcat, tag `gbaport`.
  - **Files.** It reads the ROM from the app's assets with `SDL_LoadFile`, and keeps the save in the app's own storage (`SDL_GetPrefPath`).
  - **Lifecycle.** It stores the save when the app goes to the background. SDL passes those events to watchers only (`SDL_AddEventWatch`), on the game's thread.
  - **Status.** It prints the frame rate every ten seconds, and shows a runtime error in a message box before the app closes.
- **Touch controls (`runtime/touch.c`).** This is pure geometry and bookkeeping, with no SDL, tested on the desktop through `tests/touchhost.c`.
  - **Layout.** The picture is as large as the screen allows. The buttons keep to the safe area (clear of notches and system bars), sized by its height.
  - **Fingers.** A finger that comes down on the D-pad steers it wherever it moves; a finger between A and B holds both.
- **The app's project (`gbaport/native/android.py`, `android_template/`).** gbaport writes a Gradle project per game into `games/<code>/build/android`:
  - **What goes in.** The game's generated C, the runtime, SDL3's Java code, a `GameActivity` and the ROM as an uncompressed asset.
  - **How it builds.** CMake compiles the C and SDL3 from its source with the NDK into `libmain.so` and `libSDL3.so`. Gradle 8.12.1 with the Android Gradle plugin 8.7.3 (what SDL3 3.4.18's android-project uses) builds a debug-signed APK.
  - **What it needs.** Everything is fetched once into gbaport's cache folder, checked against its published digest: Google's command-line tools, then platform 35, build tools 35.0.0, NDK r29 and CMake 3.31.6 through their `sdkmanager` (which accepts Google's Android SDK licence: the user allowed this), Gradle, and SDL3's source.
- **Devices (`gbaport/native/device.py`).** It drives a phone or an emulator through the SDK's adb: install, start with options (the intent's `gbaport.args` extra), read the log, touch the screen, press keys, kill.
  - **The emulator.** `start_emulator` boots gbaport's own virtual device: 720x1280, Android 15, x86_64, the PC's graphics card, no window and no sound. It boots afresh each time, with no quick-boot snapshot, and `stop_emulator` waits until it has gone.
- **The command.** `gbaport build ROM --host android [--abi ABI] [--install [--input FILE]]` builds the app and, with `--install`, installs it on the one connected device (or `ANDROID_SERIAL`'s), builds it for that device's processor, and starts it, optionally playing an input file.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime, built with the NDK's clang for phones; SDL3 3.4.18 (zlib licence) built from source; Gradle 8.12.1 and the Android Gradle plugin 8.7.3 on the JDK 17 already installed; the Android emulator for the tests.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Roadmap row P8, verbatim: "P8 Android | Gradle/NDK project generated per game, touch overlay, controller, lifecycle, saves | APK runs on device at 60 fps; save survives app kill | P7".
  - "SDL3 platform layer for window, input, audio and app lifecycle on desktop, Android and iOS, so one host codebase serves all three." The phone code lives in `host_sdl.c`, not in a host of its own.
  - "Emulators are dev-time test oracles only." The Android emulator runs the tests and is never part of an app.
  - "No ROM-derived bytes in git." The ROM goes into the APK at build time, under `build/` (git ignores it). Test ROMs are built at test time.
  - Toolchain: "Android SDK + NDK r27 or newer". This plan uses NDK r29.
- **The user's decisions (2026-10-21):**
  - gbaport installs the Android SDK into its cache folder and accepts Google's Android SDK licence on the user's behalf, saying so when it does.
  - Automated tests run on the Android emulator. The 60 fps check also runs on the user's phone over USB.
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Never commit a `.gba` file: the user's ROMs stay untracked.
  - Tests never open a window and never play sound. The emulator runs with `-no-window -no-audio`.
- **Commands:**
  - Use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher.
  - Run `uv run pytest` and `uv run ruff check src tests` as separate commands.
  - Never run two test runs at once once Task 4 is in: both would drive the same emulator and app.
- **First runs:**
  - The first Android build downloads about 4 GB (needs a network connection) and compiles SDL3, which takes several minutes.
  - The emulator's first boot takes one to four minutes.

## Review Focus

1. **The app killed while the game waits in the BIOS Stop call.** Nothing stores the save once a second then, because no frames pass. The host stores it as the game stops. Pinned in Task 6 (`test_the_window_host_stores_the_save_when_the_game_stops`).
2. **A phone with a notch, a punch-hole camera or system bars.** The buttons stay inside the safe area while the picture still fills the screen's height. Pinned in Task 1 (`test_the_buttons_are_inside_the_safe_area`).
3. **More than ten fingers.** The extra ones hold nothing, and their coming up changes nothing. Pinned in Task 1 (`test_an_eleventh_finger_holds_nothing_and_its_coming_up_changes_nothing`).
4. **A runtime error on the phone.** It waits on the screen instead of the app vanishing. Pinned in Task 4 (`test_a_runtime_error_is_printed_and_shown_until_it_is_read`).
5. **An input file saved by a Windows editor** (a byte order mark, CRLF line ends), played on the device. Pinned in Task 7 (`test_build_has_the_game_play_an_input_file_on_the_device`).

## Known limitations (deliberate; later plans)

- **Coverage is what was played (Plan 7b's limitation, on every host).**
  - The user's game plays into its first fight. About a second after `first-fight.input` ends (frame 4300), it stops at `no recompiled code at 0x08009e0e (Thumb state, lr = 0x08009d23)`. On the phone, that error shows on the screen.
  - In the prototype, a trace of 40000 frames of scripted fighting added 235 hits, and the game then played to frame 12826 before the next miss. That miss is a call from code in EWRAM.
  - Playing on needs more coverage: longer traces, the GDB recorder, or a loop that learns misses. That is the next plan's work.
- **No virtual gamepad on the emulator.** The gamepad code is the desktop host's. Hiding the drawn buttons when a gamepad button is pressed is checked by hand on the phone.
- **Sideways only** (`sensorLandscape`). A portrait layout is later work.
- **90 and 120 Hz screens.** The host paces frames by the clock at 59.73 a second. A 120 Hz screen shows each frame twice; a 90 Hz screen shows them unevenly.
- **Debug-signed APKs for this machine's phones,** arm64-v8a and x86_64 only: no 32-bit or x86 phones, and nothing for a store.
- **The back button** leaves the app as the home button does. That is Android 12's behaviour for an app's first activity.
- **The emulator needs Windows Hypervisor Platform and a graphics card it can use.** In the prototype, its software renderer at 2400x1080 drew 11 frames a second. The tests use the PC's graphics card at 720x1280.

---

### Task 1: The buttons on a touch screen, as geometry

`runtime/touch.c` lays out a phone's screen and follows the fingers on it. It has no SDL in it, so the desktop tests run it through a small C program, `tests/touchhost.c`. That program reads commands (`layout`, `down`, `move`, `up`, `keys`) and prints boxes and keys.
- **The picture** is as large as the whole screen allows, in its middle.
- **The buttons** keep to the safe area, sized by its height `u`:
  - the D-pad, a circle of radius 0.18u on the left;
  - A and B on the right, circles of radius 0.09u. Their boxes reach 1.4 radii, so a finger between them holds both;
  - L and R in the top corners; Select and Start at the bottom in the middle.
- **The D-pad.** A finger that comes down within 1.4 radii of its centre steers it wherever the finger moves. Each direction covers 135 degrees, so the diagonals hold two keys, and the middle fifth holds none.
- **Fingers.** Ten at most are followed; others hold nothing.

**Files:**
- Create: `src/gbaport/runtime/touch.h`, `src/gbaport/runtime/touch.c`
- Create: `tests/touchhost.c`
- Test: `tests/runtime/test_touch.py`

**Interfaces:**
- Consumes: `gbaport.native.build`'s `RUNTIME` and `SALTED_REBUILDS`, and its `_starts` (Smart App Control check); `gbaport.native.toolchain.find_clang`.
- **Produces** (`touch.h`), used by `host_sdl.c` from Task 4 on:
  - **Types:** `TouchBox {float x, y, w, h}`. `enum {TOUCH_A, TOUCH_B, TOUCH_SELECT, TOUCH_START, TOUCH_R, TOUCH_L, TOUCH_BUTTONS}`. `TouchLayout {TouchBox screen; float pad_x, pad_y, pad_radius; TouchBox buttons[TOUCH_BUTTONS];}`. `TouchState {TouchLayout layout; TouchFinger fingers[10]; int count;}`.
  - **Functions:** `void touch_layout(TouchLayout *, float width, float height, TouchBox safe)`. `void touch_down(TouchState *, uint64_t id, float x, float y)`, and `touch_move` with the same arguments. `void touch_up(TouchState *, uint64_t id)`. `uint16_t touch_keys(const TouchState *)`, in GBA key bits.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-08-android
```

- [ ] **Step 2: Write the failing tests and the test program**

Create `tests/runtime/test_touch.py`:
```python
"""The buttons drawn on a phone's screen (runtime/touch.c), through tests/touchhost.c."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

import gbaport.native.build as native
from gbaport.native.toolchain import find_clang

HOST = Path(__file__).parent.parent / "touchhost.c"
SOURCES = (HOST, native.RUNTIME / "touch.c", native.RUNTIME / "touch.h")
PHONE = "layout 2400 1080 0 0 2400 1080"  # a 20:9 phone held sideways, no notch


def _program() -> Path:
    """touchhost, built once per version of its sources (rebuilt with a salt when Windows'
    Smart App Control refuses to start it, as gbaport build does)."""
    digest = hashlib.sha1(b"".join(path.read_bytes() for path in SOURCES)).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / "gbaport-touchhost" / digest
    program = folder / ("touchhost.exe" if os.name == "nt" else "touchhost")
    if program.exists():
        return program
    folder.mkdir(parents=True, exist_ok=True)
    salt = folder / "salt.c"
    for _ in range(native.SALTED_REBUILDS):
        salt.write_text(f'const char touchhost_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        subprocess.run(
            [find_clang(), "-std=c11", "-O2", "-Wall", "-Werror", f"-I{native.RUNTIME}", str(HOST),
             str(native.RUNTIME / "touch.c"), str(salt), "-o", str(program)],
            check=True, capture_output=True,
        )
        if native._starts(program):
            return program
    raise AssertionError("Windows refused to start touchhost")


def touch(*commands: str) -> list[str]:
    result = subprocess.run([str(_program())], input="\n".join(commands) + "\n",
                            capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.splitlines()


def layout(command: str = PHONE) -> dict[str, list[float]]:
    return {line.split()[0]: [float(v) for v in line.split()[1:]] for line in touch(command)}


def centre(box: list[float]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2, y + h / 2


def test_the_picture_fills_the_screens_height_in_the_middle():
    assert layout()["screen"] == [390.0, 0.0, 1620.0, 1080.0]


def test_the_buttons_are_inside_the_safe_area():
    boxes = layout("layout 2400 1080 100 40 2200 1000")  # a notch on each side, bars above and below
    for name in ("A", "B", "SELECT", "START", "R", "L"):
        x, y, w, h = boxes[name]
        assert 100 <= x and x + w <= 2300 and 40 <= y and y + h <= 1040, name
    pad_x, pad_y, radius = boxes["pad"]
    assert 100 <= pad_x - radius and pad_y + radius <= 1040
    assert boxes["screen"] == [390.0, 0.0, 1620.0, 1080.0]  # the picture still fills the height


def test_a_finger_on_a_button_holds_its_key_until_it_comes_up():
    ax, ay = centre(layout()["A"])
    assert touch(PHONE, f"down 1 {ax} {ay}", "keys", "up 1", "keys")[-2:] == ["A", "none"]


@pytest.mark.parametrize("dx, dy, keys", [
    (1, 0, "RIGHT"), (-1, 0, "LEFT"), (0, -1, "UP"), (0, 1, "DOWN"),
    (0.7, -0.7, "RIGHT+UP"), (-0.7, 0.7, "LEFT+DOWN"), (0.05, 0.05, "none"),
])
def test_the_d_pad_points_where_the_finger_is(dx, dy, keys):
    x, y, radius = layout()["pad"]
    finger = f"down 7 {x + dx * 0.8 * radius} {y + dy * 0.8 * radius}"
    assert touch(PHONE, finger, "keys")[-1] == keys


def test_a_finger_that_came_down_on_the_d_pad_keeps_steering_it_beyond_its_edge():
    x, y, radius = layout()["pad"]
    out = touch(PHONE, f"down 1 {x} {y - 0.5 * radius}", f"move 1 {x + 3 * radius} {y}", "keys")
    assert out[-1] == "RIGHT"


def test_a_finger_that_came_down_elsewhere_does_not_steer_the_d_pad():
    boxes = layout()
    x, y, radius = boxes["pad"]
    sx, sy = centre(boxes["START"])
    assert touch(PHONE, f"down 1 {sx} {sy}", f"move 1 {x + 0.8 * radius} {y}", "keys")[-1] == "none"


def test_a_finger_between_a_and_b_holds_both():
    (ax, ay), (bx, by) = centre(layout()["A"]), centre(layout()["B"])
    assert touch(PHONE, f"down 1 {(ax + bx) / 2} {(ay + by) / 2}", "keys")[-1] == "A+B"


def test_a_finger_sliding_from_b_to_a_moves_the_press():
    (ax, ay), (bx, by) = centre(layout()["A"]), centre(layout()["B"])
    assert touch(PHONE, f"down 1 {bx} {by}", f"move 1 {ax} {ay}", "keys")[-1] == "A"


def test_fingers_add_up():
    boxes = layout()
    x, y, radius = boxes["pad"]
    lx, ly = centre(boxes["L"])
    ax, ay = centre(boxes["A"])
    out = touch(PHONE, f"down 1 {x + 0.8 * radius} {y}", f"down 2 {lx} {ly}", f"down 3 {ax} {ay}",
                "keys", "up 2", "keys")
    assert out[-2:] == ["A+RIGHT+L", "A+RIGHT"]


def test_an_eleventh_finger_holds_nothing_and_its_coming_up_changes_nothing():
    boxes = layout()
    ax, ay = centre(boxes["A"])
    sx, sy = centre(boxes["START"])
    resting = [f"down {i} 1200 540" for i in range(10)]  # ten fingers on the picture
    out = touch(PHONE, *resting, f"down 10 {sx} {sy}", "keys", "up 10", "up 3",
                f"down 11 {ax} {ay}", "keys")
    assert out[-2:] == ["none", "A"]
```

Create `tests/touchhost.c`:
```c
/* touchhost.c - runs runtime/touch.c for tests/runtime/test_touch.py. Reads commands,
 * one a line, and prints what they ask for:
 *
 *     layout W H SX SY SW SH   lay out a W x H screen whose safe area is SX SY SW SH;
 *                              prints the picture's box, the D-pad and each button's box
 *     down ID X Y | move ID X Y | up ID
 *     keys                     prints the keys held, "A+RIGHT" or "none"
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <string.h>

#include "touch.h"

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};
static const char *const BUTTON_NAMES[TOUCH_BUTTONS] = {"A", "B", "SELECT", "START", "R", "L"};

int main(void)
{
    static TouchState touch;
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        char command[16];
        unsigned long long id;
        float a, b, c, d, e, f;
        if (sscanf(line, "%15s", command) != 1)
            continue;
        if (strcmp(command, "layout") == 0 &&
            sscanf(line, "%*s %f %f %f %f %f %f", &a, &b, &c, &d, &e, &f) == 6) {
            touch_layout(&touch.layout, a, b, (TouchBox){c, d, e, f});
            const TouchLayout *l = &touch.layout;
            printf("screen %.1f %.1f %.1f %.1f\n", l->screen.x, l->screen.y, l->screen.w, l->screen.h);
            printf("pad %.1f %.1f %.1f\n", l->pad_x, l->pad_y, l->pad_radius);
            for (int i = 0; i < TOUCH_BUTTONS; i++)
                printf("%s %.1f %.1f %.1f %.1f\n", BUTTON_NAMES[i], l->buttons[i].x,
                       l->buttons[i].y, l->buttons[i].w, l->buttons[i].h);
        } else if (strcmp(command, "down") == 0 && sscanf(line, "%*s %llu %f %f", &id, &a, &b) == 3) {
            touch_down(&touch, id, a, b);
        } else if (strcmp(command, "move") == 0 && sscanf(line, "%*s %llu %f %f", &id, &a, &b) == 3) {
            touch_move(&touch, id, a, b);
        } else if (strcmp(command, "up") == 0 && sscanf(line, "%*s %llu", &id) == 1) {
            touch_up(&touch, id);
        } else if (strcmp(command, "keys") == 0) {
            unsigned keys = touch_keys(&touch);
            int first = 1;
            for (int k = 0; k < 10; k++)
                if (keys >> k & 1) {
                    printf("%s%s", first ? "" : "+", KEY_NAMES[k]);
                    first = 0;
                }
            printf("%s\n", first ? "none" : "");
        } else {
            printf("bad command: %s", line);
            return 1;
        }
    }
    return 0;
}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_touch.py`
Expected: FAIL: 16 failed, each with `FileNotFoundError` for `src\gbaport\runtime\touch.c`. The test program is cached by its sources' hash, and `touch.c` does not exist yet.

- [ ] **Step 4: The layout and the fingers**

Create `src/gbaport/runtime/touch.c`:
```c
/* touch.c - see touch.h. The picture is as large as the whole screen allows, in its
 * middle. The buttons keep to the safe area and their sizes follow its height `u`: the
 * D-pad on the left, A and B on the right, L and R in the top corners, Select and Start
 * at the bottom in the middle. On a screen wider than the picture they sit beside it;
 * on a narrower one they are drawn over it. A finger between A and B holds both. */
#include "touch.h"

#include <math.h>

static const uint16_t BUTTON_KEYS[TOUCH_BUTTONS] = {
    1u << 0, 1u << 1, 1u << 2, 1u << 3, 1u << 8, 1u << 9,  /* A B SELECT START R L */
};
enum { RIGHT = 1u << 4, LEFT = 1u << 5, UP = 1u << 6, DOWN = 1u << 7 };

#define A_B_REACH 1.4f  /* a round button's box reaches this many radii from its centre */

static TouchBox around(float x, float y, float radius)
{
    float reach = radius * A_B_REACH;
    return (TouchBox){x - reach, y - reach, 2 * reach, 2 * reach};
}

void touch_layout(TouchLayout *layout, float width, float height, TouchBox safe)
{
    float u = safe.h, right = safe.x + safe.w, bottom = safe.y + safe.h;
    float scale = fminf(width / 240, height / 160);
    layout->screen = (TouchBox){(width - 240 * scale) / 2, (height - 160 * scale) / 2,
                                240 * scale, 160 * scale};
    layout->pad_radius = 0.18f * u;
    layout->pad_x = safe.x + 0.05f * u + layout->pad_radius;
    layout->pad_y = safe.y + 0.60f * u;
    float round = 0.09f * u, ax = right - 0.05f * u - round, ay = safe.y + 0.52f * u;
    layout->buttons[TOUCH_A] = around(ax, ay, round);
    layout->buttons[TOUCH_B] = around(ax - 0.22f * u, ay + 0.12f * u, round);
    float middle = safe.x + safe.w / 2;
    layout->buttons[TOUCH_SELECT] = (TouchBox){middle - 0.19f * u, bottom - 0.10f * u, 0.17f * u, 0.08f * u};
    layout->buttons[TOUCH_START] = (TouchBox){middle + 0.02f * u, bottom - 0.10f * u, 0.17f * u, 0.08f * u};
    layout->buttons[TOUCH_R] = (TouchBox){right - 0.30f * u, safe.y, 0.30f * u, 0.13f * u};
    layout->buttons[TOUCH_L] = (TouchBox){safe.x, safe.y, 0.30f * u, 0.13f * u};
}

static int inside(TouchBox box, float x, float y)
{
    return x >= box.x && x < box.x + box.w && y >= box.y && y < box.y + box.h;
}

/* A finger on the D-pad points at up to two directions: each covers 135 degrees, so the
 * diagonals between them hold both; near the centre it points at none. */
static uint16_t pad_keys(const TouchLayout *layout, float x, float y)
{
    float dx = x - layout->pad_x, dy = y - layout->pad_y, distance = hypotf(dx, dy);
    if (distance < 0.2f * layout->pad_radius)
        return 0;
    float lean = 0.38f * distance;  /* cos(67.5 degrees) */
    return (uint16_t)((dx > lean ? RIGHT : 0) | (dx < -lean ? LEFT : 0) |
                      (dy < -lean ? UP : 0) | (dy > lean ? DOWN : 0));
}

static uint16_t finger_keys(const TouchLayout *layout, const TouchFinger *finger)
{
    if (finger->on_pad)
        return pad_keys(layout, finger->x, finger->y);
    uint16_t keys = 0;
    for (int b = 0; b < TOUCH_BUTTONS; b++)
        if (inside(layout->buttons[b], finger->x, finger->y))
            keys |= BUTTON_KEYS[b];
    return keys;
}

static TouchFinger *find(TouchState *touch, uint64_t id)
{
    for (int i = 0; i < touch->count; i++)
        if (touch->fingers[i].id == id)
            return &touch->fingers[i];
    return 0;
}

void touch_down(TouchState *touch, uint64_t id, float x, float y)
{
    TouchFinger *finger = find(touch, id);
    if (!finger) {
        if (touch->count == TOUCH_FINGERS)
            return;  /* more fingers than anyone needs: the extra ones hold nothing */
        finger = &touch->fingers[touch->count++];
    }
    const TouchLayout *layout = &touch->layout;
    float distance = hypotf(x - layout->pad_x, y - layout->pad_y);
    *finger = (TouchFinger){id, x, y, distance < 1.4f * layout->pad_radius};
}

void touch_move(TouchState *touch, uint64_t id, float x, float y)
{
    TouchFinger *finger = find(touch, id);
    if (finger) {
        finger->x = x;
        finger->y = y;
    }
}

void touch_up(TouchState *touch, uint64_t id)
{
    TouchFinger *finger = find(touch, id);
    if (finger)
        *finger = touch->fingers[--touch->count];
}

uint16_t touch_keys(const TouchState *touch)
{
    uint16_t keys = 0;
    for (int i = 0; i < touch->count; i++)
        keys |= finger_keys(&touch->layout, &touch->fingers[i]);
    return keys;
}
```

Create `src/gbaport/runtime/touch.h`:
```c
/* touch.h - the GBA's buttons drawn on a touch screen, and the keys the fingers on them
 * hold. Only geometry and bookkeeping: host_sdl.c draws the buttons and passes the
 * fingers on. Sizes are in pixels; the layout is made for a screen held sideways. */
#ifndef TOUCH_H
#define TOUCH_H

#include <stdint.h>

typedef struct {
    float x, y, w, h;
} TouchBox;

/* The buttons besides the D-pad. */
enum { TOUCH_A, TOUCH_B, TOUCH_SELECT, TOUCH_START, TOUCH_R, TOUCH_L, TOUCH_BUTTONS };

typedef struct {
    TouchBox screen;                  /* where the GBA picture goes */
    float pad_x, pad_y, pad_radius;   /* the D-pad, a circle */
    TouchBox buttons[TOUCH_BUTTONS];  /* A and B are drawn as the circles inside theirs */
} TouchLayout;

enum { TOUCH_FINGERS = 10 };

typedef struct {
    uint64_t id;
    float x, y;
    int on_pad;  /* it came down on the D-pad: it steers the D-pad wherever it moves */
} TouchFinger;

typedef struct {
    TouchLayout layout;
    TouchFinger fingers[TOUCH_FINGERS];
    int count;
} TouchState;

/* Lays the picture and the buttons out on a `width` x `height` screen whose `safe` part
 * is clear of notches and system bars. */
void touch_layout(TouchLayout *layout, float width, float height, TouchBox safe);
void touch_down(TouchState *touch, uint64_t id, float x, float y);
void touch_move(TouchState *touch, uint64_t id, float x, float y);
void touch_up(TouchState *touch, uint64_t id);
/* The GBA keys the fingers hold (GBA key bits, 1 = pressed). */
uint16_t touch_keys(const TouchState *touch);

#endif
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: 898 passed (882 + 16).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/runtime/touch.h src/gbaport/runtime/touch.c tests/touchhost.c tests/runtime/test_touch.py
git commit -m "feat: the GBA's buttons on a touch screen: their layout and the fingers on them"
```

---

### Task 2: What an Android app is built with, fetched into the cache

`gbaport/native/android.py` gets what the app needs into gbaport's cache folder (`%LOCALAPPDATA%\gbaport`, or `GBAPORT_CACHE`) the first time it is needed:
- **`android_sdk()`** downloads Google's command-line tools 23.0 and checks the SHA-1 Google's repository lists. It unpacks them as `android-sdk/cmdline-tools/latest`, then installs the platform, build tools, NDK and CMake with `sdkmanager`.
  - **The package names** go to `sdkmanager --package_file`. On Windows a `.bat` file's arguments cannot hold the `;` in them.
  - **Licences.** It answers "y" to each licence and says that this accepts Google's Android SDK licence. A package that does not install is named in the error.
- **`gradle()`** downloads Gradle 8.12.1 and checks its published SHA-256.
- **`sdl3_source()`** downloads SDL3 3.4.18's source release, with the SHA-256 the SDL3 build already pins.
- **Downloads.** Each one goes to a `.partial` file first and is unpacked under a name of its own, so an interrupted one leaves nothing that looks installed. Zip archives keep their files' permissions, so `sdkmanager` and `gradle` stay executable outside Windows.

The tests use stand-ins: an `sdkmanager` that installs whatever it is asked for at once, and local files for the downloads. The prototype installed the real ones into the cache: 7.6 GB with the emulator.

**Files:**
- Create: `src/gbaport/native/android.py`
- Test: `tests/test_android.py`

**Interfaces:**
- Consumes: `gbaport.native.sdl3`'s `cache_folder()`, `SDL3_VERSION`, `SDL3_URL`, `SDL3_SHA256`; `gbaport.native.toolchain.ToolchainError`.
- **Produces** (`gbaport.native.android`):
  - **Pinned versions:** `PLATFORM = 35`, `BUILD_TOOLS = "35.0.0"`, `NDK = "29.0.14206865"`, `CMAKE = "3.31.6"`, `GRADLE_VERSION = "8.12.1"`, `SDK_PACKAGES`.
  - **Functions:** `android_sdk(log=print) -> Path`, `installed(sdk, package) -> bool`, `install_packages(sdk, packages, log=print)`, `java_environment() -> dict[str, str]`, `gradle(log=print) -> Path`, `sdl3_source(log=print) -> Path`, `_download(url, path, digest, kind="sha256") -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_android.py`:
```python
"""What a game's Android app is built with (gbaport/native/android.py), without Google's
servers: a stand-in sdkmanager and local files for the downloads."""

import hashlib
import io
import os
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

from gbaport.native import android
from gbaport.native.toolchain import ToolchainError

FAKE_SDKMANAGER = textwrap.dedent("""\
    import sys
    from pathlib import Path
    args = dict(a.split("=", 1) for a in sys.argv[1:])
    sdk = Path(args["--sdk_root"])
    answers = sys.stdin.read().split()
    with open(sdk / "calls.txt", "a", encoding="utf-8") as calls:
        calls.write(f"{len(answers)} answers:")
        for package in Path(args["--package_file"]).read_text(encoding="utf-8").split():
            calls.write(" " + package)
            if "broken" not in package:
                folder = sdk.joinpath(*package.split(";"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "source.properties").write_text("Pkg.Revision=1\\n", encoding="utf-8")
        calls.write("\\n")
""")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


def fake_sdk(cache: Path) -> Path:
    """An SDK folder whose sdkmanager installs whatever it is asked for, at once."""
    tools = cache / "android-sdk" / "cmdline-tools" / "latest" / "bin"
    tools.mkdir(parents=True)
    script = tools / "fake_sdkmanager.py"
    script.write_text(FAKE_SDKMANAGER, encoding="utf-8")
    if os.name == "nt":
        (tools / "sdkmanager.bat").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tools / "sdkmanager"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return cache / "android-sdk"


def quiet(_: str) -> None:
    pass


def test_the_sdk_packages_gbaport_needs_are_installed_once(cache):
    sdk = fake_sdk(cache)
    assert android.android_sdk(log=quiet) == sdk
    android.android_sdk(log=quiet)  # all there now: sdkmanager does not run again
    calls = (sdk / "calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls == ["50 answers: " + " ".join(android.SDK_PACKAGES)]  # "y" to every licence
    assert (sdk / "ndk" / android.NDK / "source.properties").exists()
    assert not (sdk / "packages.txt").exists()


def test_installing_says_it_accepts_googles_licence(cache):
    fake_sdk(cache)
    said = []
    android.android_sdk(log=said.append)
    assert len(said) == 1 and "accepts Google's Android SDK licence" in said[0]


def test_a_package_that_does_not_install_is_named(cache, monkeypatch):
    fake_sdk(cache)
    monkeypatch.setattr(android, "SDK_PACKAGES", ("platform-tools", "broken;1"))
    with pytest.raises(ToolchainError, match=r"installing broken;1 failed"):
        android.android_sdk(log=quiet)


def test_a_download_must_match_its_published_digest(tmp_path):
    source = tmp_path / "file.zip"
    source.write_bytes(b"published bytes")
    digest = hashlib.sha256(b"published bytes").hexdigest()
    target = tmp_path / "downloads" / "file.zip"
    assert android._download(source.as_uri(), target, digest) == target
    assert target.read_bytes() == b"published bytes"
    with pytest.raises(ToolchainError, match="did not download as published"):
        android._download(source.as_uri(), tmp_path / "other.zip", "0" * 64)
    assert not (tmp_path / "other.zip").exists()
    assert not (tmp_path / "other.zip.partial").exists()


def test_a_download_that_fails_says_what_it_was(tmp_path):
    with pytest.raises(ToolchainError, match="cannot download"):
        android._download((tmp_path / "nothing.zip").as_uri(), tmp_path / "x.zip", "0" * 64)
    assert not (tmp_path / "x.zip.partial").exists()


def test_gradle_and_sdl3s_source_come_unpacked_into_the_cache(cache, monkeypatch, tmp_path):
    gradle_zip = io.BytesIO()
    with zipfile.ZipFile(gradle_zip, "w") as zipped:
        zipped.writestr(f"gradle-{android.GRADLE_VERSION}/bin/gradle", "#!/bin/sh\n")
        zipped.writestr(f"gradle-{android.GRADLE_VERSION}/bin/gradle.bat", "@echo off\n")
    sdl_tar = io.BytesIO()
    with tarfile.open(fileobj=sdl_tar, mode="w:gz") as packed:
        data = b"project(SDL3)\n"
        info = tarfile.TarInfo(f"SDL3-{android.SDL3_VERSION}/CMakeLists.txt")
        info.size = len(data)
        packed.addfile(info, io.BytesIO(data))
    published = {}
    for name, blob in (("gradle.zip", gradle_zip.getvalue()), ("sdl.tar.gz", sdl_tar.getvalue())):
        (tmp_path / name).write_bytes(blob)
        published[name] = ((tmp_path / name).as_uri(), hashlib.sha256(blob).hexdigest())
    monkeypatch.setattr(android, "GRADLE_URL", published["gradle.zip"][0])
    monkeypatch.setattr(android, "GRADLE_SHA256", published["gradle.zip"][1])
    monkeypatch.setattr(android, "SDL3_URL", published["sdl.tar.gz"][0])
    monkeypatch.setattr(android, "SDL3_SHA256", published["sdl.tar.gz"][1])
    program = android.gradle(log=quiet)
    assert program.parent == cache / f"gradle-{android.GRADLE_VERSION}" / "bin" and program.exists()
    source = android.sdl3_source(log=quiet)
    assert (source / "CMakeLists.txt").read_text(encoding="utf-8") == "project(SDL3)\n"
    assert sorted(p.name for p in cache.iterdir()) == [
        f"gradle-{android.GRADLE_VERSION}", f"sdl3-{android.SDL3_VERSION}-source"]  # no archives left
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_android.py`
Expected: FAIL: 1 error during collection, `ImportError: cannot import name 'android' from 'gbaport.native'`.

- [ ] **Step 3: The SDK, Gradle and SDL3's source**

Create `src/gbaport/native/android.py`:
```python
"""Android: what a game's app is built with, fetched once into the cache folder.

- **The Android SDK** (``android_sdk``): Google's command-line tools, then the platform,
  build tools, NDK and CMake that the app needs, installed with their ``sdkmanager``.
  Installing them accepts Google's Android SDK licence, which gbaport says when it does.
- **Gradle** (``gradle``), which builds the app; it runs on a JDK 17 or newer
  (``java_environment``).
- **SDL3's source** (``sdl3_source``): the app builds SDL3 from it and takes SDL's Java
  code for its activity.

Each download is checked against the digest its publisher lists and unpacked under a
name of its own first, so an interrupted one leaves nothing that looks installed.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from gbaport.native.sdl3 import SDL3_SHA256, SDL3_URL, SDL3_VERSION, cache_folder
from gbaport.native.toolchain import ToolchainError

GRADLE_VERSION = "8.12.1"  # with the Android Gradle plugin 8.7.3, as SDL3's android-project
GRADLE_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
GRADLE_SHA256 = "8d97a97984f6cbd2b85fe4c60a743440a347544bf18818048e611f5288d46c94"
PLATFORM = 35
BUILD_TOOLS = "35.0.0"
NDK = "29.0.14206865"  # r29
CMAKE = "3.31.6"
SDK_PACKAGES = (
    "platform-tools", f"platforms;android-{PLATFORM}", f"build-tools;{BUILD_TOOLS}",
    f"ndk;{NDK}", f"cmake;{CMAKE}",
)
REPOSITORY = "https://dl.google.com/android/repository/"
COMMAND_LINE_TOOLS = {  # version 23.0: archive and SHA-1, as Google's repository lists them
    "win32": ("commandlinetools-win-16111833_latest.zip", "57d04f2d75eb8e8fffc5000a987e5de4b5a63e9d"),
    "linux": ("commandlinetools-linux-16111833_latest.zip", "e025545c62a8e64c7559119566a569fb1dec5f60"),
    "darwin": ("commandlinetools-mac_arm64-16111833_latest.zip", "ad03dc49bfacfd52c110b14104ea548b8a07e830"),
}
LICENCE = "https://developer.android.com/studio/terms"

Log = Callable[[str], None]


def android_sdk(log: Log = print) -> Path:
    """The SDK folder, with the packages gbaport needs (installed the first time)."""
    sdk = cache_folder() / "android-sdk"
    if not _sdkmanager(sdk).exists():
        name, sha1 = COMMAND_LINE_TOOLS[sys.platform]
        log(f"downloading Google's Android command-line tools into {sdk}")
        archive = _download(REPOSITORY + name, sdk / name, sha1, "sha1")
        _unpack(archive, "cmdline-tools", sdk / "cmdline-tools" / "latest")
    missing = [p for p in SDK_PACKAGES if not installed(sdk, p)]
    if missing:
        install_packages(sdk, missing, log)
    return sdk


def installed(sdk: Path, package: str) -> bool:
    return (sdk.joinpath(*package.split(";")) / "source.properties").exists()


def install_packages(sdk: Path, packages: list[str], log: Log = print) -> None:
    """Installs ``packages`` with the SDK's sdkmanager, saying yes to their licences."""
    log(f"installing {', '.join(packages)} into {sdk}; this accepts Google's Android SDK "
        f"licence ({LICENCE})")
    listing = sdk / "packages.txt"  # a .bat file's arguments cannot hold the ';' in the names
    listing.write_text("\n".join(packages) + "\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [str(_sdkmanager(sdk)), f"--sdk_root={sdk}", f"--package_file={listing}"],
            input="y\n" * 50, capture_output=True, text=True, env=java_environment(), check=False,
        )
    finally:
        listing.unlink()
    missing = [p for p in packages if not installed(sdk, p)]
    if result.returncode != 0 or missing:
        raise ToolchainError(f"installing {', '.join(missing or packages)} failed:\n"
                             f"{(result.stdout + result.stderr)[-4000:]}")


def _sdkmanager(sdk: Path) -> Path:
    name = "sdkmanager.bat" if os.name == "nt" else "sdkmanager"
    return sdk / "cmdline-tools" / "latest" / "bin" / name


def java_environment() -> dict[str, str]:
    """The environment with JAVA_HOME set, which Gradle and the SDK's tools need."""
    env = dict(os.environ)
    if not env.get("JAVA_HOME"):
        java = shutil.which("java")
        if not java:
            raise ToolchainError("Java not found: Gradle and the Android SDK need a JDK 17 or "
                                 "newer (winget install EclipseAdoptium.Temurin.17.JDK)")
        env["JAVA_HOME"] = str(Path(java).resolve().parent.parent)
    return env


def gradle(log: Log = print) -> Path:
    """Gradle's launcher (downloaded the first time)."""
    home = cache_folder() / f"gradle-{GRADLE_VERSION}"
    program = home / "bin" / ("gradle.bat" if os.name == "nt" else "gradle")
    if not program.exists():
        log(f"downloading Gradle {GRADLE_VERSION} into {home}")
        archive = _download(GRADLE_URL, cache_folder() / f"gradle-{GRADLE_VERSION}-bin.zip",
                            GRADLE_SHA256)
        _unpack(archive, f"gradle-{GRADLE_VERSION}", home)
    return program


def sdl3_source(log: Log = print) -> Path:
    """SDL3's source release (downloaded the first time)."""
    folder = cache_folder() / f"sdl3-{SDL3_VERSION}-source"
    if not (folder / "CMakeLists.txt").exists():
        log(f"downloading SDL3 {SDL3_VERSION}'s source into {folder}")
        archive = _download(SDL3_URL, cache_folder() / f"SDL3-{SDL3_VERSION}.tar.gz", SDL3_SHA256)
        _unpack(archive, f"SDL3-{SDL3_VERSION}", folder)
    return folder


def _download(url: str, path: Path, digest: str, kind: str = "sha256") -> Path:
    """``url`` saved as ``path``, if its bytes have the published ``digest``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    hasher = hashlib.new(kind)
    try:
        with urllib.request.urlopen(url) as response, open(partial, "wb") as out:
            while chunk := response.read(1 << 20):
                hasher.update(chunk)
                out.write(chunk)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise ToolchainError(f"cannot download {url}: {error}") from error
    if hasher.hexdigest() != digest:
        partial.unlink()
        raise ToolchainError(f"{url} did not download as published ({kind} {hasher.hexdigest()})")
    partial.replace(path)
    return path


def _unpack(archive: Path, top: str, target: Path) -> None:
    """Unpacks ``archive``'s folder ``top`` as ``target``, then deletes the archive."""
    staging = target.with_name(target.name + "-unpacking")
    shutil.rmtree(staging, ignore_errors=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(staging)
            for info in zipped.infolist():  # zipfile drops the permissions: keep +x
                if info.external_attr >> 16 and os.name != "nt":
                    (staging / info.filename).chmod(info.external_attr >> 16)
    else:
        with tarfile.open(archive) as packed:
            packed.extractall(staging, filter="data")
    shutil.rmtree(target, ignore_errors=True)
    (staging / top).replace(target)
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink()
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 904 passed (898 + 6).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Fetch the real ones**

This is the first network use; it takes some minutes (about 3.5 GB):

```bash
uv run python -c "from gbaport.native import android; print(android.android_sdk(), android.gradle(), android.sdl3_source(), sep='\n')"
```

Expected: the licence line (unless an earlier run installed them), then the three folders under `%LOCALAPPDATA%\gbaport`.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/native/android.py tests/test_android.py
git commit -m "feat: the Android SDK, Gradle and SDL3's source, fetched once into the cache"
```

---

### Task 3: The game's Android project, and its APK

`android_project(sources, rom, out, game_code, label, abis, sdl, sdk)` writes a Gradle project from `gbaport/native/android_template`:
- **What goes in:**
  - the game's generated C (`app/src/main/cpp/generated`);
  - the runtime's sources (`cpp/runtime`);
  - SDL3's Java code and launcher icons, taken from its source;
  - `GameActivity` and the ROM as `assets/game.gba`.
- **`CMakeLists.txt`** builds SDL3 from its source (`add_subdirectory`) and `libmain.so` from the game, the runtime, `host_common.c`, `host_sdl.c` and `touch.c`, with gbaport's `CFLAGS`.
- **`app/build.gradle`:**
  - the application ID `org.gbaport.<game code>`, platform 35, NDK r29 and CMake 3.31.6;
  - native code in CMake's Release build, for the `abis` asked for;
  - `noCompress "gba"`, so SDL reads the ROM straight from the APK.
- **Writing the project again** replaces what an earlier run wrote and keeps Gradle's and CMake's build folders, so a rebuild compiles only what changed.
- **`GameActivity`** extends SDL's activity. It loads `libSDL3.so` and `libmain.so` and runs `main` with `game.gba`, plus the options in the intent's `gbaport.args` extra.

`build_apk(project, apk)` runs Gradle (`assembleDebug`, no daemon, `GRADLE_USER_HOME` in the cache folder) and copies the debug-signed APK.

`gbaport build ROM --host android [--abi ABI]...` builds the app into `<out>/build/<game code>.apk`: arm64-v8a by default, which phones have; the emulator on a PC is x86_64. `--abi` with another host is an error.

`tests/androidkit.py` builds test ROMs' apps for the emulator in one shared project in the ROM cache, so SDL3 compiles once. This task's only real Gradle build checks one of them. The first one fetches the Android Gradle plugin and compiles SDL3: several minutes.

The host is the desktop's `host_sdl.c` for now: it compiles for Android, and Task 4 makes it work there.

**Files:**
- Modify: `src/gbaport/native/android.py` (`application_id`, `android_project`, `build_apk`, `TEMPLATE`, `ABIS`, `HOST_SOURCES`)
- Create: `src/gbaport/native/android_template/` (`settings.gradle`, `build.gradle`, `gradle.properties`, `app/build.gradle`, `app/src/main/AndroidManifest.xml`, `app/src/main/cpp/CMakeLists.txt`, `app/src/main/java/org/gbaport/game/GameActivity.java`, `app/src/main/res/values/strings.xml`, `styles.xml`)
- Modify: `src/gbaport/cli.py` (`build --host android`, `--abi`)
- Create: `tests/androidkit.py`
- Test: `tests/test_android.py`, `tests/test_build_cli.py`

**Interfaces:**
- Consumes: Task 2's `android_sdk`, `gradle`, `sdl3_source`, `java_environment`, the pinned versions; `gbaport.native.build`'s `CFLAGS`, `RUNTIME`, `RUNTIME_SOURCES`, `generated_sources`, `write_sources`; `romtest.CACHE`, `build_test_rom`.
- **Produces:**
  - **`gbaport.native.android`:** `ABIS = ("arm64-v8a", "x86_64")`, `HOST_SOURCES`, `TEMPLATE`. `application_id(game_code) -> str`: letters and digits only, lower case; `g` before a leading digit; `game` when empty.
  - **Building:** `android_project(sources: Path, rom: bytes, out: Path, game_code: str, label: str, abis: tuple[str, ...], sdl: Path, sdk: Path) -> Path`. `build_apk(project: Path, apk: Path, log=print) -> Path`.
  - **`androidkit`:** `APP = "org.gbaport.atst"` (every test ROM's game code is ATST), `FOLDER`, `rom_apk(name) -> Path`.

- [ ] **Step 1: Write the failing tests**

Create `tests/androidkit.py`:
```python
"""Test ROMs as Android apps.

``rom_apk(name)`` builds a test ROM's app for gbaport's emulator (x86_64). Every test ROM
goes through one Gradle project, so SDL3 and the runtime compile once and each app after
the first takes seconds; the APKs are cached by the hash of everything that goes in. All
test ROMs have the game code ATST, so they install as the same app (``APP``), one
replacing another.
"""

import hashlib
from pathlib import Path

from romtest import CACHE, build_test_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.native import android
from gbaport.native import build as native
from gbaport.rom.image import RomImage

APP = android.application_id("ATST")
FOLDER = CACHE / "android"


def rom_apk(name: str) -> Path:
    rom = build_test_rom(name)
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration),
                                     rom.data, analysis.save)
    digest = hashlib.sha1(rom.data)
    for file_name, text in sorted(files.items()):
        digest.update(f"{file_name}\n{text}".encode())
    inputs = [*native.RUNTIME.glob("*.[ch]"), *android.TEMPLATE.rglob("*"), Path(android.__file__)]
    for path in sorted(p for p in inputs if p.is_file()):
        digest.update(path.read_bytes())
    apk = FOLDER / "apks" / f"{digest.hexdigest()[:16]}.apk"
    if not apk.exists():
        native.write_sources(files, FOLDER / "generated")
        project = android.android_project(
            FOLDER / "generated", rom.data, FOLDER / "project", "ATST", "gbaport test",
            ("x86_64",), android.sdl3_source(), android.android_sdk())
        android.build_apk(project, apk)
    return apk
```

In `tests/test_android.py`, replace:
```python
"""What a game's Android app is built with (gbaport/native/android.py), without Google's
servers: a stand-in sdkmanager and local files for the downloads."""

import hashlib
```
with:
```python
"""A game's Android app (gbaport/native/android.py): what it is built with, tested with a
stand-in sdkmanager and local files for the downloads; its Gradle project, with a
stand-in SDL3; and one real build, of a test ROM's app."""

import hashlib
```

In `tests/test_android.py`, replace:
```python

import pytest

from gbaport.native import android
```
with:
```python

import pytest
from androidkit import rom_apk
from romtest import build_test_rom

from gbaport.native import android
```

In `tests/test_android.py`, replace:
```python
        f"gradle-{android.GRADLE_VERSION}", f"sdl3-{android.SDL3_VERSION}-source"]  # no archives left
```
with:
```python
        f"gradle-{android.GRADLE_VERSION}", f"sdl3-{android.SDL3_VERSION}-source"]  # no archives left


@pytest.mark.parametrize("code, expected", [
    ("BT4E", "org.gbaport.bt4e"), ("ATST", "org.gbaport.atst"), ("1ABC", "org.gbaport.g1abc"),
    ("", "org.gbaport.game"), ("A-Bé", "org.gbaport.ab"),
])
def test_each_game_is_an_app_of_its_own(code, expected):
    assert android.application_id(code) == expected


def fake_sdl(tmp_path: Path) -> Path:
    sdl = tmp_path / "sdl"
    main = sdl / "android-project" / "app" / "src" / "main"
    (main / "java" / "org" / "libsdl" / "app").mkdir(parents=True)
    (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").write_text(
        "package org.libsdl.app;\n", encoding="utf-8")
    for density in ("mdpi", "hdpi"):
        (main / "res" / f"mipmap-{density}").mkdir(parents=True)
        (main / "res" / f"mipmap-{density}" / "ic_launcher.png").write_bytes(b"png")
    return sdl


def generated(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "generated"
    folder.mkdir(exist_ok=True)
    for name in (*names, "gba_program.h"):
        (folder / name).write_text(f"/* {name} */\n", encoding="utf-8")
    return folder


def test_the_project_holds_the_game_the_runtime_sdl_and_the_rom(tmp_path):
    sdk = tmp_path / "an sdk"
    sources = generated(tmp_path, "gba_code_000.c", "gba_dispatch.c")
    out = android.android_project(sources, b"rom bytes", tmp_path / "project", "BT4E", "DBZ & GT",
                                  ("arm64-v8a", "x86_64"), fake_sdl(tmp_path), sdk)
    main = out / "app" / "src" / "main"
    assert (main / "assets" / "game.gba").read_bytes() == b"rom bytes"
    assert (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").exists()
    assert (main / "java" / "org" / "gbaport" / "game" / "GameActivity.java").exists()
    assert (main / "res" / "mipmap-hdpi" / "ic_launcher.png").exists()
    assert (main / "cpp" / "generated" / "gba_program.h").exists()
    assert (main / "cpp" / "runtime" / "touch.h").exists()
    cmake = (main / "cpp" / "CMakeLists.txt").read_text(encoding="utf-8")
    units = [line.strip() for line in cmake.splitlines() if line.strip().endswith(".c")]
    assert units == ["generated/gba_code_000.c", "generated/gba_dispatch.c",
                     *(f"runtime/{n}" for n in (*android.RUNTIME_SOURCES, *android.HOST_SOURCES))]
    assert f'add_subdirectory("{(tmp_path / "sdl").as_posix()}" SDL3)' in cmake
    gradle = (out / "app" / "build.gradle").read_text(encoding="utf-8")
    assert 'applicationId = "org.gbaport.bt4e"' in gradle
    assert "abiFilters 'arm64-v8a', 'x86_64'" in gradle
    assert f'ndkVersion = "{android.NDK}"' in gradle
    assert "DBZ &amp; GT" in (main / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    written = [p.read_text(encoding="utf-8") for p in out.rglob("*") if p.suffix in
               {".gradle", ".txt", ".xml", ".java", ".properties"}]
    assert not any("@" + key in text for text in written for key in ("NAME", "NDK", "SOURCES"))
    escaped = str(sdk).replace("\\", "\\\\").replace(":", "\\:")
    assert (out / "local.properties").read_text(encoding="utf-8") == f"sdk.dir={escaped}\n"


def test_writing_the_project_again_replaces_what_the_game_left(tmp_path):
    sdl = fake_sdl(tmp_path)
    sources = generated(tmp_path, "gba_code_000.c", "gba_code_001.c")
    out = android.android_project(sources, b"1", tmp_path / "project", "ATST", "", ("x86_64",),
                                  sdl, tmp_path / "sdk")
    (out / "app" / "build").mkdir()  # Gradle's: kept, so that a rebuild compiles less
    (sources / "gba_code_001.c").unlink()
    android.android_project(sources, b"2", out, "ATST", "", ("x86_64",), sdl, tmp_path / "sdk")
    cpp = out / "app" / "src" / "main" / "cpp"
    assert not (cpp / "generated" / "gba_code_001.c").exists()
    assert "gba_code_001" not in (cpp / "CMakeLists.txt").read_text(encoding="utf-8")
    assert (out / "app" / "src" / "main" / "assets" / "game.gba").read_bytes() == b"2"
    assert (out / "app" / "build").is_dir()


def test_a_test_roms_app_holds_its_code_for_the_emulator_and_its_rom():
    """A real build with Gradle (the first one fetches the Android Gradle plugin and
    compiles SDL3, which takes some minutes)."""
    apk = rom_apk("hello")
    with zipfile.ZipFile(apk) as zipped:
        names = set(zipped.namelist())
        assert {"lib/x86_64/libmain.so", "lib/x86_64/libSDL3.so", "assets/game.gba"} <= names
        assert zipped.read("assets/game.gba") == build_test_rom("hello").data
        assert zipped.getinfo("assets/game.gba").compress_type == zipfile.ZIP_STORED
        dex = b"".join(zipped.read(name) for name in names if name.endswith(".dex"))
    assert b"Lorg/gbaport/game/GameActivity;" in dex
```

Create `tests/test_build_cli.py` (replacing the current version):
```python
import os

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


def test_abi_is_for_android_only(tmp_path, capsys):
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    assert main(["build", str(rom_path), "--host", "headless", "--abi", "x86_64"]) == 1
    assert "--abi is for --host android" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_android.py tests/test_build_cli.py`
Expected: FAIL: 1 error during collection, `AttributeError: module 'gbaport.native.android' has no attribute 'application_id'` (from `tests/androidkit.py`), which interrupts the run.

- [ ] **Step 3: The project, Gradle, and the command**

In `src/gbaport/cli.py`, replace:
```python
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
```
with:
```python
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.android import ABIS as ANDROID_ABIS
from gbaport.native.android import android_project, android_sdk, build_apk, sdl3_source
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
```

In `src/gbaport/cli.py`, replace:
```python
        "--host",
        choices=sorted(HOSTS),
        default="sdl",
        help="sdl: a window (the default; builds SDL3 the first time); headless: no window",
    )
```
with:
```python
        "--host",
        choices=sorted([*HOSTS, "android"]),
        default="sdl",
        help="sdl: a window (the default; builds SDL3 the first time); headless: no window; "
        "android: an app (fetches the Android SDK, Gradle and SDL3's source the first time)",
    )
    build.add_argument(
        "--abi",
        action="append",
        choices=ANDROID_ABIS,
        default=[],
        help="android: a processor to build for (repeatable; default arm64-v8a, which phones "
        "have; the emulator on a PC is x86_64)",
    )
```

In `src/gbaport/cli.py`, replace:
```python
    root = Path(args.out) if args.out else Path("games") / game_code
    _recompile(args, rom, root / "generated")
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
```
with:
```python
    root = Path(args.out) if args.out else Path("games") / game_code
    if args.host != "android" and args.abi:
        raise ValueError("--abi is for --host android")
    _recompile(args, rom, root / "generated")
    if args.host == "android":
        return _build_android(args, rom, root)
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
```

In `src/gbaport/cli.py`, replace:
```python
    print(f"run it with: {program} {args.rom} [--save PATH] [--frames N]")
    return 0
```
with:
```python
    print(f"run it with: {program} {args.rom} [--save PATH] [--frames N]")
    return 0


def _build_android(args: argparse.Namespace, rom: RomImage, root: Path) -> int:
    """The game's app: its Gradle project in <root>/build/android, the APK next to it."""
    header = parse_header(rom)
    abis = tuple(dict.fromkeys(args.abi)) or ("arm64-v8a",)
    sdk = android_sdk()
    project = android_project(root / "generated", rom.data, root / "build" / "android",
                              header.game_code, header.title, abis, sdl3_source(), sdk)
    apk = build_apk(project, root / "build" / f"{header.game_code or 'game'}.apk")
    print(f"built {apk} ({', '.join(abis)})")
    print(f"install it with: {sdk / 'platform-tools' / 'adb'} install -r {apk}")
    return 0
```

In `src/gbaport/native/android.py`, replace:
```python
"""Android: what a game's app is built with, fetched once into the cache folder.

- **The Android SDK** (``android_sdk``): Google's command-line tools, then the platform,
```
with:
```python
"""Android: a game's app, a Gradle project built with the Android SDK and NDK.

``android_project`` writes the project from ``android_template``: the game's generated C
sources, the runtime and its window host (``host_sdl.c``, which knows phones), SDL3's
Java code and the ROM, as an asset. ``build_apk`` builds it with Gradle into an APK signed
with the SDK's debug key, which phones install over USB. What they need comes into the
cache folder the first time:

- **The Android SDK** (``android_sdk``): Google's command-line tools, then the platform,
```

In `src/gbaport/native/android.py`, replace:
```python
- **Gradle** (``gradle``), which builds the app; it runs on a JDK 17 or newer
  (``java_environment``).
- **SDL3's source** (``sdl3_source``): the app builds SDL3 from it and takes SDL's Java
```
with:
```python
- **Gradle** (``gradle``), which builds the app; it runs on a JDK 17 or newer
  (``java_environment``). Its downloads (the Android Gradle plugin) go to ``gradle-home``.
- **SDL3's source** (``sdl3_source``): the app builds SDL3 from it and takes SDL's Java
```

In `src/gbaport/native/android.py`, replace:
```python

from gbaport.native.sdl3 import SDL3_SHA256, SDL3_URL, SDL3_VERSION, cache_folder
from gbaport.native.toolchain import ToolchainError

GRADLE_VERSION = "8.12.1"  # with the Android Gradle plugin 8.7.3, as SDL3's android-project
```
with:
```python

from gbaport.native.build import CFLAGS, RUNTIME, RUNTIME_SOURCES
from gbaport.native.sdl3 import SDL3_SHA256, SDL3_URL, SDL3_VERSION, cache_folder
from gbaport.native.toolchain import ToolchainError

TEMPLATE = Path(__file__).parent / "android_template"
ANDROID_PLUGIN = "8.7.3"
HOST_SOURCES = ("host_common.c", "host_sdl.c", "touch.c")
ABIS = ("arm64-v8a", "x86_64")  # phones; the emulator on a PC
GRADLE_VERSION = "8.12.1"  # with the Android Gradle plugin 8.7.3, as SDL3's android-project
```

In `src/gbaport/native/android.py`, replace:
```python
    archive.unlink()
```
with:
```python
    archive.unlink()


def application_id(game_code: str) -> str:
    """The app's name on the phone: org.gbaport.<game code>, so each game is its own app."""
    code = "".join(c for c in game_code.lower() if c.isascii() and c.isalnum())
    return f"org.gbaport.{'g' + code if code[:1].isdigit() else code or 'game'}"


def android_project(sources: Path, rom: bytes, out: Path, game_code: str, label: str,
                    abis: tuple[str, ...], sdl: Path, sdk: Path) -> Path:
    """Writes the app's Gradle project to ``out``: the game's C ``sources`` (gbaport
    recompile's folder), the runtime, SDL3's Java code from ``sdl`` and the ``rom``, built
    for ``abis`` with the SDK in ``sdk``. Writing it again replaces what an earlier run
    wrote, and keeps Gradle's and CMake's build folders, so a rebuild compiles only what
    changed."""
    main = out / "app" / "src" / "main"
    cpp = main / "cpp"
    for folder in (cpp / "generated", cpp / "runtime", main / "java", main / "assets", main / "res"):
        shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(sources, cpp / "generated")
    (cpp / "runtime").mkdir(parents=True)
    for path in RUNTIME.glob("*.[ch]"):
        shutil.copy2(path, cpp / "runtime" / path.name)
    sdl_main = sdl / "android-project" / "app" / "src" / "main"
    shutil.copytree(sdl_main / "java", main / "java")
    for icons in (sdl_main / "res").glob("mipmap-*"):
        shutil.copytree(icons, main / "res" / icons.name)
    (main / "assets").mkdir(parents=True)
    (main / "assets" / "game.gba").write_bytes(rom)
    units = [f"generated/{path.name}" for path in sorted((cpp / "generated").glob("*.c"))]
    units += [f"runtime/{name}" for name in (*RUNTIME_SOURCES, *HOST_SOURCES)]
    values = {
        "NAME": game_code or "game", "LABEL": _xml(label or game_code or "gbaport"),
        "ANDROID_PLUGIN": ANDROID_PLUGIN, "PLATFORM": str(PLATFORM), "BUILD_TOOLS": BUILD_TOOLS,
        "NDK": NDK, "CMAKE": CMAKE, "APPLICATION_ID": application_id(game_code),
        "ABIS": ", ".join(f"'{abi}'" for abi in abis), "SDL3_SOURCE": sdl.as_posix(),
        "SOURCES": "\n".join(f"    {unit}" for unit in units), "CFLAGS": " ".join(CFLAGS),
    }
    for template in TEMPLATE.rglob("*"):
        if template.is_file():
            text = template.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace(f"@{key}@", value)
            target = out / template.relative_to(TEMPLATE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    escaped = str(sdk).replace("\\", "\\\\").replace(":", "\\:")  # a Java properties file
    (out / "local.properties").write_text(f"sdk.dir={escaped}\n", encoding="utf-8")
    return out


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "\\'")


def build_apk(project: Path, apk: Path, log: Log = print) -> Path:
    """Builds ``project`` (android_project's) with Gradle; the APK is copied to ``apk``."""
    env = {**java_environment(), "ANDROID_HOME": str(android_sdk(log)),
           "GRADLE_USER_HOME": str(cache_folder() / "gradle-home")}
    result = subprocess.run(
        [str(gradle(log)), "--no-daemon", "--console=plain", "-p", str(project), "assembleDebug"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False,
    )
    if result.returncode != 0:
        raise ToolchainError(f"Gradle failed to build {project}:\n"
                             f"{(result.stdout + result.stderr)[-6000:]}")
    apk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk", apk)
    return apk
```

Create `src/gbaport/native/android_template/app/build.gradle`:
```groovy
// Generated by gbaport (gbaport/native/android.py). The game's C code, the runtime and
// SDL3 are built by CMake (src/main/cpp/CMakeLists.txt) as libmain.so and libSDL3.so;
// the ROM goes into the app's assets uncompressed, so SDL reads it straight from the APK.
plugins {
    id 'com.android.application'
}

android {
    namespace = "org.gbaport.game"
    compileSdk = @PLATFORM@
    buildToolsVersion = "@BUILD_TOOLS@"
    ndkVersion = "@NDK@"
    defaultConfig {
        applicationId = "@APPLICATION_ID@"
        minSdk = 24
        targetSdk = @PLATFORM@
        versionCode = 1
        versionName = "1.0"
        externalNativeBuild {
            cmake {
                arguments "-DCMAKE_BUILD_TYPE=Release"
                abiFilters @ABIS@
            }
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "@CMAKE@"
        }
    }
    androidResources {
        noCompress += "gba"
    }
    lint {
        abortOnError = false
    }
}
```

Create `src/gbaport/native/android_template/app/src/main/AndroidManifest.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by gbaport (gbaport/native/android.py), after SDL3's android-project. -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-feature android:glEsVersion="0x00020000" />
    <uses-feature android:name="android.hardware.touchscreen" android:required="false" />
    <uses-feature android:name="android.hardware.gamepad" android:required="false" />
    <uses-feature android:name="android.hardware.usb.host" android:required="false" />
    <uses-feature android:name="android.hardware.bluetooth" android:required="false" />

    <application android:label="@string/app_name"
        android:icon="@mipmap/ic_launcher"
        android:allowBackup="false"
        android:theme="@style/AppTheme"
        android:hardwareAccelerated="true">
        <activity android:name="org.gbaport.game.GameActivity"
            android:label="@string/app_name"
            android:alwaysRetainTaskState="true"
            android:launchMode="singleInstance"
            android:screenOrientation="sensorLandscape"
            android:configChanges="layoutDirection|locale|grammaticalGender|fontScale|fontWeightAdjustment|orientation|uiMode|screenLayout|screenSize|smallestScreenSize|keyboard|keyboardHidden|navigation"
            android:preferMinimalPostProcessing="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.hardware.usb.action.USB_DEVICE_ATTACHED" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

Create `src/gbaport/native/android_template/app/src/main/cpp/CMakeLists.txt`:
```cmake
# Generated by gbaport (gbaport/native/android.py): the game's recompiled C code
# (generated/), gbaport's runtime and window host (runtime/) and SDL3, from its source.
cmake_minimum_required(VERSION 3.22)
project(gbaport_game LANGUAGES C)

set(SDL_SHARED ON CACHE BOOL "" FORCE)
set(SDL_STATIC OFF CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
add_subdirectory("@SDL3_SOURCE@" SDL3)

add_library(main SHARED
@SOURCES@
)
target_include_directories(main PRIVATE generated runtime)
target_compile_options(main PRIVATE @CFLAGS@)
target_link_libraries(main PRIVATE SDL3::SDL3 log m)
```

Create `src/gbaport/native/android_template/app/src/main/java/org/gbaport/game/GameActivity.java`:
```java
// Generated by gbaport (gbaport/native/android.py).
package org.gbaport.game;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import org.libsdl.app.SDLActivity;

/** The game: SDL's activity, running libmain.so's main() on the ROM in the assets. The
 *  intent's "gbaport.args" extra adds options, as on the desktop host's command line:
 *  adb shell am start -n APP/org.gbaport.game.GameActivity --es gbaport.args "'--frames 600'" */
public class GameActivity extends SDLActivity {
    @Override
    protected String[] getLibraries() {
        return new String[] {"SDL3", "main"};
    }

    @Override
    protected String[] getArguments() {
        List<String> arguments = new ArrayList<>();
        arguments.add("game.gba");
        String extra = getIntent().getStringExtra("gbaport.args");
        if (extra != null && !extra.trim().isEmpty())
            arguments.addAll(Arrays.asList(extra.trim().split("[ \\t]+")));
        return arguments.toArray(new String[0]);
    }
}
```

Create `src/gbaport/native/android_template/app/src/main/res/values/strings.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by gbaport (gbaport/native/android.py). -->
<resources>
    <string name="app_name">@LABEL@</string>
</resources>
```

Create `src/gbaport/native/android_template/app/src/main/res/values/styles.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Generated by gbaport (gbaport/native/android.py). -->
<resources>
    <style name="AppTheme" parent="android:Theme.NoTitleBar.Fullscreen" />
</resources>
```

Create `src/gbaport/native/android_template/build.gradle`:
```groovy
// Generated by gbaport (gbaport/native/android.py).
plugins {
    id 'com.android.application' version '@ANDROID_PLUGIN@' apply false
}
```

Create `src/gbaport/native/android_template/gradle.properties`:
```properties
# Generated by gbaport (gbaport/native/android.py).
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
```

Create `src/gbaport/native/android_template/settings.gradle`:
```groovy
// Generated by gbaport (gbaport/native/android.py): the Android app of one game.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "@NAME@"
include ':app'
```

- [ ] **Step 4: Run the whole suite**

The first real Gradle build runs here (`test_a_test_roms_app_holds_its_code_for_the_emulator_and_its_rom`): several minutes the first time.

Run: `uv run pytest`
Expected: 915 passed (904 + 11).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/native/android.py src/gbaport/native/android_template src/gbaport/cli.py tests/androidkit.py tests/test_android.py tests/test_build_cli.py
git commit -m "feat: gbaport build --host android writes the game's Gradle project and builds its APK"
```

---

### Task 4: The game runs on a phone

**The host on Android** (`host_sdl.c`, `#if MOBILE`):
- **Output.** stdout and stderr go to logcat (tag `gbaport`) through a pipe and a thread.
- **Files.** The default save file is `game.sav` in the app's own storage (`SDL_GetPrefPath`). The ROM is read from the app's assets with `SDL_LoadFile`; `host_open` now takes a ROM the host has already loaded (`HostOptions.rom`, `rom_size`).
- **The screen.** The window is full screen. The picture goes where `touch_layout` puts it, scaled with SDL's pixel-art filter, and is laid out again when the screen's size or safe area changes.
- **Errors.** A run that ends with an error shows `rt.error` in a message box. The app closes when `main` returns.

**`GameActivity`.** SDL keeps the process once `main` has returned and refuses to run `main` in it again. So once the game ends, the process ends too (`System.exit` in `onDestroy` when finishing), and the next start is a fresh one.

**`gbaport/native/device.py`:**
- **`Device`** drives a device through the SDK's adb: `install`, `start(app, args)`, `stop` (force-stop, as Android kills apps), `clear`, `running`, `log` (the app's logcat lines) and `wait_for(pattern)`.
- **`the_device()`** is the one device adb sees, or the one `ANDROID_SERIAL` names.
- **`start_emulator()`** makes gbaport's virtual device the first time (`android-avd` in the cache folder) and boots it. It installs the emulator and the Android 15 x86_64 system image through `install_packages` if they are missing.
  - **How it runs.** `-no-window -no-audio -gpu host -no-snapshot`, and it confirms Android's "viewing full screen" notice so it never covers the app.
  - **Why no snapshot.** In validation, the emulator's quick-boot snapshot (saved on `adb emu kill` by default) left a half-shut-down emulator that adb still listed and every install then hung on. Booting afresh takes about 25 seconds.
  - **An emulator already running** is used if it answers, and reported if it does not.
- **`stop_emulator(device, process)`** sends `adb emu kill`, waits for the process to end, and kills its process tree after a minute.

**`gbaport build --host android --install`.** It finds the device first, before the long build. It builds for that device's processor unless `--abi` says otherwise, installs the app, and starts it. `--install` with another host is an error.

**The tests.** `tests/test_android_device.py` boots the emulator for its tests when it is not running and shuts it down after them. Its first boot takes one to four minutes.

**Files:**
- Modify: `src/gbaport/runtime/host_common.h`, `host_common.c` (`rom_size`, a ROM loaded by the host)
- Modify: `src/gbaport/runtime/host_sdl.c` (the phone branch)
- Modify: `src/gbaport/native/android_template/app/src/main/java/org/gbaport/game/GameActivity.java` (`onDestroy`)
- Create: `src/gbaport/native/device.py`
- Modify: `src/gbaport/cli.py` (`--install`)
- Test: `tests/test_android_device.py`, `tests/test_build_cli.py`

**Interfaces:**
- Consumes: Task 1's `touch_layout`, `TouchState`; Task 2's `android_sdk`, `install_packages`, `installed`, `java_environment`; Task 3's `rom_apk`, `APP`, `FOLDER`, `application_id`.
- **Produces:**
  - **`gbaport.native.device`:** `DeviceError(OSError)`, `adb(*args, serial=None, timeout=120) -> str`, `devices() -> list[str]`, `the_device() -> Device`, `start_emulator(timeout=600) -> tuple[Device, subprocess.Popen | None]` (the device, and its process if this call started it), `stop_emulator(device, process)`.
  - **`Device(serial)`:** `.adb`, `.shell`, `.abi()`, `.install(apk)`, `.start(app, args="")`, `.stop(app)`, `.clear(app)`, `.running(app)`, `.clear_log()`, `.log() -> list[str]`, `.wait_for(pattern, timeout=60) -> re.Match`.
  - **`HostOptions.rom_size`;** `host_open` reads `rom_path` only when `rom` is NULL.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_android_device.py`:
```python
"""Test ROMs' apps on gbaport's Android emulator (no window, no sound; the first boot takes
a minute or two, and the tests shut it down after them if they started it)."""

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
```

In `tests/test_build_cli.py`, replace:
```python

from romtest import build_test_rom, run_program
```
with:
```python

import pytest
from romtest import build_test_rom, run_program
```

In `tests/test_build_cli.py`, replace:
```python

def test_abi_is_for_android_only(tmp_path, capsys):
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    assert main(["build", str(rom_path), "--host", "headless", "--abi", "x86_64"]) == 1
    assert "--abi is for --host android" in capsys.readouterr().err
```
with:
```python

@pytest.mark.parametrize("option", [["--abi", "x86_64"], ["--install"]])
def test_abi_and_install_are_for_android_only(tmp_path, capsys, option):
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    assert main(["build", str(rom_path), "--host", "headless", *option]) == 1
    printed = capsys.readouterr()
    assert "--abi and --install are for --host android" in printed.err
    assert "functions" not in printed.out  # it stopped before recompiling
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_android_device.py tests/test_build_cli.py`
Expected: FAIL: 1 error during collection, `ModuleNotFoundError: No module named 'gbaport.native.device'`, which interrupts the run.

- [ ] **Step 3: The host on Android, the activity, the device and --install**

In `src/gbaport/cli.py`, replace:
```python
from gbaport.native.android import ABIS as ANDROID_ABIS
from gbaport.native.android import android_project, android_sdk, build_apk, sdl3_source
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.native.mgba import run_mgba
```
with:
```python
from gbaport.native.android import ABIS as ANDROID_ABIS
from gbaport.native.android import (
    android_project,
    android_sdk,
    application_id,
    build_apk,
    sdl3_source,
)
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.native.device import the_device
from gbaport.native.mgba import run_mgba
```

In `src/gbaport/cli.py`, replace:
```python
        default=[],
        help="android: a processor to build for (repeatable; default arm64-v8a, which phones "
        "have; the emulator on a PC is x86_64)",
    )
```
with:
```python
        default=[],
        help="android: a processor to build for (repeatable; default: the device's with "
        "--install, else arm64-v8a, which phones have; the emulator on a PC is x86_64)",
    )
    build.add_argument(
        "--install",
        action="store_true",
        help="android: install the app on the connected phone (USB debugging on) and start it",
    )
```

In `src/gbaport/cli.py`, replace:
```python
    root = Path(args.out) if args.out else Path("games") / game_code
    if args.host != "android" and args.abi:
        raise ValueError("--abi is for --host android")
    _recompile(args, rom, root / "generated")
    if args.host == "android":
        return _build_android(args, rom, root)
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
```
with:
```python
    root = Path(args.out) if args.out else Path("games") / game_code
    if args.host != "android" and (args.abi or args.install):
        raise ValueError("--abi and --install are for --host android")
    device = the_device() if args.install else None  # before the long build: is one there?
    _recompile(args, rom, root / "generated")
    if args.host == "android":
        return _build_android(args, rom, root, device)
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
```

In `src/gbaport/cli.py`, replace:
```python

def _build_android(args: argparse.Namespace, rom: RomImage, root: Path) -> int:
    """The game's app: its Gradle project in <root>/build/android, the APK next to it."""
    header = parse_header(rom)
    abis = tuple(dict.fromkeys(args.abi)) or ("arm64-v8a",)
    sdk = android_sdk()
```
with:
```python

def _build_android(args: argparse.Namespace, rom: RomImage, root: Path, device) -> int:
    """The game's app: its Gradle project in <root>/build/android, the APK next to it;
    installed on ``device`` and started, if there is one."""
    header = parse_header(rom)
    abis = tuple(dict.fromkeys(args.abi)) or ((device.abi(),) if device else ("arm64-v8a",))
    if abis[0] not in ANDROID_ABIS:
        raise ValueError(f"{device.serial} runs {abis[0]} code; gbaport builds for "
                         f"{' and '.join(ANDROID_ABIS)}")
    sdk = android_sdk()
```

In `src/gbaport/cli.py`, replace:
```python
    print(f"built {apk} ({', '.join(abis)})")
    print(f"install it with: {sdk / 'platform-tools' / 'adb'} install -r {apk}")
    return 0
```
with:
```python
    print(f"built {apk} ({', '.join(abis)})")
    if device is None:
        print(f"install it with --install, or: {sdk / 'platform-tools' / 'adb'} install -r {apk}")
        return 0
    device.install(apk)
    device.start(application_id(header.game_code))
    print(f"installed it on {device.serial} and started it")
    return 0
```

In `src/gbaport/native/android_template/app/src/main/java/org/gbaport/game/GameActivity.java`, replace:
```java
    }
}
```
with:
```java
    }

    /* SDL keeps the process once main() has returned, and will not run main() in it again:
     * once the game has ended, the process ends too, so that the next start is a fresh one. */
    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (isFinishing())
            System.exit(0);
    }
}
```

Create `src/gbaport/native/device.py`:
```python
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
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
{
    uint32_t size;
    o->rom = read_file(o->rom_path, &size);
    if (!o->rom) {
```
with:
```c
{
    if (!o->rom)  /* a phone's host has it from the app's assets */
        o->rom = read_file(o->rom_path, &o->rom_size);
    if (!o->rom) {
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
    }
    if (gba_init(rt, o->rom, size, host) != 0) {
        fprintf(stderr, "error: %s\n", rt->error);
```
with:
```c
    }
    if (gba_init(rt, o->rom, o->rom_size, host) != 0) {
        fprintf(stderr, "error: %s\n", rt->error);
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
    uint16_t script_keys;       /* what the presses so far hold */
    uint8_t *rom;
} HostOptions;
```
with:
```c
    uint16_t script_keys;       /* what the presses so far hold */
    uint8_t *rom;               /* the ROM (NULL: host_open reads rom_path) */
    uint32_t rom_size;
} HostOptions;
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
 * plays up to 1% faster or slower to keep it so. Without a sound device the game runs
 * silent (one warning); with --fast it runs silent too. */
#include <stdio.h>
```
with:
```c
 * plays up to 1% faster or slower to keep it so. Without a sound device the game runs
 * silent (one warning); with --fast it runs silent too.
 *
 * On a phone (Android) the picture fills the screen, held sideways, as large as it fits
 * (touch.c lays it out). The ROM is the app's asset game.gba and the save file lives in
 * the app's own storage. Everything the game and the runtime print goes to the system
 * log (logcat, tag "gbaport"); a run that ends with an error shows it before the app
 * closes. The options come from the app's intent (GameActivity.java). */
#include <stdio.h>
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c

#include "host_common.h"

#define FRAME_NS 16742706u  /* 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns */
```
with:
```c

#include "host_common.h"

#if defined(SDL_PLATFORM_ANDROID)
#define MOBILE 1
#include <android/log.h>
#include <pthread.h>
#include <unistd.h>

#include "touch.h"
#else
#define MOBILE 0
#endif

#define FRAME_NS 16742706u  /* 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns */
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c

static void handle(const SDL_Event *event)
```
with:
```c

#if MOBILE
static TouchState touch;
static int screen_w, screen_h;  /* in pixels */

/* stdout and stderr go nowhere on Android: a thread passes their lines to logcat. */
static void *forward_output(void *pipe_end)
{
    FILE *output = fdopen((int)(intptr_t)pipe_end, "r");
    char line[1024];
    while (output && fgets(line, sizeof line, output)) {
        line[strcspn(line, "\n")] = 0;
        __android_log_write(ANDROID_LOG_INFO, "gbaport", line);
    }
    return NULL;
}

static void output_to_log(void)
{
    int ends[2];
    pthread_t thread;
    if (pipe(ends) != 0)
        return;
    dup2(ends[1], 1);
    dup2(ends[1], 2);
    setvbuf(stdout, NULL, _IOLBF, 0);
    setvbuf(stderr, NULL, _IOLBF, 0);
    if (pthread_create(&thread, NULL, forward_output, (void *)(intptr_t)ends[0]) == 0)
        pthread_detach(thread);
}

/* The screen's size and safe area (clear of notches and system bars) in pixels. */
static void lay_out(void)
{
    SDL_GetWindowSizeInPixels(window, &screen_w, &screen_h);
    float density = SDL_GetWindowPixelDensity(window);
    SDL_Rect safe;
    if (!SDL_GetWindowSafeArea(window, &safe) || safe.w <= 0 || safe.h <= 0)
        safe = (SDL_Rect){0, 0, (int)(screen_w / density), (int)(screen_h / density)};
    touch_layout(&touch.layout, (float)screen_w, (float)screen_h,
                 (TouchBox){safe.x * density, safe.y * density, safe.w * density, safe.h * density});
}
#endif

static void handle(const SDL_Event *event)
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    }
}
```
with:
```c
    }
#if MOBILE
    else if (event->type == SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED ||
             event->type == SDL_EVENT_WINDOW_SAFE_AREA_CHANGED)
        lay_out();
#endif
}
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    SDL_RenderClear(renderer);
    SDL_RenderTexture(renderer, texture, NULL, NULL);
}
```
with:
```c
    SDL_RenderClear(renderer);
#if MOBILE
    TouchBox s = touch.layout.screen;
    SDL_RenderTexture(renderer, texture, NULL, &(SDL_FRect){s.x, s.y, s.w, s.h});
#else
    SDL_RenderTexture(renderer, texture, NULL, NULL);
#endif
}
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    }
    int w = GBA_SCREEN_WIDTH * options.scale, h = GBA_SCREEN_HEIGHT * options.scale;
    if (!SDL_CreateWindowAndRenderer(title, w, h, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
        fprintf(stderr, "error: cannot open a window: %s\n", SDL_GetError());
        return -1;
    }
    SDL_SetRenderLogicalPresentation(renderer, GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT,
                                     SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING,
```
with:
```c
    }
#if MOBILE
    if (!SDL_CreateWindowAndRenderer(title, 0, 0, SDL_WINDOW_FULLSCREEN, &window, &renderer)) {
#else
    int w = GBA_SCREEN_WIDTH * options.scale, h = GBA_SCREEN_HEIGHT * options.scale;
    if (!SDL_CreateWindowAndRenderer(title, w, h, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
#endif
        fprintf(stderr, "error: cannot open a window: %s\n", SDL_GetError());
        return -1;
    }
#if !MOBILE
    SDL_SetRenderLogicalPresentation(renderer, GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT,
                                     SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
#endif
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING,
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    }
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
    return 0;
```
with:
```c
    }
#if MOBILE
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_PIXELART);  /* any size, still crisp */
    lay_out();
#else
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
#endif
    return 0;
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    options.window = 1;
    int status = host_parse(&options, argc, argv);
    if (status == 0)
```
with:
```c
    options.window = 1;
#if MOBILE
    output_to_log();
    char *storage = SDL_GetPrefPath("gbaport", "game");  /* the app's own storage */
    if (storage)  /* the default save file; --save still names another */
        snprintf(options.save_path, sizeof options.save_path, "%sgame.sav", storage);
    SDL_free(storage);
#endif
    int status = host_parse(&options, argc, argv);
#if MOBILE
    if (status == 0) {  /* the ROM is one of the app's assets, which only SDL can read */
        size_t size = 0;
        options.rom = SDL_LoadFile(options.rom_path, &size);
        options.rom_size = (uint32_t)size;
    }
#endif
    if (status == 0)
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    status = host_finish(&options, &rt, end);
    SDL_DestroyAudioStream(sound);
```
with:
```c
    status = host_finish(&options, &rt, end);
#if MOBILE
    if (end == GBA_END_ERROR)  /* the app closes when main returns: say why first */
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "gbaport", rt.error, window);
#endif
    SDL_DestroyAudioStream(sound);
```

- [ ] **Step 4: Run the whole suite**

The emulator boots here for the first time; the tests shut it down after them.

Run: `uv run pytest`
Expected: 920 passed (915 + 5). The emulator boots, runs the tests and shuts down.

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_common.h src/gbaport/runtime/host_common.c src/gbaport/runtime/host_sdl.c src/gbaport/native/android_template src/gbaport/native/device.py src/gbaport/cli.py tests/test_android_device.py tests/test_build_cli.py
git commit -m "feat: the game runs on an Android phone: gbaport build --host android --install"
```

---

### Task 5: The buttons on the phone's screen

`host_sdl.c` draws the buttons over the picture and passes the fingers to `touch.c`:
- **Drawing.** The buttons are see-through white, brighter where held. The D-pad is a circle with four arms; A and B are circles; the others are boxes. Labels use SDL's built-in 8x8 font.
- **Fingers.** SDL's finger events (x and y from 0 to 1 across the screen) become `touch_down`, `touch_move` and `touch_up`. Lifted and cancelled fingers both come up. `touch_keys` joins the keys the keyboard, the gamepad and the script hold.
- **Gamepads.** A gamepad button hides the drawn buttons, and a finger on the screen shows them again.
- **While the game is stopped,** the screen is drawn again after each event, so the buttons light up under the fingers.
- **The layout goes to the log** (`touch layout: screen WxH, D-pad at X,Y radius R, A at X,Y, ...`), so tests can touch the buttons with `adb shell input`.

`tests/gbaroms/keys_log.c` prints the keys held whenever they change. `Device` learns to touch the screen (`hold`) and to press Android's keys (`key`, which Task 6 uses).

**Files:**
- Modify: `src/gbaport/runtime/host_sdl.c`
- Modify: `src/gbaport/native/device.py` (`Device.hold`, `Device.key`)
- Create: `tests/gbaroms/keys_log.c`
- Test: `tests/test_android_device.py`

**Interfaces:**
- Consumes: Task 1's `touch_down`, `touch_move`, `touch_up`, `touch_keys`; Task 4's `Device`, `launch`.
- **Produces:**
  - **`Device.hold(x, y, ms)`:** a finger at (x, y) pixels for `ms` milliseconds (`input swipe` from a point to the same point).
  - **`Device.key(name)`:** one of Android's keys (`KEYCODE_HOME`).
  - **The `touch layout:` log line,** and the `keys_log` test ROM ("KEYS none", "KEYS A+RIGHT", ...).

- [ ] **Step 1: Write the failing test and the test ROM**

Create `tests/gbaroms/keys_log.c`:
```c
/* Prints the keys held whenever they change ("KEYS A+RIGHT", "KEYS none"), for tests
 * that press keys from outside the game (a touch screen, a gamepad). Never ends. */
#include "testlib.h"

static const char *const NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

int main(void)
{
    uint32_t last = 0;
    print("KEYS none");
    for (;;) {
        wait_vcount(160);
        uint32_t keys = ~REG_KEYINPUT & 0x3FF;
        if (keys != last) {
            char text[64];  /* no initializer: that would call memset, which ROMs lack */
            int length = 0;
            for (int k = 0; k < 10; k++) {
                if (!(keys >> k & 1))
                    continue;
                if (length)
                    text[length++] = '+';
                for (const char *c = NAMES[k]; *c; c++)
                    text[length++] = *c;
            }
            text[length] = 0;
            print("KEYS %s", length ? text : "none");
            last = keys;
        }
        wait_vcount(161);
    }
}
```

In `tests/test_android_device.py`, replace:
```python

import time
```
with:
```python

import re
import time
```

In `tests/test_android_device.py`, replace:
```python

def test_build_installs_the_app_on_the_device_and_starts_it(phone, tmp_path, monkeypatch, capsys):
```
with:
```python

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_android_device.py -k buttons`
Expected: FAIL: 1 failed, 4 deselected. `DeviceError: the app printed no line matching '^touch layout: .*' in 60 s`: the app runs the ROM but draws no buttons and prints no layout yet.

- [ ] **Step 3: Draw the buttons and follow the fingers**

In `src/gbaport/native/device.py`, replace:
```python

    def clear_log(self) -> None:
```
with:
```python

    def key(self, name: str) -> None:
        """Presses one of Android's keys (KEYCODE_HOME: leave the app for the home screen)."""
        self.shell("input", "keyevent", name)

    def hold(self, x: float, y: float, ms: int) -> None:
        """A finger on the screen at (x, y) pixels for ``ms`` milliseconds."""
        self.shell("input", "swipe", *(str(round(v)) for v in (x, y, x, y)), str(ms))

    def clear_log(self) -> None:
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
 *
 * On a phone (Android) the picture fills the screen, held sideways, as large as it fits
 * (touch.c lays it out). The ROM is the app's asset game.gba and the save file lives in
 * the app's own storage. Everything the game and the runtime print goes to the system
 * log (logcat, tag "gbaport"); a run that ends with an error shows it before the app
 * closes. The options come from the app's intent (GameActivity.java). */
#include <stdio.h>
```
with:
```c
 *
 * On a phone (Android) the picture fills the screen, held sideways, as large as it fits,
 * and the GBA's buttons are drawn over it (touch.c lays them out and follows the fingers
 * on them) until a gamepad's button is pressed; touching the screen brings them back.
 * The ROM is the app's asset game.gba and the save file lives in the app's own storage.
 * Everything the game and the runtime print goes to the system log (logcat, tag
 * "gbaport"); a run that ends with an error shows it before the app closes. The options
 * come from the app's intent (GameActivity.java). */
#include <stdio.h>
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
#if MOBILE
static TouchState touch;
static int screen_w, screen_h;  /* in pixels */
```
with:
```c
#if MOBILE
static const char *const BUTTON_NAMES[TOUCH_BUTTONS] = {"A", "B", "SELECT", "START", "R", "L"};
static const uint16_t BUTTON_KEYS[TOUCH_BUTTONS] = {1u << 0, 1u << 1, 1u << 2, 1u << 3, 1u << 8, 1u << 9};
static TouchState touch;
static int touch_hidden;       /* a gamepad is in use: the drawn buttons are out of the way */
static int screen_w, screen_h;  /* in pixels */
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
                 (TouchBox){safe.x * density, safe.y * density, safe.w * density, safe.h * density});
}
```
with:
```c
                 (TouchBox){safe.x * density, safe.y * density, safe.w * density, safe.h * density});
    const TouchLayout *l = &touch.layout;  /* in the log, for tests that touch the screen */
    printf("touch layout: screen %dx%d, D-pad at %.0f,%.0f radius %.0f", screen_w, screen_h,
           l->pad_x, l->pad_y, l->pad_radius);
    for (int b = 0; b < TOUCH_BUTTONS; b++)
        printf(", %s at %.0f,%.0f", BUTTON_NAMES[b], l->buttons[b].x + l->buttons[b].w / 2,
               l->buttons[b].y + l->buttons[b].h / 2);
    printf("\n");
}

static void fill_circle(float x, float y, float radius)
{
    enum { SIDES = 40 };
    SDL_FColor colour;
    SDL_GetRenderDrawColorFloat(renderer, &colour.r, &colour.g, &colour.b, &colour.a);
    SDL_Vertex corners[SIDES + 1] = {{{x, y}, colour, {0, 0}}};
    int triangles[3 * SIDES];
    for (int i = 0; i < SIDES; i++) {
        float angle = (float)i * 2 * SDL_PI_F / SIDES;
        corners[i + 1] = (SDL_Vertex){{x + radius * SDL_cosf(angle), y + radius * SDL_sinf(angle)},
                                      colour, {0, 0}};
        triangles[3 * i] = 0;
        triangles[3 * i + 1] = 1 + i;
        triangles[3 * i + 2] = 1 + (i + 1) % SIDES;
    }
    SDL_RenderGeometry(renderer, NULL, corners, SIDES + 1, triangles, 3 * SIDES);
}

/* `text` in SDL's 8x8 font, `size` pixels tall, centred on (x, y). */
static void label(const char *text, float x, float y, float size)
{
    float scale = size / 8;
    SDL_SetRenderScale(renderer, scale, scale);
    SDL_RenderDebugText(renderer, (x - 4 * (float)strlen(text) * scale) / scale,
                        (y - 4 * scale) / scale, text);
    SDL_SetRenderScale(renderer, 1, 1);
}

static void shade(int pressed)
{
    SDL_SetRenderDrawColor(renderer, 255, 255, 255, pressed ? 110 : 45);
}

/* The buttons, see-through, brighter where `keys` holds them. */
static void draw_buttons(uint16_t keys)
{
    const TouchLayout *l = &touch.layout;
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND);
    float r = l->pad_radius, arm = r / 3;
    shade(0);
    fill_circle(l->pad_x, l->pad_y, r);
    SDL_FRect arms[4] = {  /* right, left, up, down: GBA key bits 4 to 7 */
        {l->pad_x + arm / 2, l->pad_y - arm / 2, r - arm / 2, arm},
        {l->pad_x - r, l->pad_y - arm / 2, r - arm / 2, arm},
        {l->pad_x - arm / 2, l->pad_y - r, arm, r - arm / 2},
        {l->pad_x - arm / 2, l->pad_y + arm / 2, arm, r - arm / 2},
    };
    for (int d = 0; d < 4; d++) {
        shade(keys >> (4 + d) & 1);
        SDL_RenderFillRect(renderer, &arms[d]);
    }
    for (int b = 0; b < TOUCH_BUTTONS; b++) {
        TouchBox box = l->buttons[b];
        float x = box.x + box.w / 2, y = box.y + box.h / 2;
        shade((keys & BUTTON_KEYS[b]) != 0);
        if (b == TOUCH_A || b == TOUCH_B) {
            fill_circle(x, y, box.w / 2.8f);  /* the circle in its box (touch.c's A_B_REACH) */
            label(BUTTON_NAMES[b], x, y, box.h * 0.3f);
        } else {
            SDL_RenderFillRect(renderer, &(SDL_FRect){box.x, box.y, box.w, box.h});
            label(BUTTON_NAMES[b], x, y, box.h * 0.35f);
        }
    }
}
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
#if MOBILE
    else if (event->type == SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED ||
             event->type == SDL_EVENT_WINDOW_SAFE_AREA_CHANGED)
        lay_out();
#endif
}

/* The keys held on the keyboard, the gamepad and in the script. */
static uint16_t held_keys(void)
```
with:
```c
#if MOBILE
    const SDL_TouchFingerEvent *finger = &event->tfinger;  /* x and y: 0 to 1 across the screen */
    switch (event->type) {
    case SDL_EVENT_FINGER_DOWN:
        touch_down(&touch, finger->fingerID, finger->x * screen_w, finger->y * screen_h);
        touch_hidden = 0;
        break;
    case SDL_EVENT_FINGER_MOTION:
        touch_move(&touch, finger->fingerID, finger->x * screen_w, finger->y * screen_h);
        break;
    case SDL_EVENT_FINGER_UP:
    case SDL_EVENT_FINGER_CANCELED:
        touch_up(&touch, finger->fingerID);
        break;
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN:
        touch_hidden = 1;
        break;
    case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
    case SDL_EVENT_WINDOW_SAFE_AREA_CHANGED:
        lay_out();
        break;
    default:
        break;
    }
#endif
}

/* The keys held on the keyboard, the gamepad, the touch screen and in the script. */
static uint16_t held_keys(void)
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    }
    return keys;
```
with:
```c
    }
#if MOBILE
    keys |= touch_keys(&touch);
#endif
    return keys;
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    SDL_RenderTexture(renderer, texture, NULL, &(SDL_FRect){s.x, s.y, s.w, s.h});
#else
```
with:
```c
    SDL_RenderTexture(renderer, texture, NULL, &(SDL_FRect){s.x, s.y, s.w, s.h});
    if (!touch_hidden)
        draw_buttons(touch_keys(&touch));
#else
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
            handle(&event);
        if (held_keys() != before) {
```
with:
```c
            handle(&event);
#if MOBILE
        present();  /* the buttons light up under the fingers */
        SDL_RenderPresent(renderer);
#endif
        if (held_keys() != before) {
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 921 passed (920 + 1).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_sdl.c src/gbaport/native/device.py tests/gbaroms/keys_log.c tests/test_android_device.py
git commit -m "feat: the phone draws the GBA's buttons over the picture and the fingers on them press the keys"
```

---

### Task 6: The save through the app's life, and the frame rate

**On every host:**
- **The save at Stop.** The window host stores the save when the game stops (the BIOS Stop call) and waits for a key: nothing changes the save until then, and no frames pass to store it once a second.
- **`host_store_save`** is now public (it was `host_common.c`'s `store_save`).

**On a phone:**
- **Lifecycle events** go to an event watcher. SDL passes them to watchers only, as they happen, on the game's thread. In the background the next event pump waits until the app comes back, so the game is paused.
  - **Going to the background** (`SDL_EVENT_WILL_ENTER_BACKGROUND`) stores the save, as does `SDL_EVENT_TERMINATING`: from then on Android may kill the app at any time. The fingers on the screen are forgotten.
  - **Coming back** (`SDL_EVENT_DID_ENTER_FOREGROUND`) restarts the frame pacing and the frame-rate count, so the game does not rush to catch up.
- **The frame rate.** Every 600 frames the host prints `F frames a second; the game took M ms a frame`. M counts everything but the wait for the next frame's time.

The runtime moves to a file-level `static GbaRuntime rt` in `host_sdl.c`, so the watcher can reach it.

**Test ROMs and helpers:**
- `tests/gbaroms/save_counter.c` prints the count its SRAM holds (`SAVED n`), then counts on, a frame at a time, writing each count to SRAM (`COUNT n`).
- `romtest.start_program` starts a native program without waiting for it.

**Files:**
- Modify: `src/gbaport/runtime/host_common.h`, `host_common.c` (`host_store_save`)
- Modify: `src/gbaport/runtime/host_sdl.c`
- Create: `tests/gbaroms/save_counter.c`
- Modify: `tests/romtest.py` (`start_program`)
- Test: `tests/runtime/test_saves.py`, `tests/test_android_device.py`

**Interfaces:**
- Consumes: Task 4's `Device`, the phone branch; Task 5's `Device.key` and `keys_log` ROM.
- **Produces:**
  - **The host:** `void host_store_save(HostOptions *, GbaRuntime *)` and the frame-rate log line.
  - **Test helpers:** `romtest.start_program(command, env=None) -> subprocess.Popen` and the `save_counter` test ROM.

- [ ] **Step 1: Write the failing tests and the test ROM**

Create `tests/gbaroms/save_counter.c`:
```c
/* A game that saves all the time: it prints the count its save holds ("SAVED n", 0 for a
 * blank save), then counts frames on from there, writing each new count to SRAM and
 * printing it ("COUNT n"). Never ends. The library ID string tells gbaport it has SRAM. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

#define SRAM ((volatile uint8_t *)0x0E000000)

static uint32_t load(void)
{
    uint32_t count = 0;
    for (int i = 0; i < 4; i++)
        count |= (uint32_t)SRAM[i] << (8 * i);
    return count == 0xFFFFFFFF ? 0 : count;
}

int main(void)
{
    uint32_t count = load();
    print("SAVED %u", count);
    for (;;) {
        wait_vcount(160);
        count++;
        for (int i = 0; i < 4; i++)
            SRAM[i] = (uint8_t)(count >> (8 * i));
        print("COUNT %u", count);
        wait_vcount(0);  /* printing can take longer than a line: wait for the next frame */
    }
}
```

In `tests/romtest.py`, replace:
```python

def run_rom(
```
with:
```python

def start_program(command: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
    """Start a native program without waiting for it (retried as run_program is)."""
    for attempt in range(5):
        try:
            return subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=env)
        except OSError as error:
            if getattr(error, "winerror", None) != 4551 or attempt == 4:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def run_rom(
```

In `tests/runtime/test_saves.py`, replace:
```python
import os

import pytest
from romtest import build_test_rom, run_rom, run_test

from gbaport.analysis.analyze import analyze_rom
```
with:
```python
import os
import time

import pytest
from romtest import build_test_rom, native_program, run_rom, run_test, start_program

from gbaport.analysis.analyze import analyze_rom
```

In `tests/runtime/test_saves.py`, replace:
```python
    assert "gba_save_type = 3u;  /* flash128k */" in rom_identity(rom.data, SaveType.FLASH128K)
```
with:
```python
    assert "gba_save_type = 3u;  /* flash128k */" in rom_identity(rom.data, SaveType.FLASH128K)


def test_the_window_host_stores_the_save_when_the_game_stops(tmp_path):
    """Stopped, a game changes nothing until a key wakes it: its save is stored then, so a
    program killed while waiting (a phone's app is killed in the background) keeps it."""
    rom = build_test_rom("save_sram")  # writes its save, then stops at once
    (tmp_path / "game.gba").write_bytes(rom.data)
    save = tmp_path / "game.sav"
    env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy", "SDL_AUDIO_DRIVER": "dummy"}
    command = [str(native_program(rom, "sdl")), str(tmp_path / "game.gba"), "--save", str(save)]
    process = start_program(command, env)
    try:
        deadline = time.monotonic() + 30
        while not save.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert process.poll() is None, "the program waits for a key"
        assert save.read_bytes()[0x100:0x108] == SIGNATURE
    finally:
        process.kill()
        process.wait()
```

In `tests/test_android_device.py`, replace:
```python

def test_build_installs_the_app_on_the_device_and_starts_it(phone, tmp_path, monkeypatch, capsys):
```
with:
```python

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


def test_build_installs_the_app_on_the_device_and_starts_it(phone, tmp_path, monkeypatch, capsys):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_saves.py tests/test_android_device.py`
Expected: FAIL: 3 failed, 19 passed.
- `test_the_window_host_stores_the_save_when_the_game_stops`: `FileNotFoundError` for its `game.sav`. The save is stored only when the program ends.
- `test_going_to_the_background_stores_the_save_and_pauses_the_game`: `assert N == M`, with N the count of the last once-a-second store and below M, the count when the app left. Two validation runs gave `assert 179 == 211` and `assert 239 == 250`.
- `test_the_app_keeps_the_gbas_frame_rate_and_says_so`: `DeviceError` that no frame-rate line came.
- `test_the_save_survives_the_app_being_killed` passes already: the save is stored once a second.

- [ ] **Step 3: Store the save as the app comes and goes; count the frames**

In `src/gbaport/runtime/host_common.c`, replace:
```c
 * leaves the previous save as it was. */
static void store_save(HostOptions *o, GbaRuntime *rt)
{
```
with:
```c
 * leaves the previous save as it was. */
void host_store_save(HostOptions *o, GbaRuntime *rt)
{
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
    if (rt->frames % 60 == 0)
        store_save(o, rt);
    if (o->frame_limit && rt->frames >= o->frame_limit)
```
with:
```c
    if (rt->frames % 60 == 0)
        host_store_save(o, rt);
    if (o->frame_limit && rt->frames >= o->frame_limit)
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
{
    store_save(o, rt);
    FILE *f = o->audio_file;
```
with:
```c
{
    host_store_save(o, rt);
    FILE *f = o->audio_file;
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
void host_frame(HostOptions *o, GbaRuntime *rt);
/* While the game is stopped: applies the next scripted press; 0 when none is left. */
```
with:
```c
void host_frame(HostOptions *o, GbaRuntime *rt);
/* Stores the save file now, if the game changed its save since it was last stored
 * (host_frame does once a second, host_finish at the end). */
void host_store_save(HostOptions *o, GbaRuntime *rt);
/* While the game is stopped: applies the next scripted press; 0 when none is left. */
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
 * window ends the run with exit status 0. While the game is stopped (the BIOS Stop call)
 * the screen is dark and a key press wakes it, if the game asked for that; in a run
 * limited by --frames, a Stop that no scripted press wakes ends the run instead. The other
 * options and exit statuses are those of host_headless.c.
 *
```
with:
```c
 * window ends the run with exit status 0. While the game is stopped (the BIOS Stop call)
 * the screen is dark and a key press wakes it, if the game asked for that; the save is
 * stored as it stops, since nothing changes it until then. In a run limited by --frames,
 * a Stop that no scripted press wakes ends the run instead. The other options and exit
 * statuses are those of host_headless.c.
 *
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
 * The ROM is the app's asset game.gba and the save file lives in the app's own storage.
 * Everything the game and the runtime print goes to the system log (logcat, tag
 * "gbaport"); a run that ends with an error shows it before the app closes. The options
 * come from the app's intent (GameActivity.java). */
#include <stdio.h>
```
with:
```c
 * The ROM is the app's asset game.gba and the save file lives in the app's own storage.
 * The save is stored when the app goes to the background (Android may kill it there at
 * any time) and when it closes, besides once a second while it changes, so it survives
 * the app being killed; in the background the game is paused. Everything the game and the
 * runtime print goes to the system log (logcat, tag "gbaport"), with the frame rate and
 * how much of each frame's time the game took every ten seconds; a run that ends with an
 * error shows it before the app closes. The options come from the app's intent
 * (GameActivity.java). */
#include <stdio.h>
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
static HostOptions options;
static SDL_Window *window;
```
with:
```c
static HostOptions options;
static GbaRuntime rt;
static SDL_Window *window;
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
static int touch_hidden;       /* a gamepad is in use: the drawn buttons are out of the way */
static int screen_w, screen_h;  /* in pixels */

/* stdout and stderr go nowhere on Android: a thread passes their lines to logcat. */
```
with:
```c
static int touch_hidden;       /* a gamepad is in use: the drawn buttons are out of the way */
static int screen_w, screen_h;  /* in pixels */
static Uint64 awake, busy, report_start;  /* for the frame rate report */
static unsigned report_frames;

/* stdout and stderr go nowhere on Android: a thread passes their lines to logcat. */
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
        }
    }
}
#endif

static void handle(const SDL_Event *event)
```
with:
```c
        }
    }
}

/* Every 600 frames (ten seconds): how many frames a second came, and how long the game
 * took a frame (the rest of the frame's time goes to waiting for the next one). `waited`
 * is when this frame's wait began; `awake`, when the last one ended. */
static void report_rate(Uint64 waited)
{
    if (awake)
        busy += waited - awake;
    if (report_frames == 0)
        report_start = waited;
    if (++report_frames == 601) {
        double seconds = (double)(waited - report_start) / 1e9;
        printf("%.2f frames a second; the game took %.1f ms a frame\n", 600 / seconds,
               (double)busy / 600 / 1e6);
        report_frames = 1;
        report_start = waited;
        busy = 0;
    }
}
#endif

static void handle(const SDL_Event *event)
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
#endif
}

/* The keys held on the keyboard, the gamepad, the touch screen and in the script. */
```
with:
```c
#endif
}

#if MOBILE
/* The app's comings and goings. SDL passes them to watchers only, as they happen, on the
 * game's thread (the one pumping the events); in the background the next pump waits
 * until the app comes back, so the game is paused. */
static bool on_app_event(void *user, SDL_Event *event)
{
    (void)user;
    switch (event->type) {
    case SDL_EVENT_WILL_ENTER_BACKGROUND:  /* Android may kill the app from now on */
    case SDL_EVENT_TERMINATING:
        host_store_save(&options, &rt);
        touch.count = 0;  /* the fingers on the screen now will not come up here */
        break;
    case SDL_EVENT_DID_ENTER_FOREGROUND:
        paced = 0;  /* the clocks stood still: do not rush to catch up */
        awake = 0;
        report_frames = 0;
        break;
    default:
        break;
    }
    return true;
}
#endif

/* The keys held on the keyboard, the gamepad, the touch screen and in the script. */
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    SDL_RenderPresent(renderer);
    pace();
    host_frame(&options, rt);
```
with:
```c
    SDL_RenderPresent(renderer);
#if MOBILE
    Uint64 waited = SDL_GetTicksNS();
    pace();
    report_rate(waited);
    awake = SDL_GetTicksNS();
#else
    pace();
#endif
    host_frame(&options, rt);
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
        return 0;
    uint16_t before = held_keys();
```
with:
```c
        return 0;
    host_store_save(&options, rt);  /* nothing changes it until a key wakes the game */
    uint16_t before = held_keys();
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
    lay_out();
#else
```
with:
```c
    lay_out();
    SDL_AddEventWatch(on_app_event, NULL);
#else
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
{
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
```
with:
```c
{
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 925 passed (921 + 4).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_common.h src/gbaport/runtime/host_common.c src/gbaport/runtime/host_sdl.c tests/gbaroms/save_counter.c tests/romtest.py tests/runtime/test_saves.py tests/test_android_device.py
git commit -m "feat: the save survives the app being killed, and the phone reports its frame rate"
```

---

### Task 7: Input files on the device, the user's game, and the docs

**`--input FILE` with `--install`.** The game plays an input file this time. The file is read first, so a bad one stops the command with its line before anything is built.
- **How it reaches the game.** The presses, as Python reads them (as `gbaport verify` does), go into the app's own storage through `adb push` and `run-as` (the debug build lets adb in), as the app's `--input`.
- **Restarts.** `--install` now stops the app before starting it, so the new build starts fresh.
- **Errors.** `--input` without `--install` is an error.

**The README** gets "Playing on an Android phone" and a note on the Android tests.

**The spec:**
- the saves and input bullets;
- a verification row for Android;
- the toolchain line, with the versions this plan pins.

**Then the user's game:**
- on the emulator, built and installed through the command with its input file;
- on the user's phone, which is the roadmap's acceptance.

**Files:**
- Modify: `src/gbaport/cli.py` (`--input`)
- Modify: `src/gbaport/native/device.py` (`Device.put_file`)
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`
- Test: `tests/test_build_cli.py`, `tests/test_android_device.py`

**Interfaces:**
- Consumes: Task 4's `the_device`, `Device.start`; `gbaport.inputs`' `load_input` and `format_input`.
- **Produces:** `Device.put_file(app, path) -> str` (the file's name in the app's storage) and `gbaport build ... --host android --install --input FILE`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_android_device.py`, replace:
```python

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
```
with:
```python

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
```

In `tests/test_build_cli.py`, replace:
```python
    assert "functions" not in printed.out  # it stopped before recompiling
```
with:
```python
    assert "functions" not in printed.out  # it stopped before recompiling


def test_an_input_file_is_for_install(tmp_path, capsys):
    rom_path = tmp_path / "hello.gba"
    rom_path.write_bytes(build_test_rom("hello").data)
    (tmp_path / "game.input").write_text("10 A\n", encoding="utf-8")
    command = ["build", str(rom_path), "--host", "android", "--input", str(tmp_path / "game.input")]
    assert main(command) == 1
    assert "--input is for --install" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_build_cli.py tests/test_android_device.py -k "input or build"`
Expected: FAIL: 2 failed, 7 passed, 7 deselected. Both end in `SystemExit: 2`, with `gbaport: error: unrecognized arguments: --input ...`.

- [ ] **Step 3: --input, and the docs**

In `README.md`, replace:
```markdown

## Commands
```
with:
```markdown

The Android tests build test ROMs' apps (the first run fetches what `gbaport build --host
android` needs, below) and run them on gbaport's own Android emulator: a 720x1280 phone
(Android 15, x86_64) with no window and no sound, drawn by the PC's graphics card and run
by Windows Hypervisor Platform. The tests boot it when it is not running (a minute or two;
it lives in `%LOCALAPPDATA%\gbaport\android-avd`) and shut it down after them. Run them
one test run at a time: two runs would drive the same emulator and app.

## Commands
```

In `README.md`, replace:
```markdown
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]
```
with:
```markdown
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport build roms/mygame.gba --host android [--abi x86_64] [--install [--input FILE]]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]
```

In `README.md`, replace:
```markdown
`[rom] save` says) lives in a save file: `--save PATH`, by default the ROM's path with
`.sav` (`roms/mygame.sav`, which git ignores). It is written once a second while the game
changes it and again when the program ends, also after a runtime error. A save file of
the wrong size is refused and left as it is.

Windows' Smart App Control judges every newly built program by its content and refuses
```
with:
```markdown
`[rom] save` says) lives in a save file: `--save PATH`, by default the ROM's path with
`.sav` (`roms/mygame.sav`, which git ignores). It is written once a second while the game
changes it, when the game stops (the BIOS Stop call, in the window), and again when the
program ends, also after a runtime error. A save file of the wrong size is refused and
left as it is.

Windows' Smart App Control judges every newly built program by its content and refuses
```

In `README.md`, replace:
```markdown
EEPROM take as long as in mGBA. So the game reaches each picture when it does in mGBA,
give or take a frame where an interrupt comes in at a loop or a return instead of at once.

## Checking a game against mGBA
```
with:
```markdown
EEPROM take as long as in mGBA. So the game reaches each picture when it does in mGBA,
give or take a frame where an interrupt comes in at a loop or a return instead of at once.

## Playing on an Android phone

    uv run python -m gbaport.cli build roms/mygame.gba --host android --install

builds the game's app, installs it on the phone connected over USB and starts it. Turn on
USB debugging in the phone's developer options first, and allow this computer when the
phone asks. Without `--install`, the command builds `games/<game_code>/build/<game_code>.apk`
for phones (arm64-v8a; `--abi x86_64` builds it for the Android emulator on a PC); with
`--install` it builds for the connected device's processor. With several devices
connected, `ANDROID_SERIAL` names the one to use. `--input FILE`, with `--install`, has
the game play an input file this time. The app is `org.gbaport.<game_code>`, named with
the cartridge's title, and each build replaces the last.

The first Android build fetches about 4 GB into `%LOCALAPPDATA%\gbaport`:
- **The Android SDK** (`android-sdk`): Google's command-line tools and, through them, the
  Android 15 platform (API 35), build tools 35.0.0, NDK r29 and CMake 3.31.6. Installing
  them accepts Google's Android SDK licence (https://developer.android.com/studio/terms),
  which gbaport says when it does.
- **Gradle 8.12.1**, and through it the Android Gradle plugin 8.7.3 (`gradle-home`).
  Gradle needs a JDK 17 or newer (`JAVA_HOME`, or `java` on the PATH).
- **SDL3 3.4.18's source**, which the app builds SDL3 from.

The NDK's clang compiles a large game's code for minutes the first time (Dragon Ball GT
Transformation: about five); later builds compile only what changed. The Gradle project
stays in `games/<game_code>/build/android`, and Android Studio can open it.

The app is the window host built for Android, with the ROM inside it. It fills the
screen, held sideways, and draws the GBA's buttons over the picture:
- the D-pad on the left: slide a finger around it; a finger that came down on it keeps
  steering it wherever it goes;
- A and B on the right (a finger between them holds both);
- L and R in the top corners, Select and Start at the bottom.

A gamepad works as on the desktop. Pressing one of its buttons hides the drawn ones, and
touching the screen brings them back. The back button leaves the app as the home button
does.

The save lives in the app's own storage. It is stored once a second while the game
changes it, when the game stops (the BIOS Stop call), when the app goes to the
background, where Android may kill it at any time, and when the app ends. In the
background the game is paused. Uninstalling the app deletes its save.

What the game and the runtime print goes to Android's log, with the frame rate every ten
seconds:

    %LOCALAPPDATA%\gbaport\android-sdk\platform-tools\adb logcat -s gbaport

    59.73 frames a second; the game took 3.1 ms a frame

A runtime error shows its message on the screen; the app ends when it is closed.

## Checking a game against mGBA
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- **Saves.** SRAM, Flash (with its command state machine) and EEPROM (serial protocol over
  DMA) modelled at the memory-access level, because game code drives the chip protocol
  directly. Persisted to a file per game.
- **Input.** Touch overlay and game controllers write `KEYINPUT`.

## Per-game configuration
```
with:
```markdown
- **Saves.** SRAM, Flash (with its command state machine) and EEPROM (serial protocol over
  DMA) modelled at the memory-access level, because game code drives the chip protocol
  directly. Persisted to a file per game: once a second while it changes, when the game
  stops, at the end, and on a phone when the app goes to the background, where the
  system may kill it (Plan 8).
- **Input.** Touch overlay and game controllers write `KEYINPUT`. On a phone the
  buttons are drawn over the picture, held sideways, and a gamepad hides them (Plan 8).

## Per-game configuration
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
| Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
| Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |
```
with:
```markdown
| Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
| Android (Plan 8) | Test ROMs on the Android emulator (dev only) | The app runs them; drawn buttons press keys; saves survive the app being killed; the frame rate holds |
| Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
  user's cache folder) — Plan 4c.
- Android SDK + NDK r27 or newer (Android Studio or `sdkmanager`) — Plan 8.
- macOS with Xcode 16 or newer, or a macOS CI runner, plus an Apple developer account — Plan 9.
```
with:
```markdown
  user's cache folder) — Plan 4c.
- The Android SDK, fetched by gbaport into the cache folder (Plan 8): Google's
  command-line tools 23.0, then platform 35, build tools 35.0.0, NDK r29 (29.0.14206865)
  and CMake 3.31.6 through their `sdkmanager`, which accepts Google's Android SDK licence;
  for the tests, the emulator and an Android 15 x86_64 system image (Windows Hypervisor
  Platform). Gradle 8.12.1 with the Android Gradle plugin 8.7.3, as SDL3's android-project
  uses, on a JDK 17 or newer; SDL3 3.4.18's source for the app's SDL3 and Java code.
- macOS with Xcode 16 or newer, or a macOS CI runner, plus an Apple developer account — Plan 9.
```

In `src/gbaport/cli.py`, replace:
```python
    )
    build.set_defaults(handler=_run_build)
```
with:
```python
    )
    build.add_argument(
        "--input",
        help="android, with --install: the input file the game plays this time "
        "(see gbaport/inputs.py)",
    )
    build.set_defaults(handler=_run_build)
```

In `src/gbaport/cli.py`, replace:
```python
        raise ValueError("--abi and --install are for --host android")
    device = the_device() if args.install else None  # before the long build: is one there?
```
with:
```python
        raise ValueError("--abi and --install are for --host android")
    if args.input and not args.install:
        raise ValueError("--input is for --install: the game plays it on the device")
    if args.input:
        load_input(args.input)  # a bad input file stops here, with its line
    device = the_device() if args.install else None  # before the long build: is one there?
```

In `src/gbaport/cli.py`, replace:
```python
        return 0
    device.install(apk)
    device.start(application_id(header.game_code))
    print(f"installed it on {device.serial} and started it")
    return 0
```
with:
```python
        return 0
    app = application_id(header.game_code)
    device.install(apk)
    device.stop(app)  # a fresh start, even if an older build is running
    options = ""
    if args.input:  # the presses as Python reads them (see gbaport/verify.py)
        with tempfile.TemporaryDirectory() as folder:
            canonical = Path(folder) / "game.input"
            canonical.write_text(format_input(load_input(args.input)), encoding="utf-8")
            options = f"--input {device.put_file(app, canonical)}"
    device.start(app, options)
    print(f"installed it on {device.serial} and started it"
          + (f", playing {args.input}" if args.input else ""))
    return 0
```

In `src/gbaport/native/device.py`, replace:
```python
        """Deletes the app's files, its save among them."""
        self.shell("pm", "clear", app)

    def running(self, app: str) -> bool:
```
with:
```python
        """Deletes the app's files, its save among them."""
        self.shell("pm", "clear", app)

    def put_file(self, app: str, path: Path) -> str:
        """Copies ``path`` into the app's own storage (its debug build lets adb in);
        returns its name there, for the app's command line."""
        staged = f"/data/local/tmp/gbaport-{path.name}"
        self.adb("push", str(path), staged)
        self.shell("run-as", app, "mkdir", "-p", "files")
        self.shell("run-as", app, "cp", staged, f"files/{path.name}")
        self.shell("rm", staged)
        return f"/data/user/0/{app}/files/{path.name}"

    def running(self, app: str) -> bool:
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 927 passed (925 + 2).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: The user's game on the emulator**

The emulator must be running. The tests shut it down after them, so boot it again:

```bash
uv run python -c "from gbaport.native.device import start_emulator; print(start_emulator()[0].serial)"
```

Then build, install and play, from the repo root. The first build compiles the game's 335k lines with the NDK, which takes about five minutes:

```bash
ANDROID_SERIAL=emulator-5584 uv run python -m gbaport.cli build roms/mygame.gba --host android --abi x86_64 --install --input games/BT4E/first-fight.input --out build/BT4E-android
```

Expected: `lift issues  0`, `built build\BT4E-android\build\BT4E.apk (x86_64)` and `installed it on emulator-5584 and started it, playing games/BT4E/first-fight.input`. The prototype took 3 minutes 22 seconds, with SDL3 compiled before.

After 80 seconds, read the app's log:

```bash
"$LOCALAPPDATA/gbaport/android-sdk/platform-tools/adb" -s emulator-5584 logcat -d -s gbaport | grep -E "frames a second|error"
```

Expected (validated before this plan was approved): seven `frames a second` lines, 59.70 to 59.75 frames a second, the game taking 2.8 to 6.0 ms a frame. They are followed by `error: no recompiled code at 0x08009e0e (Thumb state, lr = 0x08009d23): ...` at frame 4300, about a second after the input file ends (Known limitations).

- [ ] **Step 6: The user's game on the user's phone**

This step needs the user. Ask them to connect their phone over USB with USB debugging on, and to allow this computer when the phone asks. Then check that adb sees it (`adb devices`), and run, with `ANDROID_SERIAL` set to the phone's serial if the emulator is running too:

```bash
uv run python -m gbaport.cli build roms/mygame.gba --host android --install --input games/BT4E/first-fight.input --out build/BT4E-android
```

Expected: `built build\BT4E-android\build\BT4E.apk (arm64-v8a)` and `installed it on <serial> and started it, playing games/BT4E/first-fight.input`. The first arm64 build takes about five minutes more.

After 80 seconds, run the logcat command above with `-s <serial>`. Expected: every `frames a second` line after the first between 59.5 and 60.0, and then the coverage error at frame 4300 (Known limitations). Record the lines in the ledger.

The user may then play themselves. Opening the app from the phone's launcher starts it with no input file.
- **The sound:** it plays through the phone's speaker or headphones (the emulator's tests run silent).
- **The buttons:** the D-pad, A and B, and whether a gamepad hides them.
- **The save:** a game that saves, then kill the app from the recent apps, and open it again.

If no phone is available, ledger that and carry on: the user does this step later. The rest of the plan does not depend on it.

- [ ] **Step 7: Commit**

```bash
git add src/gbaport/cli.py src/gbaport/native/device.py README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md tests/test_build_cli.py tests/test_android_device.py
git commit -m "feat: gbaport build --install plays an input file on the device; Android in the README and the spec"
```

---

## Done criteria for Plan 8

- `uv run pytest` passes 927 tests and `uv run ruff check src tests` is clean.
- **`gbaport build ROM --host android [--abi ABI] [--install [--input FILE]]`** builds the game's Gradle project and APK. With `--install`, it installs the app on the connected phone or emulator and starts it. The SDK, Gradle and SDL3's source come into the cache folder the first time.
- **On the emulator, test ROMs show that:**
  - the app runs the game and shows runtime errors;
  - the drawn buttons press the keys;
  - the save survives the app being killed, and going to the background stores it and pauses the game;
  - the app keeps 59.73 frames a second;
  - it ends with the game and starts afresh.
- **The user's game** plays its input file into its first fight at full speed on the emulator, and on the user's phone if it was connected (Task 7, Step 6).
