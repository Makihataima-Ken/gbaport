# Plan 4c: Desktop Host and CPU Test ROMs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompiled games run in a desktop window (SDL3) with keyboard and gamepad input, at the GBA's frame rate, and wake from Stop when a key is pressed. jsmolka's public CPU test ROMs pass when recompiled.

**Architecture:**
- **The run loop does not change.** The runtime still runs the game to completion and calls the host once a frame, at VBlank start.
- **Shared host code.** A new `host_common.c` holds what both hosts share: the command line, the ROM and save files, scripted key presses, the frame limit and the end of a run.
- **The window host.** `host_sdl.c` adds the window, input and frame pacing. It links SDL3 3.4.18 statically. CMake and Ninja build SDL3 from source once, into the user's cache folder.
- **The screen.** Until the Plan 5 renderer, the screen shows the bitmap modes only.
- **Fixes first.** The public test ROMs found four lifter and runtime defects, which the first tasks fix.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; a C11 runtime built with clang 23; SDL 3.4.18 (CMake ≥ 3.28 + Ninja, `FetchContent`); jsmolka/gba-tests at commit `a7113b67e63f83a9b321696ddd7042ccfad6c881` (MIT licence).

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Roadmap row P4c, verbatim: "P4c Desktop host | SDL3 window, input, frame pacing, keypad wake-up | CPU test ROMs pass when recompiled; a test ROM runs in a window".
  - Toolchain: "Python tooling, C11 runtime, clang everywhere. Analysis and code generation are Python 3.13 (managed by uv). Generated code and runtime are C11 built with clang".
  - "SDL3 platform layer for window, input, audio and app lifecycle on desktop, Android and iOS, so one host codebase serves all three." (`host_common.c` keeps what is not SDL-specific out of `host_sdl.c`.)
  - "CMake ≥ 3.28 and Ninja (bundled with the MSVC Build Tools; elsewhere `winget install Kitware.CMake Ninja-build.Ninja`) — Plan 4c." and "SDL3 (fetched by CMake `FetchContent`) — Plan 4c."
  - "No ROM-derived bytes in git." Public test suites: "licence checked before vendoring". The repository's `.gitignore` ignores every `*.gba`, so jsmolka's MIT-licensed ROMs are downloaded at test time, pinned by commit and SHA-1; only their `game.toml` files are committed.
  - "Emulators are dev-time test oracles only." Where hardware documentation is unclear, the runtime does what mGBA does.
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Tests never open a window: window-host runs use `SDL_VIDEO_DRIVER=dummy`. Only Task 9's smoke step opens a real window, for a few seconds.
- **Commands:** use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher. Run `uv run pytest` and `uv run ruff check src tests` as separate commands.

## Review Focus

1. **SDL3 cannot be built.** Causes: the first build runs offline, or CMake or Ninja is missing.
   - `gbaport build` stops with a message that names what is missing and how to get it, and leaves no half-installed SDL3 behind.
   - `--host headless` still works.
   - Pinned in Task 8 (`test_missing_cmake_and_ninja_say_how_to_get_them`, `test_a_failed_download_stops_the_build_with_cmake_s_output`).
2. **A key already held when the game asks for it.** A game writes KEYCNT, or stops, while the player holds a chosen key: it gets the interrupt at once, as in mGBA, instead of sleeping until the next press. Pinned in Task 7 (`test_a_key_held_from_the_start_requests_the_interrupt_once_keycnt_asks`).
3. **A save written just before a runtime error, in the window host.** The bytes reach the save file, as they do in the headless host. Pinned in Task 8 (`test_the_window_host_stores_a_save_written_before_a_runtime_error`).
4. **A public test ROM that is not the file its config was written for.** Causes: a changed upstream file, or a corrupted download. The download is refused, and so is a build from the wrong bytes; nothing tests a different ROM in silence. Pinned in Task 2 (the SHA-1 check in `jsmolka_rom`, `test_a_rom_that_is_not_the_one_its_config_names_is_refused`).
5. **Window sizes out of range** (`--scale 0`, `--scale 17`). The host refuses them with a usage error, instead of opening an empty or a huge window. Pinned in Task 8 (`test_the_window_host_refuses_a_bad_scale`).

## Known limitations (deliberate; later plans)

- **The picture.** Only the bitmap modes 3, 4 and 5 are drawn (BG2, no effects). A game that draws with tiles shows its backdrop colour until the scanline renderer (Plan 5).
- **No sound** until Plan 6.
- **Real desktops are not under automated test.** Real windows, resizing, high-DPI screens and real gamepads are outside the automated tests, which use SDL's dummy video driver. Task 9's smoke step opens one real window.
- **Frame pacing is timer-based, without vsync.** On a 60 Hz display, 59.73 frames a second repeats a frame now and then, and tearing is possible.
- **Input.** The key mapping is fixed, and only the first gamepad is used.
- **Keypad interrupt timing.** The keypad interrupt follows mGBA's rules, which GBATEK does not fully settle. Only the keypad wakes a stopped game: there is no link cable or cartridge interrupt.
- **Test ROMs not run.**
  - `nes.gba` copies its code to VRAM and rewrites instructions there while they run, which a static recompiler cannot follow.
  - `unsafe.gba` fails on real hardware, according to its own README.
  - The `ppu` tests need Plan 5.
- **HardReset still sets the frame count back to 0** (a deferred minor from Plan 4b's review).

---

### Task 1: The lifter test kit rebuilds harnesses Windows refuses

Later tasks change `gba_cpu.h` and the lifter. That rebuilds every lifter test harness (`tests/liftkit.py`), and Windows' Smart App Control refuses some freshly built programs for good. `gbaport build` already links a refused program again with a salt (Plan 4b); this task does the same in the lifter test kit.

**Files:**
- Modify: `tests/liftkit.py`
- Test: `tests/lift/test_kit.py`

**Interfaces:**
- Consumes: `gbaport.native.build._starts(program) -> bool` and `SALTED_REBUILDS` (Plan 4b).
- **Produces, in `liftkit`:**
  - `build(source) -> Path` compiles again with a new `salt.c` until Windows lets the harness start, at most `SALTED_REBUILDS` extra times.
  - It caches a harness only once it has started: a `started` file sits next to it.
  - `liftkit.native` is the `gbaport.native.build` module.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-04c-desktop-host
```

- [ ] **Step 2: Write the failing test**

In `tests/lift/test_kit.py`, replace:
```python
from liftkit import Case, differences, run_compiled, run_oracle
```
with:
```python
import liftkit
from liftkit import Case, differences, run_compiled, run_oracle
```

In `tests/lift/test_kit.py`, replace:
```python
    assert differences(a, b) == ["r0 0x00000005 != 0x00000006"]
```
with:
```python
    assert differences(a, b) == ["r0 0x00000005 != 0x00000006"]


def test_a_harness_windows_refuses_is_compiled_again_with_a_salt(monkeypatch, tmp_path):
    verdicts = iter([False, True])  # Smart App Control refuses the first file, takes the next
    builds = []

    def starts(program):
        builds.append(program.read_bytes())
        return next(verdicts)

    monkeypatch.setattr(liftkit, "CACHE", tmp_path)
    monkeypatch.setattr(liftkit.native, "_starts", starts)
    exe = liftkit.build(STOP_AFTER_SETTING_R0)
    assert len(builds) == 2 and builds[0] != builds[1]
    assert exe.read_bytes() == builds[1]
    assert liftkit.build(STOP_AFTER_SETTING_R0) == exe  # cached once Windows took it
    assert len(builds) == 2
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/lift/test_kit.py`
Expected: FAIL — 1 failed, 5 passed: `AttributeError: module 'liftkit' has no attribute 'native'`

- [ ] **Step 4: Compile a refused harness again with a salt**

In `tests/liftkit.py`, replace:
```python
import hashlib
import random
```
with:
```python
import hashlib
import os
import random
```

In `tests/liftkit.py`, replace:
```python
import gbaport.lift
from gbaport.analysis.cfg import build_program
```
with:
```python
import gbaport.lift
import gbaport.native.build as native
from gbaport.analysis.cfg import build_program
```

In `tests/liftkit.py`, replace:
```python
def build(source: str) -> Path:
    """Compile the harness with ``source``; reuses an earlier build of the same sources."""
    digest = hashlib.sha1()
```
with:
```python
def build(source: str) -> Path:
    """Compile the harness with ``source``; reuses an earlier build of the same sources.

    A build Windows refuses to start (Smart App Control) is compiled again with a different
    ``salt.c``, as ``gbaport build`` does.
    """
    digest = hashlib.sha1()
```

In `tests/liftkit.py`, replace:
```python
        digest.update(text.encode())
    folder = CACHE / digest.hexdigest()[:16]
    exe = folder / "lifthost.exe"
    if exe.exists():
        return exe
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cases.c").write_text(source, encoding="utf-8")
    command = [
        clang(), "-std=c11", "-O1", "-Wall", "-Werror", "-Wno-unused-label",
        f"-I{INCLUDE}", f"-I{HOST.parent}", str(HOST), str(folder / "cases.c"), "-o", str(exe),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"clang failed:\n{result.stderr[-4000:]}")
    return exe


def run_compiled(source: str, cases: list[Case]) -> list[Outcome]:
```
with:
```python
        digest.update(text.encode())
    folder = CACHE / digest.hexdigest()[:16]
    exe = folder / "lifthost.exe"
    if (folder / "started").exists():  # written once Windows let it start
        return exe
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cases.c").write_text(source, encoding="utf-8")
    salt = folder / "salt.c"
    command = [
        clang(), "-std=c11", "-O1", "-Wall", "-Werror", "-Wno-unused-label", f"-I{INCLUDE}",
        f"-I{HOST.parent}", str(HOST), str(folder / "cases.c"), str(salt), "-o", str(exe),
    ]
    for _ in range(native.SALTED_REBUILDS + 1):
        salt.write_text(f'const char lifthost_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"clang failed:\n{result.stderr[-4000:]}")
        if native._starts(exe):
            (folder / "started").write_text("", encoding="utf-8")
            return exe
    raise RuntimeError(f"Windows refused to start {exe} after {native.SALTED_REBUILDS} rebuilds")


def run_compiled(source: str, cases: list[Case]) -> list[Outcome]:
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 582 passed (581 + 1); ruff clean.

- [ ] **Step 6: Commit**

```bash
git add tests/liftkit.py tests/lift/test_kit.py
git commit -m "test: the lifter kit compiles a harness Windows refuses again with a salt"
```

---

### Task 2: jsmolka's CPU test ROMs, and the hosts' `--registers`

**Files:**
- Create: `tests/publicroms/jsmolka/README.md` and one `game.toml` per ROM: `arm.toml`, `thumb.toml`, `memory.toml`, `bios.toml`, `sram.toml`, `flash64.toml`, `flash128.toml`, `none.toml`.
- Modify: `src/gbaport/runtime/host_headless.c` (`--registers`)
- Modify: `tests/romtest.py` (`run_rom(..., args=())`, `run_test(..., args=())`)
- Test: `tests/runtime/test_public_roms.py`

**Interfaces:**
- Consumes: `romtest.TestRom`, `run_rom`, `native_program`, `CACHE` (Plans 4a and 4b).
- **Produces:**
  - **The headless program's `--registers`:** when the run ends it prints `registers r0=xxxxxxxx ... r14=xxxxxxxx cpsr=xxxxxxxx` to stderr.
  - **`romtest`:** `run_rom(rom, *, frames, rom_file, save, args=())` and `run_test(name, *, frames, data, save, args=())`; `args` go to the program after the usual ones.
  - **`test_public_roms`:**
    - `jsmolka_rom(name) -> TestRom` downloads `SOURCE + path` once, checks its SHA-1 and caches it in `CACHE / "jsmolka"`.
    - `failed_test(name) -> int` runs the ROM for 120 frames and reads r12.
    - `ROMS` maps each name to its path and SHA-1.
- **The configs:** each ROM's `game.toml` holds its SHA-1, the entries discovery cannot find (arm, thumb), and the save chip when the ROM's marker has no version digits (sram, flash64, flash128). This task's test runs `memory` and `none`; Tasks 3-5 add the others as they fix what those test.

- [ ] **Step 1: Write the failing test, the configs and the test-kit arguments**

Create `tests/publicroms/jsmolka/README.md`:
```markdown
# jsmolka's GBA tests

Test ROMs from <https://github.com/jsmolka/gba-tests> (MIT licence), commit
`a7113b67e63f83a9b321696ddd7042ccfad6c881`. `tests/runtime/test_public_roms.py` downloads
them from that commit the first time, checks their SHA-1 and caches them with the other
test ROMs: like every `.gba` file, they are not in the repository. Each ROM runs its tests,
shows "All tests passed" or "Failed test N" in mode 4 and then idles; register r12 holds
the number of the first failed test (0 when all passed), which
`tests/runtime/test_public_roms.py` reads with the hosts' `--registers` option.

| ROM | Tests |
|---|---|
| `arm.gba` | ARM instructions: conditions, branches, flags, shifts, data processing, PSR transfers, multiplies, single and halfword transfers, swaps, block transfers |
| `thumb.gba` | Thumb instructions |
| `memory.gba` | Memory mirrors and byte writes to video memory |
| `bios.gba` | What reads of the BIOS area return, before and after a SWI and an interrupt |
| `sram.gba`, `flash64.gba`, `flash128.gba`, `none.gba` | The save chips, and a cartridge without one |

Each ROM's `.toml` is its `game.toml`: the ROM's SHA-1, the code addresses discovery
cannot find (reached through addresses the tests store in memory), and the save chip where
the ROM's marker has no version digits.

Not used: `ppu/` (the renderer comes in Plan 5); `nes.gba`, which copies its code to
VRAM and rewrites instructions there while they run, which a static recompiler cannot
follow; and `unsafe.gba`, whose own README says it fails on real hardware.
```

Create `tests/publicroms/jsmolka/arm.toml`:
```toml
# jsmolka/gba-tests arm.gba (see README.md)
[rom]
sha1 = "753d7f40f50735bf13faab215cf9268f76cf9065"

[code]
# Reached through code addresses the test stores in RAM and loads into pc (ldr pc,
# ldmia {r0, pc}, ldmia with an empty list), which code discovery cannot follow.
entries = [0x080012b8, 0x0800191c, 0x080019dc]
```

Create `tests/publicroms/jsmolka/bios.toml`:
```toml
# jsmolka/gba-tests bios.gba (see README.md)
[rom]
sha1 = "a65b88f609aa3488add7fe331792f1e3ba3372b2"
```

Create `tests/publicroms/jsmolka/flash128.toml`:
```toml
# jsmolka/gba-tests flash128.gba (see README.md)
[rom]
sha1 = "9396b0525ae548e524d50cd6c48ea3e15b092504"
# Its save marker has no version digits, which the detection needs.
save = "flash128k"
```

Create `tests/publicroms/jsmolka/flash64.toml`:
```toml
# jsmolka/gba-tests flash64.gba (see README.md)
[rom]
sha1 = "354fe3dba476b54b869cb44aeb6968fdd72dabd3"
# Its save marker has no version digits, which the detection needs.
save = "flash64k"
```

Create `tests/publicroms/jsmolka/memory.toml`:
```toml
# jsmolka/gba-tests memory.gba (see README.md)
[rom]
sha1 = "5f989b9a4017f16a431f76fd78a95e9799aa8fca"
```

Create `tests/publicroms/jsmolka/none.toml`:
```toml
# jsmolka/gba-tests none.gba (see README.md)
[rom]
sha1 = "6ea4c58075159aa51c1feecd04f17efe3050b70a"
```

Create `tests/publicroms/jsmolka/sram.toml`:
```toml
# jsmolka/gba-tests sram.gba (see README.md)
[rom]
sha1 = "4fc95dc85cb68fdbc04c6689c9d62329582a1856"
# Its save marker, "SRAM_V" with no version digits, is not one the detection knows.
save = "sram"
```

Create `tests/publicroms/jsmolka/thumb.toml`:
```toml
# jsmolka/gba-tests thumb.gba (see README.md)
[rom]
sha1 = "bdcf58182e9a99b388acba5fbca87ac31e8f58eb"

[code]
# Reached through pop {pc} with a pushed lr the test computed, and through a code
# address loaded from RAM by ldmia r0!, {}.
thumb_entries = [0x08000840, 0x08000850, 0x080008a8]
```

In `tests/romtest.py`, replace:
```python
def run_rom(
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None
) -> Run:
```
with:
```python
def run_rom(
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    args: tuple[str, ...] = (),
) -> Run:
```

In `tests/romtest.py`, replace:
```python
    The game's save file is ``save``; without one, every run starts with a blank save.
    """
```
with:
```python
    The game's save file is ``save``; without one, every run starts with a blank save.
    ``args`` go to the program after the usual ones.
    """
```

In `tests/romtest.py`, replace:
```python
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path)]
        result = run_program(command)
```
with:
```python
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path), *args]
        result = run_program(command)
```

In `tests/romtest.py`, replace:
```python

def run_test(name: str, *, frames: int = 600, data: str = "", save: Path | None = None) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save)
```
with:
```python

def run_test(
    name: str, *, frames: int = 600, data: str = "", save: Path | None = None,
    args: tuple[str, ...] = (),
) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save, args=args)
```

Create `tests/runtime/test_public_roms.py`:
```python
"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md), recompiled and run.

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository. Each ROM runs its tests and then idles; when the run reaches its frame limit,
r12 holds the number of the first test that failed, 0 when all of them passed.
"""

import hashlib
import re
import urllib.request
from pathlib import Path

import pytest
import romtest

from gbaport.analysis.config import ConfigError

CONFIGS = Path(__file__).parent.parent / "publicroms" / "jsmolka"
COMMIT = "a7113b67e63f83a9b321696ddd7042ccfad6c881"
SOURCE = f"https://raw.githubusercontent.com/jsmolka/gba-tests/{COMMIT}/"
ROMS = {  # name: (path in jsmolka's repository, SHA-1)
    "arm": ("arm/arm.gba", "753d7f40f50735bf13faab215cf9268f76cf9065"),
    "thumb": ("thumb/thumb.gba", "bdcf58182e9a99b388acba5fbca87ac31e8f58eb"),
    "memory": ("memory/memory.gba", "5f989b9a4017f16a431f76fd78a95e9799aa8fca"),
    "bios": ("bios/bios.gba", "a65b88f609aa3488add7fe331792f1e3ba3372b2"),
    "sram": ("save/sram.gba", "4fc95dc85cb68fdbc04c6689c9d62329582a1856"),
    "flash64": ("save/flash64.gba", "354fe3dba476b54b869cb44aeb6968fdd72dabd3"),
    "flash128": ("save/flash128.gba", "9396b0525ae548e524d50cd6c48ea3e15b092504"),
    "none": ("save/none.gba", "6ea4c58075159aa51c1feecd04f17efe3050b70a"),
}


def jsmolka_rom(name: str) -> romtest.TestRom:
    path, sha1 = ROMS[name]
    cached = romtest.CACHE / "jsmolka" / f"{name}.gba"
    if not cached.exists():
        with urllib.request.urlopen(SOURCE + path, timeout=60) as response:
            data = response.read()
        assert hashlib.sha1(data).hexdigest() == sha1, f"{SOURCE}{path} is not the expected file"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    config = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    return romtest.TestRom(cached.read_bytes(), config)


def failed_test(name: str) -> int:
    run = romtest.run_rom(jsmolka_rom(name), frames=120, args=("--registers",))
    assert run.status == 4, run.stderr
    return int(re.search(r" r12=([0-9a-f]{8})", run.stderr).group(1), 16)


@pytest.mark.parametrize(
    "name", ["memory", "none"]
)
def test_jsmolka_rom_passes(name):
    failed = failed_test(name)
    assert failed == 0, f"{name}.gba: test {failed} failed"


def test_a_rom_that_is_not_the_one_its_config_names_is_refused():
    rom = jsmolka_rom("none")
    changed = romtest.TestRom(rom.data[:-1] + bytes([rom.data[-1] ^ 1]), rom.config)
    with pytest.raises(ConfigError, match="game.toml is for ROM sha1"):
        romtest.native_program(changed)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_public_roms.py`
Expected: FAIL — 2 failed, 1 passed:
- `memory` and `none` fail with `AssertionError: usage: ...game.exe ROM [--frames N] [--save PATH]`, because the host does not know `--registers` yet.
- The SHA-1 test passes already: the analysis checks `[rom] sha1`, and this test pins that for the downloaded ROMs.
- The first run downloads the eight ROMs (about 28 KB) from GitHub.

- [ ] **Step 3: Print the registers when a run ends**

In `src/gbaport/runtime/host_headless.c`, replace:
```c
 *
 *     game ROM [--frames N] [--save PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * The save chip's contents live in PATH (default: the ROM's path with .sav): loaded at the
 * start, stored once a second while they change and again at the end.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
```
with:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--registers]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * The save chip's contents live in PATH (default: the ROM's path with .sav): loaded at the
 * start, stored once a second while they change and again at the end. --registers prints
 * the CPU registers when the run ends.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
static unsigned long frame_limit;
static char save_path[1024];

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
```
with:
```c
static unsigned long frame_limit;
static char save_path[1024];
static int registers;

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
            snprintf(save_path, sizeof save_path, "%s", argv[++i]);
        else if (!rom_path && argv[i][0] != '-')
```
with:
```c
            snprintf(save_path, sizeof save_path, "%s", argv[++i]);
        else if (strcmp(argv[i], "--registers") == 0)
            registers = 1;
        else if (!rom_path && argv[i][0] != '-')
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH]\n", argv[0]);
        return 2;
```
with:
```c
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH] [--registers]\n", argv[0]);
        return 2;
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
    store_save(&rt);
    if (end == GBA_END_ERROR)
```
with:
```c
    store_save(&rt);
    if (registers) {
        fprintf(stderr, "registers");
        for (int i = 0; i < 15; i++)
            fprintf(stderr, " r%d=%08x", i, (unsigned)rt.cpu.r[i]);
        fprintf(stderr, " cpsr=%08x\n", (unsigned)gba_cpsr(&rt.cpu));
    }
    if (end == GBA_END_ERROR)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 585 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_headless.c tests/romtest.py tests/publicroms tests/runtime/test_public_roms.py
git commit -m "test: jsmolka's CPU test ROMs, downloaded and checked by SHA-1; --registers"
```

---

### Task 3: What the BIOS area reads during and after an interrupt

`bios.gba`'s tests 3 and 4 read address 0 inside an interrupt handler and after it returns. The BIOS has fetched the opcode at 0x13C while the handler runs (`0xE25EF004`) and the one at 0x144 after it returns (`0xE55EC002`). `deliver()` had the two the other way round.

**Files:**
- Modify: `src/gbaport/runtime/scheduler.c`
- Test: `tests/runtime/test_public_roms.py` (adds `bios`)

**Interfaces:**
- Consumes: `deliver()` in `scheduler.c` (Plan 4a), `rt->bios_bus`.
- Produces: no new names.

- [ ] **Step 1: Write the failing test**

In `tests/runtime/test_public_roms.py`, replace:
```python
@pytest.mark.parametrize(
    "name", ["memory", "none"]
)
```
with:
```python
@pytest.mark.parametrize(
    "name", ["memory", "bios", "none"]
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_public_roms.py`
Expected: FAIL — 1 failed, 3 passed: `AssertionError: bios.gba: test 3 failed`

- [ ] **Step 3: Swap the two values**

In `src/gbaport/runtime/scheduler.c`, replace:
```c
    ctx->cycles += 40;  /* the BIOS's IRQ entry and exit */
    rt->bios_bus = 0xE55EC002u;
    gba_call(ctx, handler, BIOS_IRQ_RETURN);
```
with:
```c
    ctx->cycles += 40;  /* the BIOS's IRQ entry and exit */
    rt->bios_bus = 0xE25EF004u;  /* the opcode at 0x13C, fetched while the handler runs */
    gba_call(ctx, handler, BIOS_IRQ_RETURN);
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
    gba_restore_cpsr(ctx);
    rt->bios_bus = 0xE25EF004u;
    gba_reschedule(rt);
```
with:
```c
    gba_restore_cpsr(ctx);
    rt->bios_bus = 0xE55EC002u;  /* the opcode at 0x144, fetched after it returns */
    gba_reschedule(rt);
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 586 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/scheduler.c tests/runtime/test_public_roms.py
git commit -m "fix: the BIOS area reads the opcodes the BIOS fetches around an interrupt"
```

---

### Task 4: The save chip's bus sees the whole address of a store

The save chip sits on an 8-bit bus that sees every address line. A halfword or word store there writes the one byte of the value that lines up with the address: `strh 0xAABB` at an odd address writes 0xAA.

Until now `gba_cpu.h` rounded store addresses down before the memory saw them, so the save chip got the low byte at the rounded-down address. It also wrote 32-bit stores as two bytes, at addr and addr+2, a deferred minor from Plan 4b's review. Now stores pass the whole address and `memory.c` rounds it down, except on the save chip's bus. Reads of 16 and 32 bits round down in `memory.c` too, so a BIOS call given an odd pointer can no longer touch the next region's array (another Plan 4b minor).

**Files:**
- Modify: `src/gbaport/runtime/memory.c`, `src/gbaport/lift/gba_cpu.h`
- Modify: `tests/lifthost.c`. The lifter test harness's memory rounds store addresses down too, as `memory.c` now does.
- Test: `tests/runtime/test_public_roms.py` (adds `sram`, `flash64`, `flash128`)

**Interfaces:**
- Consumes: `gba_save_write8` (Plan 4b).
- **Produces (a changed contract):**
  - `gba_write16` and `gba_write32` take unaligned addresses and round them down, except for the save chip.
  - `gba_read16` and `gba_read32` round down as well.
  - `gba_str` and `gba_strh` in `gba_cpu.h` pass the whole address.

- [ ] **Step 1: Write the failing test**

In `tests/lifthost.c`, replace:
```c
{
    uint8_t *p = window(addr, 2, 1);
    (void)ctx;
```
with:
```c
{
    uint8_t *p = window(addr & ~1u, 2, 1);  /* stores arrive with the whole address */
    (void)ctx;
```

In `tests/lifthost.c`, replace:
```c
{
    uint8_t *p = window(addr, 4, 1);
    (void)ctx;
```
with:
```c
{
    uint8_t *p = window(addr & ~3u, 4, 1);
    (void)ctx;
```

In `tests/runtime/test_public_roms.py`, replace:
```python
@pytest.mark.parametrize(
    "name", ["memory", "bios", "none"]
)
```
with:
```python
@pytest.mark.parametrize(
    "name", ["memory", "bios", "sram", "flash64", "flash128", "none"]
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_public_roms.py`
Expected: FAIL — 3 failed, 4 passed: `sram.gba: test 6 failed`, `flash64.gba: test 6 failed`, `flash128.gba: test 6 failed` (test 6: "Store half position").

- [ ] **Step 3: Pass the whole address and round it down in the memory**

In `src/gbaport/lift/gba_cpu.h`, replace:
```c

static inline void gba_str(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write32(ctx, addr & ~3u, v); }
static inline void gba_strh(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write16(ctx, addr & ~1u, v & 0xFFFF); }
static inline void gba_strb(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write8(ctx, addr, v & 0xFF); }
```
with:
```c

/* Stores pass the whole address: the memory rounds it down, except on the save chip's bus. */
static inline void gba_str(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write32(ctx, addr, v); }
static inline void gba_strh(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write16(ctx, addr, v & 0xFFFF); }
static inline void gba_strb(GbaCtx *ctx, uint32_t addr, uint32_t v) { gba_write8(ctx, addr, v & 0xFF); }
```

In `src/gbaport/runtime/memory.c`, replace:
```c
 *
 * Addresses arrive aligned to the access size (gba_cpu.h applies the ARM7TDMI rules for
 * misaligned loads and stores first). Every region mirrors across its 16 MiB page.
 * Byte writes follow the hardware: palette and BG VRAM write the byte to both halves of
```
with:
```c
 *
 * 16- and 32-bit accesses use the address rounded down to their size, as the buses do;
 * only the save chip sees the whole address of a store (gba_cpu.h applies the ARM7TDMI's
 * rotation of misaligned loads). Every region mirrors across its 16 MiB page.
 * Byte writes follow the hardware: palette and BG VRAM write the byte to both halves of
```

In `src/gbaport/runtime/memory.c`, replace:
```c
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus (wider reads repeat the byte), and an EEPROM at 0x0D000000. */
#include <string.h>
```
with:
```c
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus: wider reads repeat the byte, and wider stores write the one byte of the
 * value that lines up with the address. An EEPROM answers at 0x0D000000. */
#include <string.h>
```

In `src/gbaport/runtime/memory.c`, replace:
```c
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get16(mem + offset);
```
with:
```c
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    addr &= ~1u;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get16(mem + offset);
```

In `src/gbaport/runtime/memory.c`, replace:
```c
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get32(mem + offset);
```
with:
```c
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    addr &= ~3u;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get32(mem + offset);
```

In `src/gbaport/runtime/memory.c`, replace:
```c
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        put16(mem + offset, value);
    else
        write16(rt, addr, value & 0xFFFF, 0xFFFF);
}
```
with:
```c
    uint32_t offset;
    uint8_t *mem = plain(rt, addr & ~1u, &offset);
    if (mem)
        put16(mem + offset, value);
    else if (is_save(addr))
        gba_save_write8(rt, addr, value >> (addr & 1) * 8);
    else
        write16(rt, addr & ~1u, value & 0xFFFF, 0xFFFF);
}
```

In `src/gbaport/runtime/memory.c`, replace:
```c
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem) {
        put32(mem + offset, value);
    } else {
        write16(rt, addr, value & 0xFFFF, 0xFFFF);
        write16(rt, addr + 2, value >> 16, 0xFFFF);
    }
```
with:
```c
    uint32_t offset;
    uint8_t *mem = plain(rt, addr & ~3u, &offset);
    if (mem) {
        put32(mem + offset, value);
    } else if (is_save(addr)) {
        gba_save_write8(rt, addr, value >> (addr & 3) * 8);
    } else {
        write16(rt, addr & ~3u, value & 0xFFFF, 0xFFFF);
        write16(rt, (addr & ~3u) + 2, value >> 16, 0xFFFF);
    }
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 589 passed; ruff clean.
- `gba_cpu.h` changed, so every lifter test harness is rebuilt; Task 1's salt loop deals with any Windows refuses. The run takes a few minutes longer than usual.
- The Unicorn tests of misaligned stores still pass: they check RAM, where stores still round down.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/memory.c src/gbaport/lift/gba_cpu.h tests/lifthost.c tests/runtime/test_public_roms.py
git commit -m "fix: halfword and word stores to the save chip write the byte at their address"
```

---

### Task 5: ARMv4 quirks — compares with Rd = 15, and empty register lists

`arm.gba` and `thumb.gba` test two things the ARM7TDMI does that later cores (and Unicorn's ARMv5 model) do not:
- **A compare with Rd = 15.** An ARM `tst`/`teq`/`cmp`/`cmn` whose Rd field is 15 (the old `tstp`/`teqp`/`cmpp`/`cmnp`) copies SPSR to CPSR and does not jump.
- **An empty register list.** An `ldm`/`stm` with no registers transfers r15 alone, at the address the first of 16 registers would use, and moves the base by 0x40. An `ldm` with an empty list is therefore a jump through memory.

The lifter reported empty lists as instructions it cannot express, and compiled compares with Rd = 15 as plain compares. The two test ROMs also jump to a few addresses that discovery cannot see (stored to RAM, then loaded into pc). Their `game.toml` files from Task 2 list them.

**Files:**
- Modify: `src/gbaport/lift/semantics.py` (`restores_cpsr`, `_block_transfer`), `src/gbaport/analysis/flow.py` (`writes_pc`)
- Modify: `tests/liftkit.py`. A case gets `entries`: more functions to recompile.
- Modify: `tests/lift/test_program.py`. Its "an instruction C cannot express is reported" test used an empty list. Every instruction can be expressed now, so it makes one fail on purpose instead.
- Test: `tests/lift/test_armv4_quirks.py`, `tests/runtime/test_public_roms.py` (adds `arm`, `thumb`)

**Interfaces:**
- Consumes: `liftkit.Case`, `run_lifted`, `progkit.CODE_ADDR`.
- **Produces:**
  - `restores_cpsr(ins)` is true for an ARM compare whose Rd field (bits 12-15 of `raw`) is 15.
  - `writes_pc(ins)` is true for an `ldm` with an empty list.
  - `_block_transfer` lifts empty lists.
  - `Case.entries: tuple[int, ...]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/lift/test_armv4_quirks.py`:
```python
"""ARMv4 behaviours Unicorn's ARMv5 core does differently, checked against the ARM7TDMI's
rules directly (jsmolka's arm.gba and thumb.gba test them too: test_public_roms.py)."""

import struct

from liftkit import EWRAM, Case, run_lifted
from progkit import CODE_ADDR

FIQ, SYS = 0xD1, 0x1F


def test_a_compare_with_rd_15_copies_spsr_to_cpsr_and_does_not_jump():
    source = (
        "msr cpsr_c, #0xd1\n"         # FIQ mode, which banks r8
        "mov r8, #64\n"
        "msr spsr_fsxc, #0x1f\n"      # SPSR: system mode, flags clear
        ".word 0xe15ff000\n"          # cmp pc, r0 with Rd = 15 (the old cmpp)
        "mov r0, r8\n"                # runs next, in system mode: its own r8
    )
    case = Case(source, flags=0xF0000000)
    case.regs[8] = 32
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    assert out.cpsr & 0xFF == SYS and out.cpsr >> 28 == 0  # SPSR's mode and flags
    assert out.regs[0] == 32


def test_tst_teq_and_cmn_with_rd_15_restore_cpsr_too():
    for word in (0xE11FF000, 0xE13FF000, 0xE17FF000):  # tst, teq, cmn pc, r0 with Rd = 15
        case = Case(f"msr cpsr_c, #0xd1\nmsr spsr_fsxc, #0x1f\n.word {word:#x}\n")
        out = run_lifted([case])[0]
        assert out.status == "stopped"
        assert out.cpsr & 0xFF == SYS


def stm_empty(word: int) -> tuple[int, bytes]:
    """Runs an ARM STM with an empty register list on r0 = EWRAM + 0x200."""
    case = Case(f".word {word:#x}\n")
    case.regs[0] = EWRAM + 0x200
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    return out.regs[0], out.ewram


def test_an_empty_register_list_stores_r15_and_moves_the_base_by_0x40():
    stored = struct.pack("<I", CODE_ADDR + 12)  # the stm's own address + 12
    for word, base, at in (
        (0xE8A00000, 0x240, 0x200),  # stmia r0!, {}
        (0xE9A00000, 0x240, 0x204),  # stmib r0!, {}
        (0xE8200000, 0x1C0, 0x1C4),  # stmda r0!, {}: where r0-r15 would start
        (0xE9200000, 0x1C0, 0x1C0),  # stmdb r0!, {}
    ):
        r0, ram = stm_empty(word)
        assert r0 == EWRAM + base, hex(word)
        assert ram[at : at + 4] == stored, hex(word)


def test_an_ldm_with_an_empty_register_list_loads_r15_and_moves_the_base_by_0x40():
    source = (
        "adr r1, after\n"
        "str r1, [r0]\n"
        ".word 0xe8b00000\n"  # ldmia r0!, {}: jumps to after
        "mov r2, #1\n"        # skipped
        "after:\n"
        "mov r3, #2\n"
    )
    case = Case(source, entries=(CODE_ADDR + 16,))  # after: only the loaded pc leads there
    case.regs[0] = EWRAM + 0x200
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    assert (out.regs[0], out.regs[2], out.regs[3]) == (EWRAM + 0x240, 0, 2)
```

In `tests/lift/test_program.py`, replace:
```python
from gbaport.analysis.discover import explore
from gbaport.isa.model import Mode
from gbaport.lift.program import lift_program, program_files, single_source

# Two functions without calls, both given as seeds.   c0 first   c8 second
```
with:
```python
from gbaport.analysis.discover import explore
from gbaport.isa.model import Mode
from gbaport.lift import function
from gbaport.lift.program import lift_program, program_files, single_source
from gbaport.lift.semantics import LiftError

# Two functions without calls, both given as seeds.   c0 first   c8 second
```

In `tests/lift/test_program.py`, replace:
```python

def test_an_instruction_c_cannot_express_is_reported():
    program = lifted(".word 0xe8bd0000\nbx lr")  # ldmia sp!, {} (empty register list)
    assert program.problems == ("0x080000c0: LDM/STM with an empty register list",)
    assert "gba_undefined(ctx, 0x080000c0u);" in program.functions[0x080000C0]
```
with:
```python

def test_an_instruction_c_cannot_express_is_reported(monkeypatch):
    effects = function.lift_effects

    def refuse_the_first(ins):  # every instruction has C now: pretend the first does not
        if ins.addr == 0x080000C0:
            raise LiftError(f"{ins.addr:#010x}: no effects for {ins.op.value}")
        return effects(ins)

    monkeypatch.setattr(function, "lift_effects", refuse_the_first)
    program = lifted("mov r0, #1\nbx lr")
    assert program.problems == ("0x080000c0: no effects for mov",)
    assert "gba_undefined(ctx, 0x080000c0u);" in program.functions[0x080000C0]
```

In `tests/liftkit.py`, replace:
```python
    ewram: bytes = bytes(WINDOW)
    iwram: bytes = bytes(WINDOW)

    @property
```
with:
```python
    ewram: bytes = bytes(WINDOW)
    iwram: bytes = bytes(WINDOW)
    entries: tuple[int, ...] = ()  # more functions to recompile (in the case's state)

    @property
```

In `tests/liftkit.py`, replace:
```python
        mode = Mode.THUMB if case.thumb else Mode.ARM
        ex = explore(space, [(CODE_ADDR, mode, "seed")])
        lifted = lift_program(build_program(ex), ex, prefix=f"c{i}_")
```
with:
```python
        mode = Mode.THUMB if case.thumb else Mode.ARM
        ex = explore(space, [(addr, mode, "seed") for addr in (CODE_ADDR, *case.entries)])
        lifted = lift_program(build_program(ex), ex, prefix=f"c{i}_")
```

In `tests/runtime/test_public_roms.py`, replace:
```python
@pytest.mark.parametrize(
    "name", ["memory", "bios", "sram", "flash64", "flash128", "none"]
)
```
with:
```python
@pytest.mark.parametrize(
    "name", ["arm", "thumb", "memory", "bios", "sram", "flash64", "flash128", "none"]
)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/lift/test_armv4_quirks.py tests/runtime/test_public_roms.py`
Expected: FAIL — 6 failed, 7 passed.
- The compare tests: the CPSR keeps FIQ mode (`assert (... & 255) == 31`).
- The empty-list tests: `assert 'undefined' == 'stopped'`.
- `arm` and `thumb` end with exit status 3: the registers line, then `error: no recompiled code at 0x00000000` for arm and `error: undefined instruction at 0x080008a0` for thumb.

- [ ] **Step 3: Lift both quirks**

In `src/gbaport/analysis/flow.py`, replace:
```python
        return ins.rd == PC
    if ins.op is Op.LDM:
        return PC in ins.reglist
    return False
```
with:
```python
        return ins.rd == PC
    if ins.op is Op.LDM:  # ARMv4: an empty list loads r15 alone
        return PC in ins.reglist or not ins.reglist
    return False
```

In `src/gbaport/lift/semantics.py`, replace:
```python
def restores_cpsr(ins: Instruction) -> bool:
    """An exception return (movs pc, ... or ldm ... {..., pc}^): CPSR = SPSR, T bit included."""
    if ins.op in DATA_PROCESSING_OPS:
```
with:
```python
def restores_cpsr(ins: Instruction) -> bool:
    """An exception return (movs pc, ... or ldm ... {..., pc}^): CPSR = SPSR, T bit included.

    An ARM compare whose Rd field is 15 (the old tstp/teqp/cmpp/cmnp) copies SPSR to CPSR
    too, without jumping.
    """
    if ins.op in COMPARE_OPS:
        return ins.mode is Mode.ARM and (ins.raw >> 12) & 0xF == PC
    if ins.op in DATA_PROCESSING_OPS:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
def _block_transfer(ins: Instruction) -> list[str]:
    regs = ins.reglist
    if not regs:
        raise LiftError(f"{ins.addr:#010x}: LDM/STM with an empty register list")
    count = len(regs)
    base = read(ins, ins.rn)
```
with:
```python
def _block_transfer(ins: Instruction) -> list[str]:
    # ARMv4: an empty list transfers r15 alone, at the address the first of 16 would use.
    regs = ins.reglist or (PC,)
    count = len(ins.reglist) or 16
    base = read(ins, ins.rn)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 595 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/lift/semantics.py src/gbaport/analysis/flow.py tests/liftkit.py tests/lift/test_armv4_quirks.py tests/lift/test_program.py tests/runtime/test_public_roms.py
git commit -m "fix: compares with Rd = 15 restore CPSR; empty register lists move r15"
```

---

### Task 6: The screen — the bitmap modes, and `--screenshot`

The hosts need a picture before the renderer exists (Plan 5). `gba_screen` draws the bitmap modes, which jsmolka's test ROMs and many homebrew programs use. Everything else shows the backdrop colour, and forced blank shows white.

**Files:**
- Create: `src/gbaport/runtime/screen.c`, `tests/gbaroms/bitmap.c`
- Modify: `src/gbaport/runtime/gba_runtime.h` (`GBA_SCREEN_WIDTH`, `GBA_SCREEN_HEIGHT`, `gba_screen`), `src/gbaport/native/build.py` (`screen.c`), `src/gbaport/runtime/host_headless.c` (`--screenshot`)
- Modify: `tests/romtest.py` (`read_bmp`)
- Test: `tests/runtime/test_screen.py`

**Interfaces:**
- Consumes: the runtime's `io`, `palette` and `vram` arrays.
- **Produces:**
  - `void gba_screen(const GbaRuntime *rt, uint32_t *pixels)`: 240x160 pixels, `0x00RRGGBB`, each 5-bit colour widened as `(c << 3) | (c >> 2)`.
  - The headless program's `--screenshot PATH`: a 24-bit BMP of the last picture.
  - `romtest.read_bmp(path) -> list[int]`: a 240x160 BMP's pixels, top row first.

- [ ] **Step 1: Write the failing test**

Create `tests/gbaroms/bitmap.c`:
```c
/* Draws a known picture for the screen tests, then waits for VBlanks until the run ends.
 * testdata.h sets DISPCNT; test_screen.py works out the expected picture by the same
 * formulas. Only the page DISPCNT shows is drawn. Mode 4 pixels are written in pairs, as
 * byte writes to VRAM would repeat the byte. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    PALETTE[0] = 0x7C00;  /* the backdrop: blue */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(i * 0x0421 & 0x7FFF);
    uint32_t page = DISPCNT & 0x10 ? 0xA000 / 2 : 0;
    for (uint32_t y = 0; y < 160; y++) {
        for (uint32_t x = 0; x < 240; x += 2) {
            if ((DISPCNT & 7) == 3) {
                VRAM[y * 240 + x] = (uint16_t)((x & 31) | (y & 31) << 5);
                VRAM[y * 240 + x + 1] = (uint16_t)(((x + 1) & 31) | (y & 31) << 5);
            } else if ((DISPCNT & 7) == 4) {
                VRAM[page + (y * 240 + x) / 2] = (uint16_t)(((x + y) & 255) | ((x + 1 + y) & 255) << 8);
            } else if (x < 160 && y < 128) {
                VRAM[page + y * 160 + x] = (uint16_t)((x ^ y) & 0x7FFF);
                VRAM[page + y * 160 + x + 1] = (uint16_t)(((x + 1) ^ y) & 0x7FFF);
            }
        }
    }
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
```

In `tests/romtest.py`, replace:
```python
    return run_rom(build_test_rom(name, data), frames=frames, save=save, args=args)
```
with:
```python
    return run_rom(build_test_rom(name, data), frames=frames, save=save, args=args)

def read_bmp(path: Path) -> list[int]:
    """A 240x160, 24-bit BMP's pixels as 0x00RRGGBB values, top row first."""
    data = path.read_bytes()
    offset, = struct.unpack_from("<I", data, 10)
    width, height = struct.unpack_from("<ii", data, 18)
    assert (width, abs(height), data[28]) == (240, 160, 24), "not a 240x160 24-bit BMP"
    pixels = []
    for y in range(160):
        row = offset + (159 - y if height > 0 else y) * 720  # bottom-up unless the height is negative
        for x in range(240):
            b, g, r = data[row + 3 * x : row + 3 * x + 3]
            pixels.append(r << 16 | g << 8 | b)
    return pixels
```

Create `tests/runtime/test_screen.py`:
```python
"""The picture the hosts show: the bitmap modes, until the scanline renderer (Plan 5)."""

import pytest
from romtest import read_bmp, run_test

BACKDROP = 0x7C00  # blue, palette entry 0 (bitmap.c)


def rgb(color: int) -> int:
    r, g, b = color & 31, (color >> 5) & 31, (color >> 10) & 31
    return ((r << 3 | r >> 2) << 16) | ((g << 3 | g >> 2) << 8) | (b << 3 | b >> 2)


def expected(dispcnt: int) -> list[int]:
    """What bitmap.c draws, by the same formulas."""
    mode = dispcnt & 7
    pixels = []
    for y in range(160):
        for x in range(240):
            color = BACKDROP
            if dispcnt & 0x400 and mode == 3:
                color = (x & 31) | (y & 31) << 5
            elif dispcnt & 0x400 and mode == 4 and (x + y) & 255:
                color = ((x + y) & 255) * 0x0421 & 0x7FFF
            elif dispcnt & 0x400 and mode == 5 and x < 160 and y < 128:
                color = (x ^ y) & 0x7FFF
            pixels.append(0xFFFFFF if dispcnt & 0x80 else rgb(color))
    return pixels


@pytest.mark.parametrize("dispcnt", [
    0x0403,  # mode 3
    0x0404,  # mode 4, page 0
    0x0414,  # mode 4, page 1 (bitmap.c draws only the page it shows)
    0x0415,  # mode 5, page 1: 160x128, the rest is backdrop
    0x0003,  # mode 3 with BG2 off: backdrop
    0x0100,  # mode 0 (tiles): backdrop until the renderer arrives
    0x0483,  # forced blank: white
])
def test_the_screen_shows_the_bitmap_modes(tmp_path, dispcnt):
    shot = tmp_path / "screen.bmp"
    data = f"#define DISPCNT 0x{dispcnt:04x}\n"
    run = run_test("bitmap", frames=10, data=data, args=("--screenshot", str(shot)))
    assert run.status == 4, run.stderr
    assert read_bmp(shot) == expected(dispcnt)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_screen.py`
Expected: FAIL — 7 failed, each with `AssertionError: usage: ...game.exe ROM [--frames N] [--save PATH] [--registers]`: the host does not know `--screenshot` yet.

- [ ] **Step 3: Draw the bitmap modes and write screenshots**

In `src/gbaport/native/build.py`, replace:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c", "save.c",
)
```
with:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c", "save.c", "screen.c",
)
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
enum {
    GBA_CYCLES_HDRAW = 1008,  /* the HBlank flag and interrupt come this far into a line */
```
with:
```c
enum {
    GBA_SCREEN_WIDTH = 240,
    GBA_SCREEN_HEIGHT = 160,
    GBA_CYCLES_HDRAW = 1008,  /* the HBlank flag and interrupt come this far into a line */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_end(GbaRuntime *rt, GbaEnd why);  /* from a callback: ends gba_run */
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);
uint32_t gba_crc32(const uint8_t *data, uint32_t size);
```
with:
```c
void gba_end(GbaRuntime *rt, GbaEnd why);  /* from a callback: ends gba_run */
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);  /* GBA key bits, 1 = pressed */
void gba_screen(const GbaRuntime *rt, uint32_t *pixels);  /* 240x160, 0x00RRGGBB */
uint32_t gba_crc32(const uint8_t *data, uint32_t size);
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--registers]
 *
```
with:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--registers] [--screenshot PATH]
 *
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
 * start, stored once a second while they change and again at the end. --registers prints
 * the CPU registers when the run ends.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
```
with:
```c
 * start, stored once a second while they change and again at the end. --registers prints
 * the CPU registers when the run ends; --screenshot writes the last picture as a BMP file.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
static char save_path[1024];
static int registers;

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
```
with:
```c
static char save_path[1024];
static int registers;
static const char *screenshot;

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c

static void on_frame(GbaRuntime *rt, void *user)
```
with:
```c

/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
static int write_bmp(const char *path, const uint32_t *pixels)
{
    enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT, ROW = W * 3, DATA = ROW * H };
    uint8_t header[54] = {'B', 'M'};
    uint32_t fields[][2] = {  /* offset, value: little-endian 32-bit fields */
        {2, 54 + DATA}, {10, 54}, {14, 40}, {18, W}, {22, H}, {34, DATA},
    };
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        for (int b = 0; b < 4; b++)
            header[fields[i][0] + b] = (uint8_t)(fields[i][1] >> (8 * b));
    header[26] = 1;   /* planes */
    header[28] = 24;  /* bits per pixel */
    FILE *f = fopen(path, "wb");
    if (!f)
        return -1;
    fwrite(header, 1, sizeof header, f);
    for (int y = H - 1; y >= 0; y--) {  /* bottom row first */
        uint8_t row[ROW];
        for (int x = 0; x < W; x++) {
            uint32_t c = pixels[y * W + x];
            row[x * 3] = (uint8_t)c;
            row[x * 3 + 1] = (uint8_t)(c >> 8);
            row[x * 3 + 2] = (uint8_t)(c >> 16);
        }
        fwrite(row, 1, ROW, f);
    }
    return fclose(f) == 0 ? 0 : -1;
}

static void on_frame(GbaRuntime *rt, void *user)
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
            registers = 1;
        else if (!rom_path && argv[i][0] != '-')
```
with:
```c
            registers = 1;
        else if (strcmp(argv[i], "--screenshot") == 0 && i + 1 < argc)
            screenshot = argv[++i];
        else if (!rom_path && argv[i][0] != '-')
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH] [--registers]\n", argv[0]);
        return 2;
```
with:
```c
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH] [--registers] "
                        "[--screenshot PATH]\n", argv[0]);
        return 2;
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
    }
    if (end == GBA_END_ERROR)
```
with:
```c
    }
    if (screenshot) {
        static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
        gba_screen(&rt, pixels);
        if (write_bmp(screenshot, pixels) != 0)
            fprintf(stderr, "warning: cannot write %s\n", screenshot);
    }
    if (end == GBA_END_ERROR)
```

Create `src/gbaport/runtime/screen.c`:
```c
/* screen.c - the picture the host shows, until the scanline renderer (Plan 5) replaces it.
 *
 * Only the bitmap modes are drawn, on BG2 without scaling, rotation or effects: mode 3
 * (240x160, 15-bit colour), mode 4 (240x160, palette indices, two pages) and mode 5
 * (160x128, 15-bit colour, two pages). Everything else shows the backdrop colour (palette
 * entry 0); forced blank shows white. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

static uint32_t rgb(uint32_t color)  /* GBA 0BBBBBGGGGGRRRRR to 0x00RRGGBB */
{
    uint32_t r = color & 31, g = (color >> 5) & 31, b = (color >> 10) & 31;
    r = (r << 3) | (r >> 2);
    g = (g << 3) | (g >> 2);
    b = (b << 3) | (b >> 2);
    return r << 16 | g << 8 | b;
}

static uint32_t get16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }

void gba_screen(const GbaRuntime *rt, uint32_t *pixels)
{
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    uint32_t mode = control & 7, page = control & 0x10 ? 0xA000u : 0;
    uint32_t backdrop = rgb(get16(rt->palette));
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++) {
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint32_t color = backdrop;
            if (control & 0x80) {
                color = 0xFFFFFF;  /* forced blank */
            } else if (control & 0x400) {  /* BG2 on */
                if (mode == 3) {
                    color = rgb(get16(rt->vram + (y * 240 + x) * 2));
                } else if (mode == 4) {
                    uint8_t index = rt->vram[page + y * 240 + x];
                    if (index)
                        color = rgb(get16(rt->palette + index * 2));
                } else if (mode == 5 && x < 160 && y < 128) {
                    color = rgb(get16(rt->vram + page + (y * 160 + x) * 2));
                }
            }
            pixels[y * GBA_SCREEN_WIDTH + x] = color;
        }
    }
}
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 602 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/screen.c src/gbaport/runtime/gba_runtime.h src/gbaport/native/build.py src/gbaport/runtime/host_headless.c tests/gbaroms/bitmap.c tests/romtest.py tests/runtime/test_screen.py
git commit -m "feat: the bitmap modes on screen, and --screenshot"
```

---

### Task 7: The keypad interrupt, Stop wake-up and scripted key presses

**What changes for the game:**
- **Stop.** It now waits for the host instead of ending the run. The CPU, the clocks and the display stand still until an enabled keypad interrupt is requested. Only the host can press keys, so it waits for input in a new `stopped` callback; without one (or with nothing to press) the run ends as before.
- **KEYCNT.** It requests the keypad interrupt as mGBA does. With "any of" (OR), the interrupt comes at every check while a chosen key is held. With "all of" (AND), it comes once each time the keys change to a match.
- **The checks.** They happen at the start of every frame, when the host passes keys in, when KEYCNT is written, and when the game stops.

**What changes in the hosts:** both share `host_common.c`, so the window host (Task 8) gets the same command line, save file and scripted presses. `--press FRAME:KEYS` holds keys from a frame on. While the game is stopped no time passes, so the next scripted press arrives at once.

**Files:**
- Create: `src/gbaport/runtime/host_common.h`, `src/gbaport/runtime/host_common.c`
- Create: `src/gbaport/runtime/host_headless.c`, replacing the current version. It keeps only what is headless: the debug log on stdout, keys from the script, and the screenshot.
- Modify: `src/gbaport/runtime/gba_runtime.h`, `io.c`, `bios.c`, `scheduler.c`, `runtime.c`
- Modify: `src/gbaport/native/build.py`. `HOSTS` maps a host to its source files.
- Create test ROMs: `tests/gbaroms/keypad.c`, `tests/gbaroms/stop_wake.c`
- Modify: `tests/gbaroms/testlib.h` (`REG_KEYCNT`, `KEY_*`)
- Test: `tests/runtime/test_keypad.py`

**Interfaces:**
- Consumes: Task 6's `gba_screen`, and the Plan 4b save functions.
- **Produces, C runtime:**
  - `GbaHost.stopped` (`int (*)(GbaRuntime *, void *)`, after `diag`, before `user`).
  - `void gba_stop(GbaRuntime *rt)` and `void gba_keypad_check(GbaRuntime *rt)`.
  - `GbaRuntime.keys_last`.
  - `gba_set_keys` checks the keypad interrupt on every call.
- **Produces, `host_common.h`:**
  - `HostOptions` and `HostPress`.
  - `host_parse(o, argc, argv)` returns 0, or 2 after printing the usage. It reads `--frames`, `--save`, `--press`, `--registers` and `--screenshot`, and `--scale`/`--fast` when `o->window` is set.
  - `host_open(o, rt, host)` returns 0 or 2.
  - `host_frame(o, rt)`, `host_script_wake(o)`, `host_finish(o, rt, end)` (returns the exit status) and `host_write_bmp(path, pixels)`.
- **Produces, Python:** `HOSTS = {"headless": ("host_common.c", "host_headless.c")}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/gbaroms/keypad.c`:
```c
/* The keypad. Run with --press 5:A --press 10:A+B --press 15:none --press 20:A
 * --press 25:A+B (the test script holds those keys from those frames on). KEYINPUT reads
 * them (0 = pressed). KEYCNT requests the keypad interrupt as mGBA does: with "any of"
 * (OR), at every frame start while a chosen key is held; with "all of" (AND), once each
 * time the keys change to a match; never without its interrupt bit. */
#include "testlib.h"

#define KEYCNT_IRQ 0x4000
#define KEYCNT_AND 0x8000

static void until_frame(uint32_t *frame, uint32_t target)
{
    while (*frame < target) {
        bios_vblank_wait();
        ++*frame;
    }
}

int main(void)
{
    uint32_t frame = 0;
    irq_init();
    REG_DISPSTAT = 0x08;  /* VBlank interrupt */
    REG_IE = IRQ_VBLANK | IRQ_KEYPAD;
    REG_KEYCNT = KEYCNT_IRQ | KEY_B;  /* any of: B */

    until_frame(&frame, 7);
    expect("keyinput reads a held", REG_KEYINPUT, 0x3FF & ~KEY_A);
    expect("a key keycnt does not choose requests nothing", irq_count[12], 0);

    until_frame(&frame, 13);
    expect("keyinput reads a and b held", REG_KEYINPUT, 0x3FF & ~(KEY_A | KEY_B));
    check("holding b requests it at every frame", irq_count[12] >= 3);

    REG_KEYCNT = KEYCNT_IRQ | KEYCNT_AND | KEY_A | KEY_B;  /* all of: A, B (held now) */
    irq_count[12] = 0;
    until_frame(&frame, 14);
    expect("a keycnt matching the held keys requests it once", irq_count[12], 1);

    until_frame(&frame, 23);
    expect("keyinput reads a alone held", REG_KEYINPUT, 0x3FF & ~KEY_A);
    expect("half of an and condition requests nothing", irq_count[12], 1);

    until_frame(&frame, 28);
    expect("pressing both again requests it once more", irq_count[12], 2);

    REG_KEYCNT = KEY_A | KEY_B;  /* the interrupt bit off */
    until_frame(&frame, 30);
    expect("without the interrupt bit nothing is requested", irq_count[12], 2);
    test_end();
    return 0;
}
```

Create `tests/gbaroms/stop_wake.c`:
```c
/* Stop sleeps until a key the game asked for (KEYCNT with its interrupt bit, IE) is
 * pressed. The test presses START from frame 30; the clocks stand still while the game
 * is stopped, so the press arrives at once and the screen has not moved on. A key held
 * already wakes it at once; with no press, nothing wakes it and the run ends at the Stop. */
#include "testlib.h"

int main(void)
{
    irq_init();
    REG_IE = IRQ_KEYPAD;
    REG_KEYCNT = 0x4000 | KEY_START;
    print("stopping");
    uint32_t before = REG_VCOUNT;
    __asm__ volatile("svc #3" ::: "r0", "r1", "r2", "r3", "memory");
    uint32_t after = REG_VCOUNT;
    print("woke");
    check("the keypad interrupt woke it", irq_count[12] >= 1);
    expect("start reads as held", REG_KEYINPUT & KEY_START, 0);
    uint32_t lines = after >= before ? after - before : after + 228 - before;
    check("the screen did not move on while stopped", lines < 2);
    REG_KEYCNT = 0;  /* START is still held: it would wake the last Stop at once */
    test_end();
    return 0;
}
```

In `tests/gbaroms/testlib.h`, replace:
```c
#define REG_KEYINPUT REG16(0x04000130)
#define REG_IE       REG16(0x04000200)
```
with:
```c
#define REG_KEYINPUT REG16(0x04000130)
#define REG_KEYCNT   REG16(0x04000132)
#define REG_IE       REG16(0x04000200)
```

In `tests/gbaroms/testlib.h`, replace:
```c
    IRQ_DMA0 = 0x100, IRQ_KEYPAD = 0x1000,
};
```
with:
```c
    IRQ_DMA0 = 0x100, IRQ_KEYPAD = 0x1000,
};

enum {  /* KEYINPUT and KEYCNT bits */
    KEY_A = 1, KEY_B = 2, KEY_SELECT = 4, KEY_START = 8, KEY_RIGHT = 0x10, KEY_LEFT = 0x20,
    KEY_UP = 0x40, KEY_DOWN = 0x80, KEY_R = 0x100, KEY_L = 0x200,
};
```

Create `tests/runtime/test_keypad.py`:
```python
from romtest import run_test

SCRIPT = (
    "--press", "5:A", "--press", "10:A+B", "--press", "15:none", "--press", "20:A",
    "--press", "25:A+B",
)


def test_keyinput_and_the_keypad_interrupt_follow_the_keys():
    run_test("keypad", args=SCRIPT).assert_passed()


def test_a_key_press_wakes_a_stopped_game():
    run = run_test("stop_wake", args=("--press", "30:START"))
    run.assert_passed()
    assert run.lines[:2] == ("stopping", "woke")


def test_a_stopped_game_that_nothing_wakes_ends_the_run():
    run = run_test("stop_wake")
    assert run.status == 0
    assert run.lines == ("stopping",)


def test_presses_must_name_keys_and_come_in_order():
    for script in (("--press", "3:JUMP"), ("--press", "9:A", "--press", "4:B"), ("--press", "A")):
        run = run_test("stop_wake", args=script)
        assert run.status == 2
        assert "usage:" in run.stderr


def test_a_key_held_from_the_start_requests_the_interrupt_once_keycnt_asks():
    run = run_test("stop_wake", args=("--press", "0:START"))
    run.assert_passed()  # the request came with the KEYCNT write: the Stop wakes at once
    assert run.lines[:2] == ("stopping", "woke")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_keypad.py`
Expected: FAIL — 3 failed, 2 passed. The keypad test and both wake-up tests end with `exit status 2: usage: ...`, because the host does not know `--press` yet. Two tests pass already:
- a Stop that nothing wakes still ends the run;
- `--press` misuse is a usage error (any unknown option was one).

- [ ] **Step 3: Write the keypad interrupt, Stop and the shared host code**

In `src/gbaport/native/build.py`, replace:
```python
)
HOSTS = {"headless": "host_headless.c"}
GENERATED_NAMES = ("gba_program.h", "gba_dispatch.c", "gba_rom.c", HEADER)  # plus gba_code_*.c
```
with:
```python
)
HOSTS = {"headless": ("host_common.c", "host_headless.c")}
GENERATED_NAMES = ("gba_program.h", "gba_dispatch.c", "gba_rom.c", HEADER)  # plus gba_code_*.c
```

In `src/gbaport/native/build.py`, replace:
```python
    objects = out / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    units = [*sorted(sources.glob("*.c")), *(RUNTIME / s for s in RUNTIME_SOURCES), RUNTIME / HOSTS[host]]

    def compile_unit(unit: Path) -> Path:
```
with:
```python
    objects = out / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    units = [*sorted(sources.glob("*.c")), *(RUNTIME / s for s in (*RUNTIME_SOURCES, *HOSTS[host]))]

    def compile_unit(unit: Path) -> Path:
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    case 0x02: gba_halt(rt); break;
    case 0x03: gba_end(rt, GBA_END_STOPPED); break;  /* nothing can wake a headless run */
    case 0x04: intr_wait(rt, ctx->r[0], ctx->r[1]); break;
```
with:
```c
    case 0x02: gba_halt(rt); break;
    case 0x03: gba_stop(rt); break;
    case 0x04: intr_wait(rt, ctx->r[0], ctx->r[1]); break;
```

In `src/gbaport/runtime/bios.c`, replace:
```c
        if (ctx->r[2] & 0x80)
            gba_end(rt, GBA_END_STOPPED);
        gba_halt(rt);
        break;
```
with:
```c
        if (ctx->r[2] & 0x80)
            gba_stop(rt);
        else
            gba_halt(rt);
        break;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
typedef enum {
    GBA_END_STOPPED = 0,  /* the game executed Stop and nothing can wake it (headless) */
    GBA_END_ERROR = 3,    /* see GbaRuntime.error */
```
with:
```c
typedef enum {
    GBA_END_STOPPED = 0,  /* the game executed Stop and the host had nothing to wake it */
    GBA_END_ERROR = 3,    /* see GbaRuntime.error */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    void (*diag)(GbaRuntime *rt, const char *text, void *user);  /* runtime warnings */
    void *user;
```
with:
```c
    void (*diag)(GbaRuntime *rt, const char *text, void *user);  /* runtime warnings */
    /* The game executed Stop: wait for input and pass it on with gba_set_keys, then return
     * 1 (the runtime calls again until a key wakes the game), or return 0 to end the run.
     * Without this callback a Stop ends the run. */
    int (*stopped)(GbaRuntime *rt, void *user);
    void *user;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    uint16_t keys_pressed;               /* GBA key bits, 1 = pressed */
    GbaSave save;
```
with:
```c
    uint16_t keys_pressed;               /* GBA key bits, 1 = pressed */
    uint16_t keys_last;                  /* at the last keypad check; 0x400: no match */
    GbaSave save;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_irq_changed(GbaRuntime *rt);      /* IE, IF or IME written */
void gba_halt(GbaRuntime *rt);             /* until IE & IF, then deliver the interrupt */

void gba_timer_write(GbaRuntime *rt, int n, uint16_t control);
```
with:
```c
void gba_irq_changed(GbaRuntime *rt);      /* IE, IF or IME written */
void gba_halt(GbaRuntime *rt);             /* until IE & IF, then deliver the interrupt */
void gba_stop(GbaRuntime *rt);             /* until a key wakes the game (host.stopped) */
void gba_keypad_check(GbaRuntime *rt);     /* may request the keypad interrupt */

void gba_timer_write(GbaRuntime *rt, int n, uint16_t control);
```

Create `src/gbaport/runtime/host_common.c`:
```c
/* host_common.c - the parts of a host that do not depend on a window.
 *
 * The save chip's contents live in a file (default: the ROM's path with .sav): loaded at
 * the start, stored once a second while they change and again at the end. Scripted key
 * presses (--press FRAME:KEYS) let tests and recordings drive the game: KEYS are names
 * joined with '+' (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or "none", held from
 * the FRAME-th VBlank on. While the game is stopped, time does not pass, so the next
 * scripted press comes at once. */
#define _CRT_SECURE_NO_WARNINGS
#include "host_common.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

/* The file's bytes, or NULL with errno set (ENOENT: there is no such file). */
static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(length > 0 ? (size_t)length : 1);
    if (data && length > 0 && fread(data, 1, (size_t)length, f) != (size_t)length) {
        free(data);
        data = NULL;
        errno = EIO;
    }
    fclose(f);
    *size = length > 0 ? (uint32_t)length : 0;
    return data;
}

/* Puts `from` in the place of `to` in one step; `to` stays as it was if that fails. */
static int replace_file(const char *from, const char *to)
{
#ifdef _WIN32
    return MoveFileExA(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) ? 0 : -1;
#else
    return rename(from, to);
#endif
}

/* Writes the save next to its file, then puts it in place: a crash or a failed write
 * leaves the previous save as it was. */
static void store_save(HostOptions *o, GbaRuntime *rt)
{
    uint32_t size;
    uint8_t *data = gba_save_data(rt, &size);
    if (!gba_save_dirty(rt) || size == 0)
        return;
    char temp[sizeof o->save_path + 4];
    snprintf(temp, sizeof temp, "%s.new", o->save_path);
    FILE *f = fopen(temp, "wb");
    int ok = f && fwrite(data, 1, size, f) == size;
    if (f)
        ok = fclose(f) == 0 && ok;
    if (ok && replace_file(temp, o->save_path) == 0) {
        gba_save_stored(rt);
        return;
    }
    if (f)
        remove(temp);
    fprintf(stderr, "warning: cannot write the save file %s\n", o->save_path);
}

static void default_save_path(HostOptions *o)
{
    char *path = o->save_path;
    size_t size = sizeof o->save_path;
    snprintf(path, size, "%s", o->rom_path);
    char *dot = strrchr(path, '.');
    char *slash = strrchr(path, '/'), *backslash = strrchr(path, '\\');
    if (dot && dot > slash && dot > backslash && strlen(path) + 4 < size)
        strcpy(dot, ".sav");
    else
        snprintf(path, size, "%s.sav", o->rom_path);
}

/* "FRAME:KEYS" into a press; returns 0, or -1 when it is not one. */
static int parse_press(const char *text, HostPress *press)
{
    char *end;
    press->frame = strtoul(text, &end, 10);
    if (end == text || *end != ':')
        return -1;
    press->keys = 0;
    const char *name = end + 1;
    if (strcmp(name, "none") == 0)
        return 0;
    while (*name) {
        size_t length = strcspn(name, "+");
        int found = -1;
        for (int k = 0; k < 10; k++)
            if (strlen(KEY_NAMES[k]) == length && strncmp(name, KEY_NAMES[k], length) == 0)
                found = k;
        if (found < 0)
            return -1;
        press->keys |= (uint16_t)(1u << found);
        name += length;
        if (*name == '+')
            name++;
    }
    return press->keys ? 0 : -1;
}

int host_parse(HostOptions *o, int argc, char **argv)
{
    int bad = 0;
    o->scale = 3;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i], *value = i + 1 < argc ? argv[i + 1] : NULL;
        if (strcmp(arg, "--frames") == 0 && value) {
            o->frame_limit = strtoul(value, NULL, 10);
            i++;
        } else if (strcmp(arg, "--save") == 0 && value) {
            snprintf(o->save_path, sizeof o->save_path, "%s", value);
            i++;
        } else if (strcmp(arg, "--press") == 0 && value) {
            HostPress *press = &o->presses[o->press_count];
            if (o->press_count == HOST_MAX_PRESSES || parse_press(value, press) != 0 ||
                (o->press_count && press->frame < press[-1].frame))
                bad = 1;
            else
                o->press_count++;
            i++;
        } else if (strcmp(arg, "--screenshot") == 0 && value) {
            o->screenshot = value;
            i++;
        } else if (strcmp(arg, "--registers") == 0) {
            o->registers = 1;
        } else if (o->window && strcmp(arg, "--scale") == 0 && value) {
            o->scale = atoi(value);
            bad |= o->scale < 1 || o->scale > 16;
            i++;
        } else if (o->window && strcmp(arg, "--fast") == 0) {
            o->fast = 1;
        } else if (!o->rom_path && arg[0] != '-') {
            o->rom_path = arg;
        } else {
            bad = 1;
        }
    }
    if (!o->rom_path || bad) {
        fprintf(stderr,
                "usage: %s ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... "
                "[--registers] [--screenshot PATH]%s\n",
                argv[0], o->window ? " [--scale N] [--fast]" : "");
        return 2;
    }
    if (!o->save_path[0])
        default_save_path(o);
    return 0;
}

int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host)
{
    uint32_t size;
    o->rom = read_file(o->rom_path, &size);
    if (!o->rom) {
        fprintf(stderr, "error: cannot read %s\n", o->rom_path);
        return 2;
    }
    if (gba_init(rt, o->rom, size, host) != 0) {
        fprintf(stderr, "error: %s\n", rt->error);
        return 2;
    }
    uint32_t save_size;
    uint8_t *save = read_file(o->save_path, &save_size);
    if (!save && errno != ENOENT) {
        fprintf(stderr, "error: cannot read the save file %s (it was left as it is)\n", o->save_path);
        return 2;
    }
    if (save && gba_save_load(rt, save, save_size) != 0) {
        fprintf(stderr, "error: %s: %s (the file was left as it is)\n", o->save_path, rt->error);
        return 2;
    }
    free(save);
    while (o->next_press < o->press_count && o->presses[o->next_press].frame == 0)
        o->script_keys = o->presses[o->next_press++].keys;
    gba_set_keys(rt, o->script_keys);
    return 0;
}

void host_frame(HostOptions *o, GbaRuntime *rt)
{
    while (o->next_press < o->press_count && o->presses[o->next_press].frame <= rt->frames)
        o->script_keys = o->presses[o->next_press++].keys;
    if (rt->frames % 60 == 0)
        store_save(o, rt);
    if (o->frame_limit && rt->frames >= o->frame_limit)
        gba_end(rt, GBA_END_HOST);
}

int host_script_wake(HostOptions *o)
{
    if (o->next_press == o->press_count)
        return 0;
    o->script_keys = o->presses[o->next_press++].keys;
    return 1;
}

int host_finish(HostOptions *o, GbaRuntime *rt, GbaEnd end)
{
    store_save(o, rt);
    if (o->registers) {
        GbaCtx *ctx = &rt->cpu;
        fprintf(stderr, "registers");
        for (int i = 0; i < 15; i++)
            fprintf(stderr, " r%d=%08x", i, (unsigned)ctx->r[i]);
        fprintf(stderr, " cpsr=%08x\n", (unsigned)gba_cpsr(ctx));
    }
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt->error);
    else if (end == GBA_END_HOST && o->frame_limit && rt->frames >= o->frame_limit)
        fprintf(stderr, "stopped after %lu frames\n", o->frame_limit);
    return (int)end;
}

int host_write_bmp(const char *path, const uint32_t *pixels)
{
    enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT, ROW = W * 3, DATA = ROW * H };
    uint8_t header[54] = {'B', 'M'};
    uint32_t fields[][2] = {  /* offset, value: little-endian 32-bit fields */
        {2, 54 + DATA}, {10, 54}, {14, 40}, {18, W}, {22, H}, {34, DATA},
    };
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        for (int b = 0; b < 4; b++)
            header[fields[i][0] + b] = (uint8_t)(fields[i][1] >> (8 * b));
    header[26] = 1;   /* planes */
    header[28] = 24;  /* bits per pixel */
    FILE *f = fopen(path, "wb");
    if (!f)
        return -1;
    fwrite(header, 1, sizeof header, f);
    for (int y = H - 1; y >= 0; y--) {  /* bottom row first */
        uint8_t row[ROW];
        for (int x = 0; x < W; x++) {
            uint32_t c = pixels[y * W + x];
            row[x * 3] = (uint8_t)c;
            row[x * 3 + 1] = (uint8_t)(c >> 8);
            row[x * 3 + 2] = (uint8_t)(c >> 16);
        }
        fwrite(row, 1, ROW, f);
    }
    return fclose(f) == 0 ? 0 : -1;
}
```

Create `src/gbaport/runtime/host_common.h`:
```c
/* host_common.h - what both hosts do the same way: the command line, the ROM and save
 * files, scripted key presses, the frame limit and the end of a run. */
#ifndef HOST_COMMON_H
#define HOST_COMMON_H

#include "gba_runtime.h"

enum { HOST_MAX_PRESSES = 64 };

typedef struct {
    unsigned long frame;  /* from this VBlank on (0: from the start) */
    uint16_t keys;        /* the GBA keys held, 1 = pressed */
} HostPress;

typedef struct {
    const char *rom_path;
    char save_path[1024];
    unsigned long frame_limit;  /* 0: no limit */
    int registers;              /* print the CPU registers when the run ends */
    const char *screenshot;     /* write the last picture there (BMP) */
    int window;                 /* the window host's options are allowed */
    int fast;                   /* window: no frame pacing */
    int scale;                  /* window: initial size in GBA screens */
    HostPress presses[HOST_MAX_PRESSES];
    int press_count, next_press;
    uint16_t script_keys;       /* what the presses so far hold */
    uint8_t *rom;
} HostOptions;

/* Reads the command line; prints the usage and returns 2 when it is wrong. */
int host_parse(HostOptions *o, int argc, char **argv);
/* Loads the ROM and the save file into rt; returns 0, or 2 after printing why not. */
int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host);
/* Once a frame: scripted presses due by now, the save file, the frame limit. */
void host_frame(HostOptions *o, GbaRuntime *rt);
/* While the game is stopped: applies the next scripted press; 0 when none is left. */
int host_script_wake(HostOptions *o);
/* Stores the save, reports the end and returns the exit status. */
int host_finish(HostOptions *o, GbaRuntime *rt, GbaEnd end);
/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
int host_write_bmp(const char *path, const uint32_t *pixels);

#endif
```

Create `src/gbaport/runtime/host_headless.c` (replacing the current version):
```c
/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--registers]
 *              [--screenshot PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Keys come only from --press (host_common.c). --registers prints the CPU registers when
 * the run ends; --screenshot writes the last picture as a BMP file.
 * Exit status: 0 the game executed Stop and no scripted press was left to wake it, 2 bad
 * arguments, the wrong ROM or an unusable save file, 3 a runtime error (for example code
 * the recompiler did not find), 4 the frame limit was reached. */
#include <stdio.h>

#include "host_common.h"

static HostOptions options;

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    host_frame(&options, rt);
    gba_set_keys(rt, options.script_keys);
}

static void on_log(GbaRuntime *rt, int level, const char *text, void *user)
{
    (void)rt, (void)level, (void)user;
    printf("%s\n", text);
    fflush(stdout);
}

static void on_diag(GbaRuntime *rt, const char *text, void *user)
{
    (void)rt, (void)user;
    fprintf(stderr, "warning: %s\n", text);
}

static int on_stopped(GbaRuntime *rt, void *user)
{
    (void)user;
    if (!host_script_wake(&options))
        return 0;
    gba_set_keys(rt, options.script_keys);
    return 1;
}

int main(int argc, char **argv)
{
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
    int status = host_parse(&options, argc, argv);
    if (status == 0)
        status = host_open(&options, &rt, &host);
    if (status != 0)
        return status;
    GbaEnd end = gba_run(&rt);
    if (options.screenshot) {
        static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
        gba_screen(&rt, pixels);
        if (host_write_bmp(options.screenshot, pixels) != 0)
            fprintf(stderr, "warning: cannot write %s\n", options.screenshot);
    }
    return host_finish(&options, &rt, end);
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
 * - DISPSTAT's status bits and VCOUNT belong to the scheduler; writes cannot change them.
 * - KEYINPUT comes from the host.
 * - IF clears the bits written as 1.
```
with:
```c
 * - DISPSTAT's status bits and VCOUNT belong to the scheduler; writes cannot change them.
 * - KEYINPUT comes from the host; KEYCNT can make the keys request an interrupt.
 * - IF clears the bits written as 1.
```

In `src/gbaport/runtime/io.c`, replace:
```c

void gba_reset_io(GbaRuntime *rt)
```
with:
```c

/* The keypad interrupt, as mGBA requests it: KEYCNT bit 14 enables it and bits 0-9 choose
 * keys. With bit 15 clear, any chosen key held requests it at every check (frame start,
 * new keys from the host, KEYCNT writes, Stop); with bit 15 set, all of them must be held,
 * and only a change of keys requests it again. */
void gba_keypad_check(GbaRuntime *rt)
{
    uint16_t control = IO(rt, GBA_REG_KEYCNT), chosen = control & 0x3FF;
    if (!(control & 0x4000))
        return;
    uint16_t last = rt->keys_last, keys = rt->keys_pressed;
    rt->keys_last = keys;
    if (control & 0x8000 && (keys & chosen) == chosen) {
        if (keys != last)
            gba_request_irq(rt, GBA_IRQ_KEYPAD);
    } else if (!(control & 0x8000) && (keys & chosen)) {
        gba_request_irq(rt, GBA_IRQ_KEYPAD);
    } else {
        rt->keys_last = 0x400;
    }
}

void gba_reset_io(GbaRuntime *rt)
```

In `src/gbaport/runtime/io.c`, replace:
```c
    IO(rt, GBA_REG_POSTFLG) = 0x0001;        /* booted */
}
```
with:
```c
    IO(rt, GBA_REG_POSTFLG) = 0x0001;        /* booted */
    rt->keys_last = 0x400;
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
        return;
    case GBA_REG_WAITCNT:
```
with:
```c
        return;
    case GBA_REG_KEYCNT:
        if (rt->keys_last < 0x400)  /* newly chosen keys count as changed (as in mGBA) */
            rt->keys_last &= old | ~merged;
        IO(rt, offset) = merged & 0xC3FF;
        gba_keypad_check(rt);
        return;
    case GBA_REG_WAITCNT:
```

In `src/gbaport/runtime/io.c`, replace:
```c
            if (value & 0x8000)
                gba_end(rt, GBA_END_STOPPED);  /* Stop: nothing wakes a headless run */
            gba_halt(rt);
        }
```
with:
```c
            if (value & 0x8000)
                gba_stop(rt);
            else
                gba_halt(rt);
        }
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
}

void gba_set_keys(GbaRuntime *rt, uint16_t pressed) { rt->keys_pressed = pressed & 0x3FF; }

/* ---- hooks from gba_cpu.h: what recompiled code cannot handle itself -------------- */
```
with:
```c
}

void gba_set_keys(GbaRuntime *rt, uint16_t pressed)
{
    rt->keys_pressed = pressed & 0x3FF;
    gba_keypad_check(rt);
}

/* ---- hooks from gba_cpu.h: what recompiled code cannot handle itself -------------- */
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
        gba_request_irq(rt, GBA_IRQ_VCOUNT);
    if (line == GBA_VISIBLE_LINES) {
```
with:
```c
        gba_request_irq(rt, GBA_IRQ_VCOUNT);
    if (line == 0)
        gba_keypad_check(rt);  /* at the start of every frame */
    if (line == GBA_VISIBLE_LINES) {
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c

/* Halt: skip ahead from event to event until an interrupt is requested and enabled in IE
```
with:
```c

/* Stop: the CPU, the clocks and the display stand still until a keypad, cartridge or
 * link interrupt that IE enables is requested. Only the keypad can request one here, and
 * only the host can press keys: it waits for input in its stopped callback. */
void gba_stop(GbaRuntime *rt)
{
    const uint16_t wake = GBA_IRQ_KEYPAD | GBA_IRQ_GAMEPAK | GBA_IRQ_SERIAL;
    gba_keypad_check(rt);  /* keys held already wake it, as at a frame start */
    while (!(IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & wake))
        if (!rt->host.stopped || !rt->host.stopped(rt, rt->host.user))
            gba_end(rt, GBA_END_STOPPED);
    while (irq_ready(rt))
        deliver(rt);
}

/* Halt: skip ahead from event to event until an interrupt is requested and enabled in IE
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 607 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms tests/runtime/test_keypad.py
git commit -m "feat: keypad interrupt, Stop that a key wakes, and scripted key presses"
```

---

### Task 8: The window host (SDL3)

**What it adds:**
- **The window program.** `gbaport build` makes it by default: `host_sdl.c` linked with SDL3.
- **SDL3 itself.**
  - `sdl3.py` builds it once from the pinned source release, with CMake's `FetchContent` and Ninja.
  - It installs the static library into the user's cache folder and links it with the flags from its `sdl3.pc`.
  - CMake and Ninja come from `$GBAPORT_CMAKE` / `$GBAPORT_NINJA`, the PATH, or the copies the Visual Studio Build Tools bundle.
- **`--host headless`** builds the headless program, now named `<game_code>-headless`.
- **In the window:**
  - The picture scales by whole steps.
  - Keyboard and the first gamepad drive the keys.
  - Frames are paced to 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns each.
  - A stopped game shows a dark screen and waits for a key.

**Files:**
- Create: `src/gbaport/native/sdl3.py`, `src/gbaport/native/sdl3_superbuild/CMakeLists.txt`, `src/gbaport/runtime/host_sdl.c`
- Modify: `src/gbaport/native/toolchain.py` (`find_cmake`, `find_ninja`), `src/gbaport/native/build.py` (the `sdl` host), `src/gbaport/cli.py` (`--host`)
- Modify: `tests/romtest.py` (`host=`). Window runs use `SDL_VIDEO_DRIVER=dummy`, so no window opens.
- Test: `tests/test_sdl3.py`, `tests/runtime/test_window.py`, `tests/test_build_cli.py`

**Interfaces:**
- Consumes: Task 7's `host_common.h` and `GbaHost.stopped`; Task 6's `gba_screen`; Plan 4b's `compile_native` salt loop.
- **Produces, Python:**
  - In `sdl3`: `SDL3_VERSION = "3.4.18"`, `SDL3_URL`, `SDL3_SHA256`, `cache_folder() -> Path`, `sdl3_prefix(log=print) -> Path` and `sdl3_flags(prefix) -> (include_flags, link_flags)`.
  - `toolchain.find_cmake()` and `find_ninja()`.
  - `HOSTS["sdl"]`.
  - `romtest.native_program(rom, host)`, `run_rom(..., host=...)` and `run_test(..., host=...)`.
- **Produces, the window program:**
  - **Options:** `[--scale N]` (1-16, default 3) and `[--fast]`, beside the shared ones.
  - **Exit status:**
    - 0 when the window is closed;
    - in a run limited by `--frames`, a Stop that no scripted press wakes ends the run, as in the headless host.

- [ ] **Step 1: Write the failing tests**

In `tests/romtest.py`, replace:
```python

ROMs and native builds are cached in the system temp folder by the hash of their sources.
```
with:
```python

Runs use the headless host unless they ask for the window host (``host="sdl"``), which
then runs with SDL's dummy video driver: no window opens.

ROMs and native builds are cached in the system temp folder by the hash of their sources.
```

In `tests/romtest.py`, replace:
```python
import hashlib
import struct
```
with:
```python
import hashlib
import os
import struct
```

In `tests/romtest.py`, replace:
```python

def native_program(rom: TestRom) -> Path:
    """Recompile ``rom`` and build it with the headless host (cached by the C sources)."""
    image = RomImage(rom.data)
```
with:
```python

def native_program(rom: TestRom, host: str = "headless") -> Path:
    """Recompile ``rom`` and build it with ``host`` (cached by the C sources)."""
    image = RomImage(rom.data)
```

In `tests/romtest.py`, replace:
```python
    sources = (f"{name}\n{text}" for name, text in sorted(files.items()))
    folder = CACHE / "native" / _digest(*sources, *runtime, flags)
    built = folder / "program.txt"  # written last: the build finished
    if not built.exists():
        native.write_sources(files, folder / "generated")
        program = native.compile_native(folder / "generated", folder / "build", "game")
        built.write_text(str(program), encoding="utf-8")
```
with:
```python
    sources = (f"{name}\n{text}" for name, text in sorted(files.items()))
    folder = CACHE / "native" / _digest(*sources, *runtime, flags, host)
    built = folder / "program.txt"  # written last: the build finished
    if not built.exists():
        native.write_sources(files, folder / "generated")
        program = native.compile_native(folder / "generated", folder / "build", "game", host)
        built.write_text(str(program), encoding="utf-8")
```

In `tests/romtest.py`, replace:
```python

def run_program(command: list[str]) -> subprocess.CompletedProcess:
    """Run a native program. Windows' Smart App Control sometimes blocks a program the
```
with:
```python

def run_program(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a native program. Windows' Smart App Control sometimes blocks a program the
```

In `tests/romtest.py`, replace:
```python
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except OSError as error:
```
with:
```python
        try:
            return subprocess.run(
                command, capture_output=True, text=True, timeout=120, check=False, env=env
            )
        except OSError as error:
```

In `tests/romtest.py`, replace:
```python
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    args: tuple[str, ...] = (),
) -> Run:
```
with:
```python
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (),
) -> Run:
```

In `tests/romtest.py`, replace:
```python
    """
    program = native_program(rom)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    with tempfile.TemporaryDirectory() as scratch:
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path), *args]
        result = run_program(command)
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)
```
with:
```python
    """
    program = native_program(rom, host)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy"} if host == "sdl" else None
    with tempfile.TemporaryDirectory() as scratch:
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path), *args]
        result = run_program(command, env)
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)
```

In `tests/romtest.py`, replace:
```python
def run_test(
    name: str, *, frames: int = 600, data: str = "", save: Path | None = None,
    args: tuple[str, ...] = (),
) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save, args=args)

def read_bmp(path: Path) -> list[int]:
```
with:
```python
def run_test(
    name: str, *, frames: int = 600, data: str = "", save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (),
) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save, host=host, args=args)


def read_bmp(path: Path) -> list[int]:
```

Create `tests/runtime/test_window.py`:
```python
"""The window host (SDL3), run with SDL's dummy video driver: no window opens."""

import time

from romtest import build_test_rom, read_bmp, run_rom, run_test

MODE3 = "#define DISPCNT 0x0403\n"
FRAME_SECONDS = 280896 / 16777216  # one GBA frame


def test_the_window_shows_what_the_headless_host_shows(tmp_path):
    rom = build_test_rom("bitmap", MODE3)
    window, headless = tmp_path / "window.bmp", tmp_path / "headless.bmp"
    run = run_rom(rom, frames=10, host="sdl", args=("--scale", "1", "--screenshot", str(window)))
    assert run.status == 4, run.stderr
    assert run_rom(rom, frames=10, args=("--screenshot", str(headless))).status == 4
    assert read_bmp(window) == read_bmp(headless)


def test_the_window_runs_at_the_gba_frame_rate_unless_fast():
    rom = build_test_rom("bitmap", MODE3)
    run_rom(rom, frames=1, host="sdl")  # builds the program, outside the timing

    def seconds(*args: str) -> float:
        start = time.perf_counter()
        run = run_rom(rom, frames=60, host="sdl", args=args)
        assert run.status == 4, run.stderr
        return time.perf_counter() - start

    paced, fast = seconds(), seconds("--fast")
    assert paced >= 59 * FRAME_SECONDS  # the first frame is not waited for
    assert fast < paced / 2


def test_the_window_host_takes_scripted_presses():
    run = run_test("stop_wake", host="sdl", args=("--press", "30:START"))
    run.assert_passed()
    assert run.lines[:2] == ("stopping", "woke")


def test_the_window_host_refuses_a_bad_scale():
    for scale in ("0", "17"):
        run = run_test("stop_wake", host="sdl", args=("--scale", scale))
        assert run.status == 2
    assert "[--scale N] [--fast]" in run.stderr


def test_the_window_host_stores_a_save_written_before_a_runtime_error(tmp_path):
    save = tmp_path / "game.sav"
    run = run_test("save_then_fail", host="sdl", save=save)
    assert run.status == 3
    assert save.read_bytes()[0x40] == 0x42
```

Create `tests/test_build_cli.py` (replacing the current version):
```python
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
```

Create `tests/test_sdl3.py`:
```python
"""Finding the tools SDL3's build needs, and what a failed build says (the real build runs
in tests/runtime/test_window.py)."""

import pytest

from gbaport.native import sdl3, toolchain
from gbaport.native.toolchain import ToolchainError


def test_the_cache_folder_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path))
    assert sdl3.cache_folder() == tmp_path


def test_missing_cmake_and_ninja_say_how_to_get_them(monkeypatch, tmp_path):
    for name in ("GBAPORT_CMAKE", "GBAPORT_NINJA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: None)
    monkeypatch.setattr(toolchain, "PROGRAM_FILES", (tmp_path,))  # no Visual Studio here
    with pytest.raises(ToolchainError, match="winget install Kitware.CMake"):
        toolchain.find_cmake()
    with pytest.raises(ToolchainError, match="winget install Ninja-build.Ninja"):
        toolchain.find_ninja()


def test_a_failed_download_stops_the_build_with_cmake_s_output(monkeypatch, tmp_path):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path))
    monkeypatch.setattr(sdl3, "SDL3_URL", (tmp_path / "missing.tar.gz").as_posix())
    with pytest.raises(ToolchainError, match="building SDL3 failed"):
        sdl3.sdl3_prefix(log=lambda text: None)
    assert not (tmp_path / f"sdl3-{sdl3.SDL3_VERSION}" / "lib").exists()


def test_the_link_flags_come_from_sdl3_pc(tmp_path):
    (tmp_path / "lib" / "pkgconfig").mkdir(parents=True)
    (tmp_path / "lib" / "pkgconfig" / "sdl3.pc").write_text(
        "prefix=/somewhere\nLibs: -L${libdir}  -lSDL3-static -lwinmm\nCflags: -I${includedir}\n",
        encoding="utf-8",
    )
    include, libraries = sdl3.sdl3_flags(tmp_path)
    assert include == [f"-I{tmp_path / 'include'}"]
    assert libraries == [f"-L{tmp_path / 'lib'}", "-lSDL3-static", "-lwinmm"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sdl3.py`
Expected: FAIL — `ImportError: cannot import name 'sdl3' from 'gbaport.native'`

Run: `uv run pytest tests/runtime/test_window.py tests/test_build_cli.py`
Expected: FAIL — 7 failed.
- The window tests fail with `KeyError: 'sdl'`.
- The build tests fail with `gbaport: error: unrecognized arguments: --host headless`, or, for the default build, with the missing `[--scale N] [--fast]` in the program's usage.

- [ ] **Step 3: Build SDL3, write the window host, and add `--host`**

In `src/gbaport/cli.py`, replace:
```python
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import compile_native, generated_sources, write_sources
from gbaport.rom.header import parse_header
```
with:
```python
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.rom.header import parse_header
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
        "--host",
        choices=sorted(HOSTS),
        default="sdl",
        help="sdl: a window (the default; builds SDL3 the first time); headless: no window",
    )
    build.set_defaults(handler=_run_build)
```

In `src/gbaport/cli.py`, replace:
```python
    _recompile(args, rom, root / "generated")
    program = compile_native(root / "generated", root / "build", game_code)
    print(f"built {program}")
    print(f"run it with: {program} {args.rom} [--frames N]")
    return 0
```
with:
```python
    _recompile(args, rom, root / "generated")
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
    program = compile_native(root / "generated", root / "build", name, args.host)
    print(f"built {program}")
    print(f"run it with: {program} {args.rom} [--save PATH] [--frames N]")
    return 0
```

In `src/gbaport/native/build.py`, replace:
```python
(the runtime refuses any other ROM) and which save chip the game has. ``compile_native``
compiles those sources together with the runtime in ``gbaport/runtime`` and one host
(``host_headless.c`` so far).
"""
```
with:
```python
(the runtime refuses any other ROM) and which save chip the game has. ``compile_native``
compiles those sources together with the runtime in ``gbaport/runtime`` and one host:
``sdl`` (a window, with SDL3 from ``sdl3.py``) or ``headless`` (for tests and scripts).
"""
```

In `src/gbaport/native/build.py`, replace:
```python
from gbaport.lift.program import HEADER, LiftedProgram, program_files
from gbaport.native.toolchain import ToolchainError, find_clang
```
with:
```python
from gbaport.lift.program import HEADER, LiftedProgram, program_files
from gbaport.native.sdl3 import sdl3_flags, sdl3_prefix
from gbaport.native.toolchain import ToolchainError, find_clang
```

In `src/gbaport/native/build.py`, replace:
```python
)
HOSTS = {"headless": ("host_common.c", "host_headless.c")}
GENERATED_NAMES = ("gba_program.h", "gba_dispatch.c", "gba_rom.c", HEADER)  # plus gba_code_*.c
```
with:
```python
)
HOSTS = {"headless": ("host_common.c", "host_headless.c"), "sdl": ("host_common.c", "host_sdl.c")}
GENERATED_NAMES = ("gba_program.h", "gba_dispatch.c", "gba_rom.c", HEADER)  # plus gba_code_*.c
```

In `src/gbaport/native/build.py`, replace:
```python
    clang = find_clang()
    objects = out / "obj"
```
with:
```python
    clang = find_clang()
    include, libraries = sdl3_flags(sdl3_prefix()) if host == "sdl" else ([], [])
    objects = out / "obj"
```

In `src/gbaport/native/build.py`, replace:
```python
        obj = objects / f"{unit.stem}.o"
        command = [clang, *CFLAGS, f"-I{sources}", f"-I{RUNTIME}", "-c", str(unit), "-o", str(obj)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
```
with:
```python
        obj = objects / f"{unit.stem}.o"
        command = [clang, *CFLAGS, f"-I{sources}", f"-I{RUNTIME}", *include, "-c", str(unit), "-o", str(obj)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
```

In `src/gbaport/native/build.py`, replace:
```python
    program = out / (name + (".exe" if os.name == "nt" else ""))
    _link(clang, compiled, program)
    for _ in range(SALTED_REBUILDS):
```
with:
```python
    program = out / (name + (".exe" if os.name == "nt" else ""))
    _link(clang, compiled, program, libraries)
    for _ in range(SALTED_REBUILDS):
```

In `src/gbaport/native/build.py`, replace:
```python
        salt.write_text(f'const char gba_build_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _link(clang, [*compiled, compile_unit(salt)], program)
    if _starts(program):
```
with:
```python
        salt.write_text(f'const char gba_build_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _link(clang, [*compiled, compile_unit(salt)], program, libraries)
    if _starts(program):
```

In `src/gbaport/native/build.py`, replace:
```python

def _link(clang: str, objects: list[Path], program: Path) -> None:
    result = subprocess.run(
        [clang, *(str(obj) for obj in objects), "-o", str(program)],
        capture_output=True, text=True, check=False,
```
with:
```python

def _link(clang: str, objects: list[Path], program: Path, libraries: list[str]) -> None:
    result = subprocess.run(
        [clang, *(str(obj) for obj in objects), *libraries, "-o", str(program)],
        capture_output=True, text=True, check=False,
```

Create `src/gbaport/native/sdl3.py`:
```python
"""SDL3 for the window host: built once from source with CMake and Ninja, then reused.

CMake's FetchContent downloads the pinned source release and checks its SHA-256
(``sdl3_superbuild/CMakeLists.txt``); clang builds it as a static library, installed into
the cache folder, so every game links the same build. The cache folder is ``$GBAPORT_CACHE`` or the user's
cache folder (``%LOCALAPPDATA%\\gbaport`` on Windows).
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

SDL3_VERSION = "3.4.18"
SDL3_URL = (
    f"https://github.com/libsdl-org/SDL/releases/download/release-{SDL3_VERSION}/"
    f"SDL3-{SDL3_VERSION}.tar.gz"
)
SDL3_SHA256 = "9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3"
SUPERBUILD = Path(__file__).parent / "sdl3_superbuild"


def cache_folder() -> Path:
    if os.environ.get("GBAPORT_CACHE"):
        return Path(os.environ["GBAPORT_CACHE"])
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "gbaport"


def sdl3_prefix(log: Callable[[str], None] = print) -> Path:
    """The folder SDL3 is installed in, building it first if it is not there yet."""
    prefix = cache_folder() / f"sdl3-{SDL3_VERSION}"
    if (prefix / "lib" / "pkgconfig" / "sdl3.pc").exists():
        return prefix
    log(f"building SDL3 {SDL3_VERSION} into {prefix} (once; it takes a minute or two)")
    work = cache_folder() / f"sdl3-{SDL3_VERSION}-build"
    shutil.rmtree(work, ignore_errors=True)
    cmake = find_cmake()
    configure = [
        cmake, "-S", str(SUPERBUILD), "-B", str(work), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={_forward(find_ninja())}", f"-DCMAKE_C_COMPILER={_forward(find_clang())}",
        "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_INSTALL_PREFIX={_forward(prefix)}",
        f"-DGBAPORT_SDL3_URL={SDL3_URL}", f"-DGBAPORT_SDL3_SHA256={SDL3_SHA256}",
    ]
    if os.name == "nt":  # clang's GNU-style driver needs LLVM's resource compiler
        configure.append(f"-DCMAKE_RC_COMPILER={_forward(llvm_tool('llvm-rc'))}")
    for command in (configure, [cmake, "--build", str(work)], [cmake, "--install", str(work)]):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output = (result.stdout + result.stderr)[-4000:]
            raise ToolchainError(f"building SDL3 failed ({command[1]} {command[2]}):\n{output}")
    shutil.rmtree(work, ignore_errors=True)
    return prefix


def sdl3_flags(prefix: Path) -> tuple[list[str], list[str]]:
    """The compile and link flags for the SDL3 in ``prefix`` (from its sdl3.pc)."""
    libs = []
    for line in (prefix / "lib" / "pkgconfig" / "sdl3.pc").read_text(encoding="utf-8").splitlines():
        if line.startswith("Libs:"):
            libs = [flag for flag in line.split()[1:] if not flag.startswith("-L")]
    return [f"-I{prefix / 'include'}"], [f"-L{prefix / 'lib'}", *libs]


def _forward(path: str | Path) -> str:
    """A path for a CMake -D value: CMake reads backslashes as escapes."""
    return Path(path).as_posix()
```

Create `src/gbaport/native/sdl3_superbuild/CMakeLists.txt`:
```cmake
# Builds SDL3 as a static library for gbaport's window host (gbaport/native/sdl3.py runs
# this). The source release comes from GBAPORT_SDL3_URL and must match GBAPORT_SDL3_SHA256.
cmake_minimum_required(VERSION 3.28)
project(gbaport_sdl3 LANGUAGES C)

include(FetchContent)
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_INSTALL ON CACHE BOOL "" FORCE)
FetchContent_Declare(SDL3 URL "${GBAPORT_SDL3_URL}" URL_HASH "SHA256=${GBAPORT_SDL3_SHA256}")
FetchContent_MakeAvailable(SDL3)
```

Create `src/gbaport/native/toolchain.py` (replacing the current version):
```python
"""Finding the build tools.

clang: $GBAPORT_CLANG, then PATH, then the LLVM installer's Windows location. CMake and
Ninja (for SDL3): $GBAPORT_CMAKE / $GBAPORT_NINJA, then PATH, then the copies the Visual
Studio Build Tools bundle.
"""

import os
import shutil
from pathlib import Path

WINDOWS_LLVM = Path(r"C:\Program Files\LLVM\bin\clang.exe")
VISUAL_STUDIO_CMAKE = "Microsoft Visual Studio/*/*/Common7/IDE/CommonExtensions/Microsoft/CMake"
PROGRAM_FILES = (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"))


class ToolchainError(OSError):
    """A compiler or tool the build needs is missing or failed."""


def find_clang() -> str:
    found = os.environ.get("GBAPORT_CLANG") or shutil.which("clang")
    if found:
        return found
    if WINDOWS_LLVM.exists():
        return str(WINDOWS_LLVM)
    raise ToolchainError("clang not found: install LLVM (winget install LLVM.LLVM) or set GBAPORT_CLANG")


def llvm_tool(name: str) -> str:
    """Another LLVM tool (ld.lld, llvm-objcopy) from the directory clang is in."""
    folder = Path(find_clang()).parent
    for candidate in (folder / f"{name}.exe", folder / name):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise ToolchainError(f"{name} not found next to clang ({folder})")


def _bundled(relative: str) -> str | None:
    """A tool inside a Visual Studio installation's CMake folder, if there is one."""
    for root in PROGRAM_FILES:
        for candidate in sorted(root.glob(f"{VISUAL_STUDIO_CMAKE}/{relative}"), reverse=True):
            return str(candidate)
    return None


def find_cmake() -> str:
    found = os.environ.get("GBAPORT_CMAKE") or shutil.which("cmake") or _bundled("CMake/bin/cmake.exe")
    if found:
        return found
    raise ToolchainError("CMake not found: winget install Kitware.CMake, or set GBAPORT_CMAKE")


def find_ninja() -> str:
    found = os.environ.get("GBAPORT_NINJA") or shutil.which("ninja") or _bundled("Ninja/ninja.exe")
    if found:
        return found
    raise ToolchainError("Ninja not found: winget install Ninja-build.Ninja, or set GBAPORT_NINJA")
```

Create `src/gbaport/runtime/host_sdl.c`:
```c
/* host_sdl.c - run a recompiled game in a window (SDL3).
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--registers]
 *              [--screenshot PATH] [--scale N] [--fast]
 *
 * Keyboard: arrows, X = A, Z = B, A = L, S = R, Enter = Start, Backspace = Select. A
 * gamepad works too: its right face button is A, the bottom one B. The game runs at the
 * GBA's 59.73 frames a second (--fast: as fast as it can); the window scales the picture
 * by whole steps (--scale: the starting size in GBA screens, 3 by default). Closing the
 * window ends the run with exit status 0. While the game is stopped (the BIOS Stop call)
 * the screen is dark and a key press wakes it, if the game asked for that; in a run
 * limited by --frames, a Stop that no scripted press wakes ends the run instead. The other
 * options and exit statuses are those of host_headless.c. */
#include <stdio.h>
#include <string.h>

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include "host_common.h"

#define FRAME_NS 16742706u  /* 280896 cycles at 16.78 MHz: 16742706 + 153/512 ns */

static HostOptions options;
static SDL_Window *window;
static SDL_Renderer *renderer;
static SDL_Texture *texture;
static SDL_Gamepad *gamepad;
static uint32_t pixels[GBA_SCREEN_WIDTH * GBA_SCREEN_HEIGHT];
static int closed;
static Uint64 pace_start, paced;

static const SDL_Scancode KEYBOARD[10] = {
    SDL_SCANCODE_X, SDL_SCANCODE_Z, SDL_SCANCODE_BACKSPACE, SDL_SCANCODE_RETURN,
    SDL_SCANCODE_RIGHT, SDL_SCANCODE_LEFT, SDL_SCANCODE_UP, SDL_SCANCODE_DOWN,
    SDL_SCANCODE_S, SDL_SCANCODE_A,
};
static const SDL_GamepadButton BUTTONS[10] = {
    SDL_GAMEPAD_BUTTON_EAST, SDL_GAMEPAD_BUTTON_SOUTH, SDL_GAMEPAD_BUTTON_BACK,
    SDL_GAMEPAD_BUTTON_START, SDL_GAMEPAD_BUTTON_DPAD_RIGHT, SDL_GAMEPAD_BUTTON_DPAD_LEFT,
    SDL_GAMEPAD_BUTTON_DPAD_UP, SDL_GAMEPAD_BUTTON_DPAD_DOWN,
    SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,
};

static void handle(const SDL_Event *event)
{
    if (event->type == SDL_EVENT_QUIT)
        closed = 1;
    else if (event->type == SDL_EVENT_GAMEPAD_ADDED && !gamepad)
        gamepad = SDL_OpenGamepad(event->gdevice.which);
    else if (event->type == SDL_EVENT_GAMEPAD_REMOVED && gamepad &&
             SDL_GetGamepadID(gamepad) == event->gdevice.which) {
        SDL_CloseGamepad(gamepad);
        gamepad = NULL;
    }
}

/* The keys held on the keyboard, the gamepad and in the script. */
static uint16_t held_keys(void)
{
    const bool *keyboard = SDL_GetKeyboardState(NULL);
    uint16_t keys = options.script_keys;
    for (int k = 0; k < 10; k++) {
        if (keyboard[KEYBOARD[k]] || (gamepad && SDL_GetGamepadButton(gamepad, BUTTONS[k])))
            keys |= (uint16_t)(1u << k);
    }
    if (gamepad) {  /* the left stick works as the D-pad */
        Sint16 x = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTX);
        Sint16 y = SDL_GetGamepadAxis(gamepad, SDL_GAMEPAD_AXIS_LEFTY);
        keys |= (uint16_t)((x > 16000) << 4 | (x < -16000) << 5 | (y < -16000) << 6 | (y > 16000) << 7);
    }
    return keys;
}

static void present(void)
{
    SDL_UpdateTexture(texture, NULL, pixels, GBA_SCREEN_WIDTH * 4);
    SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255);
    SDL_RenderClear(renderer);
    SDL_RenderTexture(renderer, texture, NULL, NULL);
}

/* Waits until this frame's time has come; after falling behind by more than a few
 * frames (a slow machine, a dragged window) it starts counting again instead of rushing. */
static void pace(void)
{
    if (options.fast)
        return;
    Uint64 now = SDL_GetTicksNS();
    if (paced == 0)
        pace_start = now;
    paced++;
    Uint64 due = pace_start + paced * FRAME_NS + paced * 153u / 512u;
    if (now < due)
        SDL_DelayPrecise(due - now);
    else if (now - due > 4ull * FRAME_NS)
        paced = 0;
}

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    SDL_Event event;
    while (SDL_PollEvent(&event))
        handle(&event);
    if (closed)
        gba_end(rt, GBA_END_HOST);
    gba_screen(rt, pixels);
    present();
    SDL_RenderPresent(renderer);
    pace();
    host_frame(&options, rt);
    gba_set_keys(rt, held_keys());
}

static void on_log(GbaRuntime *rt, int level, const char *text, void *user)
{
    (void)rt, (void)level, (void)user;
    printf("%s\n", text);
    fflush(stdout);
}

static void on_diag(GbaRuntime *rt, const char *text, void *user)
{
    (void)rt, (void)user;
    fprintf(stderr, "warning: %s\n", text);
}

/* Stopped: a dark screen until the keys change (or the script presses some). */
static int on_stopped(GbaRuntime *rt, void *user)
{
    (void)user;
    memset(pixels, 0, sizeof pixels);
    present();
    SDL_RenderPresent(renderer);
    if (host_script_wake(&options)) {
        gba_set_keys(rt, held_keys());
        return 1;
    }
    if (options.frame_limit)  /* a run limited by --frames is scripted: end it, as headless */
        return 0;
    uint16_t before = held_keys();
    while (!closed) {
        SDL_Event event;
        if (SDL_WaitEventTimeout(&event, 100))
            handle(&event);
        if (held_keys() != before) {
            gba_set_keys(rt, held_keys());
            paced = 0;  /* the clocks stood still: do not rush to catch up */
            return 1;
        }
    }
    gba_end(rt, GBA_END_HOST);
    return 0;
}

static int open_window(void)
{
    if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        fprintf(stderr, "error: cannot start SDL: %s\n", SDL_GetError());
        return -1;
    }
    char title[64] = "gbaport";
    if (options.rom) {  /* the cartridge's title, 12 characters at 0xA0 */
        char name[13] = {0};
        memcpy(name, options.rom + 0xA0, 12);
        snprintf(title, sizeof title, "%s - gbaport", name);
    }
    int w = GBA_SCREEN_WIDTH * options.scale, h = GBA_SCREEN_HEIGHT * options.scale;
    if (!SDL_CreateWindowAndRenderer(title, w, h, SDL_WINDOW_RESIZABLE, &window, &renderer)) {
        fprintf(stderr, "error: cannot open a window: %s\n", SDL_GetError());
        return -1;
    }
    SDL_SetRenderLogicalPresentation(renderer, GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT,
                                     SDL_LOGICAL_PRESENTATION_INTEGER_SCALE);
    texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_XRGB8888, SDL_TEXTUREACCESS_STREAMING,
                                GBA_SCREEN_WIDTH, GBA_SCREEN_HEIGHT);
    if (!texture) {
        fprintf(stderr, "error: cannot make the screen texture: %s\n", SDL_GetError());
        return -1;
    }
    SDL_SetTextureScaleMode(texture, SDL_SCALEMODE_NEAREST);
    return 0;
}

/* The window's picture, as the last frame left it, into a BMP file. */
static void screenshot(void)
{
    present();
    SDL_Surface *shot = SDL_RenderReadPixels(renderer, NULL);
    if (!shot || !SDL_SaveBMP(shot, options.screenshot))
        fprintf(stderr, "warning: cannot write %s: %s\n", options.screenshot, SDL_GetError());
    SDL_DestroySurface(shot);
}

int main(int argc, char **argv)
{
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, on_stopped, NULL};
    options.window = 1;
    int status = host_parse(&options, argc, argv);
    if (status == 0)
        status = host_open(&options, &rt, &host);
    if (status != 0)
        return status;
    if (open_window() != 0)
        return 2;
    GbaEnd end = gba_run(&rt);
    if (options.screenshot)
        screenshot();
    status = host_finish(&options, &rt, end);
    SDL_Quit();
    return closed ? 0 : status;
}
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 617 passed; ruff clean.
- The first run builds SDL3: it downloads 15.6 MB from GitHub and takes about two minutes before the window tests run. It prints nothing while it works.
- Later runs reuse `%LOCALAPPDATA%\gbaport\sdl3-3.4.18`.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/native src/gbaport/runtime/host_sdl.c src/gbaport/cli.py tests/romtest.py tests/test_sdl3.py tests/runtime/test_window.py tests/test_build_cli.py
git commit -m "feat: the window host, with SDL3 built once from source"
```

---

### Task 9: README, spec, and a smoke test in a real window

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Write the documentation**

In `README.md`, replace:
```markdown
The runtime tests build small GBA test ROMs from C (`tests/gbaroms`) with clang and
ld.lld, recompile them and run them natively; ROMs and builds are cached in
`gbaport-romcache`.

## Commands
```
with:
```markdown
The runtime tests build small GBA test ROMs from C (`tests/gbaroms`) with clang and
ld.lld, recompile them and run them natively; ROMs and builds are cached in
`gbaport-romcache`. They also download and run jsmolka's CPU test ROMs (MIT licence;
`tests/publicroms/jsmolka` has their configs), so the first run needs a network
connection. The window tests build SDL3 the first time (see below) and run with SDL's
dummy video driver, so no window opens.

## Commands
```

In `README.md`, replace:
```markdown

`gbaport build` recompiles the game and compiles it with the runtime into
`games/<game_code>/build/<game_code>.exe`. Run it with the ROM it was built from:

    games/XXXX/build/XXXX.exe roms/mygame.gba [--frames N] [--save PATH]

It runs without a window for now (the desktop window comes in Plan 4c). Lines the game
prints through mGBA's debug log go to stdout. It exits with 0 when the game executes the
BIOS Stop call, 2 for bad arguments, a different ROM or an unusable save file, 3 for a
runtime error, and 4 when `--frames` runs out.

The game's save chip (SRAM, Flash or EEPROM, as its library ID string or `game.toml`'s
```
with:
```markdown

`gbaport build` recompiles the game and compiles it with the runtime into
`games/<game_code>/build/<game_code>.exe`, which runs the game in a window. Run it with
the ROM it was built from:

    games/XXXX/build/XXXX.exe roms/mygame.gba [--save PATH] [--scale N] [--fast]

Keys: arrows, X = A, Z = B, A = L, S = R, Enter = Start, Backspace = Select. A gamepad
works too: its right face button is A, the bottom one B. The game runs at the GBA's 59.73
frames a second (`--fast`: as fast as it can), and the picture grows with the window by
whole steps (`--scale`: the starting size, 3 by default). Until the renderer arrives
(Plan 5) only the bitmap modes are drawn; a game that draws with tiles shows its backdrop
colour. Closing the window ends the run.

The first build also builds SDL3 3.4.18 from source, once, into `%LOCALAPPDATA%\gbaport`
(`GBAPORT_CACHE` moves it). That needs CMake and Ninja (the Visual Studio Build Tools
include both; elsewhere `winget install Kitware.CMake Ninja-build.Ninja`), a network
connection, and a minute or two.

`gbaport build --host headless` builds `<game_code>-headless.exe` instead, which runs
without a window, for tests and scripts. Both programs take:

- `--frames N`: end after N frames;
- `--save PATH`: the save file (below);
- `--press FRAME:KEYS`: hold KEYS from that frame on (repeatable). KEYS are A, B, SELECT,
  START, RIGHT, LEFT, UP, DOWN, R and L joined with `+`, or `none`;
- `--registers`: print the CPU registers when the run ends;
- `--screenshot PATH`: save the last picture as a BMP file.

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
(the window waits for a key instead, unless `--frames` limits the run); 2 for bad
arguments, a different ROM or an unusable save file; 3 for a runtime error; 4 when
`--frames` runs out.

The game's save chip (SRAM, Flash or EEPROM, as its library ID string or `game.toml`'s
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- CMake ≥ 3.28 and Ninja (bundled with the MSVC Build Tools; elsewhere
  `winget install Kitware.CMake Ninja-build.Ninja`) — Plan 4c. Plan 4a builds with clang
  directly.
- SDL3 (fetched by CMake `FetchContent`) — Plan 4c.
- Android SDK + NDK r27 or newer (Android Studio or `sdkmanager`) — Plan 8.
```
with:
```markdown
- CMake ≥ 3.28 and Ninja (bundled with the MSVC Build Tools; elsewhere
  `winget install Kitware.CMake Ninja-build.Ninja`) — Plan 4c, for SDL3. Games still
  build with clang directly.
- SDL3 3.4.18 (fetched by CMake `FetchContent`, built once as a static library into the
  user's cache folder) — Plan 4c.
- Android SDK + NDK r27 or newer (Android Studio or `sdkmanager`) — Plan 8.
```

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 617 passed; ruff clean.

- [ ] **Step 3: Smoke-test the window host**

Run, from the repo root:

```bash
uv run python -m gbaport.cli build roms/mygame.gba --out build/bt4e
SDL_VIDEO_DRIVER=dummy build/bt4e/build/BT4E.exe roms/mygame.gba --frames 600 --save build/bt4e/bt4e.sav; echo "exit $?"
ARM="$(uv run python -c 'import tempfile; print(tempfile.gettempdir())')/gbaport-romcache/jsmolka/arm.gba"
uv run python -m gbaport.cli build "$ARM" --config tests/publicroms/jsmolka/arm.toml --out build/jsmolka-arm
build/jsmolka-arm/build/1337.exe "$ARM" --frames 300 --screenshot build/jsmolka-arm/window.bmp; echo "exit $?"
```

Expected (validated before this plan was approved):
- **BT4E build:** `config games\BT4E\game.toml`, `functions 577`, `lift issues 0`, then `built build\bt4e\build\BT4E.exe`.
- **BT4E run:** `stopped after 600 frames` and exit 4 after about 10 seconds (600 frames at 59.73 a second). `build/bt4e/bt4e.sav` holds 8192 bytes.
- **jsmolka's `arm.gba` in a real window** (Task 2's tests downloaded it), shown on the desktop for five seconds: it opens at three times the GBA's size, shows "All tests passed", and closes by itself with `stopped after 300 frames` and exit 4. `window.bmp` is the window's picture.
- **Afterwards, by hand** (not part of the plan's checks), the user can play with the keyboard: `build/bt4e/build/BT4E.exe roms/mygame.gba`. BT4E draws with tiles, so until Plan 5 the window shows only the game's backdrop colour.

Record the numbers in the ledger.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: the window host, SDL3, scripted presses and the public test ROMs"
```

---

## Done criteria for Plan 4c

- `uv run pytest` passes 617 tests and `uv run ruff check src tests` is clean.
- **jsmolka's test ROMs** `arm`, `thumb`, `memory`, `bios`, `sram`, `flash64`, `flash128` and `none` pass when recompiled. Getting there fixed four defects:
  - compares with Rd = 15;
  - empty register lists;
  - the BIOS bus value around interrupts;
  - stores to the save chip.
- **`gbaport build`** makes a window program by default:
  - it builds SDL3 once;
  - keyboard and gamepad input work;
  - frames are paced to 59.73 a second;
  - the bitmap modes are on screen.
- **Stop** sleeps until a chosen key requests the keypad interrupt, which follows mGBA's rules.
- **Both hosts** take `--frames`, `--save`, `--press`, `--registers` and `--screenshot`.
- **A test ROM runs in a window:** jsmolka's `arm.gba` shows "All tests passed" (Task 9's smoke test).
