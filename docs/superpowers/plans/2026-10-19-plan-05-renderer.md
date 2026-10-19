# Plan 5: Scanline Renderer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompiled games show their whole picture: display modes 0-5, text and rotation/scaling backgrounds, sprites, windows, colour effects and mosaic, drawn a line at a time so raster effects work. Every picture the tests make is compared, pixel for pixel, with mGBA's.

**Architecture:**
- **One line at a time.** A new `render.c` draws line y when the line's HDraw ends, before the HBlank interrupt and HBlank DMA (as mGBA does). It reads the registers, VRAM, palette and OAM as they are at that moment. So a game that changes them between lines (HBlank DMA, VCOUNT interrupts) gets its raster effects.
- **The picture stays in GBA colours.** `rt->screen` holds 240×160 15-bit colours. `screen.c` only widens them to 0x00RRGGBB for the hosts, so the hosts do not change.
- **Layers, then composition.** Each line draws every enabled background and the sprites into rows of their own, with a CLEAR marker where nothing is drawn. It then works out each pixel's window and composes the top two layers with the colour effects.
- **Reference points.** BG2's and BG3's internal reference points restart at VBlank (line 160). They step by (PB, PD) after each line drawn, and restart from the register whenever a game writes BGxX or BGxY.
- **mGBA as the oracle.** The tests build mGBA 0.10.5's GBA core from source, once, into a small program that writes a ROM's picture after N frames. Every renderer test compares the native build's screenshot with it, pixel for pixel, as 15-bit colours. A mismatch writes mGBA's picture, ours and the differences side by side as a PNG, and the message names it.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime built with clang 23; mGBA 0.10.5 (MPL-2.0; the source tarball, pinned by SHA-256, built by the tests with CMake, Ninja and clang); jsmolka/gba-tests' PPU ROMs at the commit Plan 4c pinned.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Roadmap row P5, verbatim: "P5 Renderer | Scanline renderer, all modes/features, per-line latching | Reference-image tests on graphics test ROMs | P4a".
  - The renderer, verbatim: "Scanline software renderer in C reproducing GBA compositing (modes 0–5, sprites, affine, windows, blending, mosaic), with per-scanline register latching so raster effects work. Output 240×160 RGBA, upscaled by the GPU in the host." (The runtime keeps GBA colours; the hosts already widen and scale them, Plan 4c.)
  - "Emulators are dev-time test oracles only." mGBA is built by the tests and never linked into a game. Where GBATEK is unclear, the renderer does what mGBA does. Where mGBA takes a shortcut the GBA does not take (Known limitations), the renderer follows the GBA and the tests stay away from that case.
  - "No ROM-derived bytes in git." Test ROMs are built at test time. jsmolka's PPU ROMs are downloaded at test time, pinned by commit and SHA-1 (`.gitignore` ignores every `*.gba`).
  - "Python tooling, C11 runtime, clang everywhere." mGBA is built with the same CMake, Ninja and clang as SDL3 (Plan 4c).
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Never commit a `.gba` file: the user's ROMs stay untracked.
  - Tests never open a window.
- **Commands:**
  - Use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher.
  - Run `uv run pytest` and `uv run ruff check src tests` as separate commands.
  - The first test run downloads mGBA's source (about 14 MB) and builds it (a few minutes). Later runs reuse the build in `%LOCALAPPDATA%\gbaport`.

## Review Focus

1. **Display modes 6 and 7, which do not exist.** A game that sets them by mistake gets mGBA's picture, without the renderer reading past VRAM. Pinned in Task 2 (`test_the_modes_that_do_not_exist_show_what_mgba_shows`).
2. **Scroll values past 511** (BG0HOFS 0xFFFF, BG0VOFS 0xFE01). Only the low 9 bits count, as on the GBA. Pinned in Task 3 (`scroll-past-511` in `test_text_backgrounds_look_like_mgba`).
3. **A colour changed between lines.** HBlank DMA writes palette entry 0 (the backdrop) line after line: the common gradient trick. Each line shows the colour written before it was drawn. Pinned in Task 3 (`hblank-dma-backdrop-colours` in `test_raster_effects_look_like_mgba`).
4. **Sprite matrices that make no sensible picture** (all zero, the largest values, 1/256). No crash, no read outside the sprite's tiles, and mGBA's picture. Pinned in Task 5 (`matrices-that-make-no-picture` in `test_sprites_look_like_mgba`).
5. **A busy picture**: four backgrounds, 128 rotating double-size sprites, both windows and the OBJ window, blending and mosaic. It looks like mGBA's, and the headless build draws 600 frames in less than the ten seconds the GBA takes to show them. Pinned in Task 8 (`tests/runtime/test_render_speed.py`).

## Known limitations (deliberate; later plans)

- **mGBA shortcuts the renderer does not copy.** The renderer follows GBATEK here, and the tests avoid these cases:
  - mGBA draws the sprites that make the OBJ window without mosaic.
  - mGBA restarts a 256-colour text background's horizontal mosaic where a window's span starts.
  - mGBA stops a rotating sprite's line at the first texel outside it, after an approximate clip at its left edge. The renderer tests every pixel of the box.
  - mGBA rounds the amount it darkens by up in some channels, so a partial darkening (BLDY 1-15) can be one step darker there. The renderer uses GBATEK's formula, rounded down; `test_partial_darkening_follows_gbatek` checks it against that formula instead of mGBA. (Added by the final review's fix pass: fades in games will differ from mGBA by one step per channel.)
- **Not modelled:**
  - The delay of a few lines before a background that is switched on mid-frame appears (mGBA models it).
  - Green swap (register 0x04000002).
  - Changes made in the middle of a line: each line is drawn from memory as it is when its HDraw ends, as in mGBA.
- **Whole-game timing.** On the user's game, frame 120 is the same as mGBA's. Later frames drift, because the recompiled code's cycle counts are estimates. Plan 7's lockstep harness measures that.
- **No upscaling filters**: the hosts scale the picture by whole steps, as in Plan 4c.

---

### Task 1: mGBA, built from source, as the renderer's reference

Every renderer test in this plan compares a picture with mGBA's. This task builds that reference: mGBA 0.10.5's GBA core (MPL-2.0), with 16-bit colour and no dependencies, linked into a small program, `mgbaref`. It runs a ROM for N frames and writes the picture as raw GBA colours. The bitmap modes already reach the screen (Plan 4c), so their pictures must match mGBA's from the start.

**Files:**
- Create: `tests/mgbaref/CMakeLists.txt`, `tests/mgbaref/mgbaref.c`
- Create: `tests/mgbaref.py`
- Create: `tests/rendertest.py`
- Test: `tests/runtime/test_render_reference.py`

**Interfaces:**
- Consumes:
  - `romtest`: `CACHE`, `TestRom`, `_digest`, `build_test_rom(name, data)`, `run_rom(rom, *, frames, args)`, `read_bmp(path)` (Plans 4a-4c).
  - `gbaport.native.build`: `_starts(program) -> bool` and `SALTED_REBUILDS` (Plan 4b), so a program Windows refuses is linked again with a salt.
  - `gbaport.native.sdl3.cache_folder()` and `gbaport.native.toolchain`'s `ToolchainError`, `find_clang`, `find_cmake`, `find_ninja`, `llvm_tool` (Plan 4c), to build mGBA the way SDL3 is built.
  - The headless program's `--screenshot PATH` (Plan 4c).
- **Produces:**
  - **`mgbaref.py`:**
    - `MGBA_VERSION = "0.10.5"`, `MGBA_URL`, `MGBA_SHA256`.
    - `mgbaref_program() -> Path` downloads the source tarball once, checks its SHA-256 and builds `mgbaref` in `cache_folder() / "mgbaref-0.10.5-<digest of tests/mgbaref>"`. It writes a `started` file once Windows lets the program start.
    - `mgba_picture(rom: bytes, frames: int) -> list[int]`: 38400 colours, `0BBBBBGGGGGRRRRR`, top row first.
  - **`rendertest.py`:**
    - `gba_colour(pixel: int) -> int`: a host pixel (0x00RRGGBB) back to a GBA colour.
    - `our_picture(rom: TestRom, frames: int) -> list[int]`: the native build's picture, as GBA colours.
    - `assert_same_picture(rom, frames=30)` raises `AssertionError("N pixels differ from mGBA's picture, the first at (x, y): 0x.... instead of 0x.... (see PATH)")`. PATH is a PNG in `CACHE / "pictures"` with mGBA's picture, ours and the differing pixels (red), side by side.
    - `assert_test_rom_matches(name, data="", frames=30)`: the same, for a test ROM from `tests/gbaroms`.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-05-renderer
```

- [ ] **Step 2: Write the failing test**

Create `tests/runtime/test_render_reference.py`:
```python
"""mGBA as the renderer's reference (tests/mgbaref.py, tests/rendertest.py).

The bitmap modes already reach the screen (Plan 4c), so their pictures match mGBA's from
the start; the other renderer tests compare their own test ROMs the same way.
"""

from pathlib import Path

import pytest
import rendertest
from romtest import build_test_rom


@pytest.mark.parametrize("dispcnt", [0x0403, 0x0404, 0x0414, 0x0415, 0x0483])
def test_the_bitmap_modes_match_mgba(dispcnt):
    rendertest.assert_test_rom_matches("bitmap", f"#define DISPCNT 0x{dispcnt:04x}\n", frames=10)


def test_a_different_picture_names_the_pixels_and_shows_them_side_by_side(monkeypatch):
    monkeypatch.setattr(rendertest, "our_picture", lambda rom, frames: [0] * 38400)
    monkeypatch.setattr(rendertest, "mgba_picture", lambda data, frames: [0] * 38399 + [0x7FFF])
    with pytest.raises(AssertionError) as failure:
        rendertest.assert_same_picture(build_test_rom("bitmap", "#define DISPCNT 0x0403\n"))
    message = str(failure.value)
    assert message.startswith("1 pixels differ from mGBA's picture, the first at (239, 159): "
                              "0x0000 instead of 0x7fff (see ")
    picture = message.split("(see ")[1].rstrip(")")
    assert Path(picture).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_render_reference.py`
Expected: FAIL — 1 error: `ModuleNotFoundError: No module named 'rendertest'`

- [ ] **Step 4: The reference program and the picture comparison**

Create `tests/mgbaref.py`:
```python
"""mGBA as the reference picture for the renderer tests.

mGBA's GBA core is the spec's development-time oracle (MPL-2.0; nothing ships it). The
pinned source release is downloaded once (its SHA-256 checked) and built with CMake, Ninja
and clang, together with ``mgbaref/mgbaref.c``, which runs a ROM for some frames and
writes its picture. Both live in gbaport's cache folder (``$GBAPORT_CACHE``, by default the
user's), next to SDL3; a change to ``mgbaref/`` builds it again. A harness Windows refuses
to start is linked again with a new ``salt.c``, like every program the tests build.
"""

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.sdl3 import cache_folder
from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

MGBA_VERSION = "0.10.5"
MGBA_URL = f"https://github.com/mgba-emu/mgba/archive/refs/tags/{MGBA_VERSION}.tar.gz"
MGBA_SHA256 = "91d6fbd32abcbdf030d58d3f562de25ebbc9d56040d513ff8e5c19bee9dacf14"
SOURCE = Path(__file__).parent / "mgbaref"


def _source_release() -> Path:
    """The source tarball, downloaded once (CMake's own download is far slower)."""
    tarball = cache_folder() / f"mgba-{MGBA_VERSION}.tar.gz"
    if not tarball.exists():
        with urllib.request.urlopen(MGBA_URL, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != MGBA_SHA256:
            raise ToolchainError(f"{MGBA_URL} is not the expected mGBA {MGBA_VERSION} source")
        tarball.parent.mkdir(parents=True, exist_ok=True)
        partial = tarball.with_suffix(".partial")
        partial.write_bytes(data)
        partial.replace(tarball)
    return tarball


def _run(command: list[str], what: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output = (result.stdout + result.stderr)[-4000:]
        raise ToolchainError(f"building mGBA's reference failed ({what}):\n{output}")


def mgbaref_program() -> Path:
    """The reference program, building it first if it is not there yet (again when its
    sources change)."""
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in sorted(SOURCE.iterdir()))).hexdigest()
    folder = cache_folder() / f"mgbaref-{MGBA_VERSION}-{digest[:8]}"
    program = folder / ("mgbaref.exe" if os.name == "nt" else "mgbaref")
    if (folder / "started").exists():  # written once Windows let it start
        return program
    tarball = _source_release()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    cmake = find_cmake()
    configure = [
        cmake, "-S", str(SOURCE), "-B", str(folder), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={Path(find_ninja()).as_posix()}",
        f"-DCMAKE_C_COMPILER={Path(find_clang()).as_posix()}", "-DCMAKE_BUILD_TYPE=Release",
        f"-DGBAPORT_MGBA_URL={tarball.as_posix()}", f"-DGBAPORT_MGBA_SHA256={MGBA_SHA256}",
    ]
    if os.name == "nt":  # clang's GNU-style driver needs LLVM's resource compiler
        configure.append(f"-DCMAKE_RC_COMPILER={Path(llvm_tool('llvm-rc')).as_posix()}")
    salt = folder / "salt.c"
    salt.write_text('const char mgbaref_salt[] = "";\n', encoding="utf-8")
    _run(configure, "configure")
    for _ in range(native.SALTED_REBUILDS + 1):
        salt.write_text(f'const char mgbaref_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _run([cmake, "--build", str(folder)], "build")
        if native._starts(program):
            (folder / "started").write_text("", encoding="utf-8")
            return program
    raise ToolchainError(f"Windows refused to start {program} after {native.SALTED_REBUILDS} rebuilds")


def mgba_picture(rom: bytes, frames: int) -> list[int]:
    """mGBA's picture after ``frames`` frames: 240x160 GBA colours (0BBBBBGGGGGRRRRR),
    top row first."""
    program = mgbaref_program()
    with tempfile.TemporaryDirectory() as scratch:
        rom_path, out = Path(scratch) / "game.gba", Path(scratch) / "picture.raw"
        rom_path.write_bytes(rom)
        result = subprocess.run([str(program), str(rom_path), str(frames), str(out)],
                                capture_output=True, text=True, timeout=120, check=False)
        assert result.returncode == 0, f"mgbaref: {result.stderr}"
        return list(struct.unpack("<38400H", out.read_bytes()))
```

Create `tests/mgbaref/CMakeLists.txt`:
```cmake
# Builds mGBA's GBA core and mgbaref.c, the renderer tests' reference (tests/mgbaref.py
# runs this). The source release is GBAPORT_MGBA_URL (mgbaref.py downloads it first) and
# must match GBAPORT_MGBA_SHA256; mgbaref.py writes salt.c into the build folder.
cmake_minimum_required(VERSION 3.28)
project(gbaport_mgbaref LANGUAGES C)

include(FetchContent)
string(APPEND CMAKE_C_FLAGS " -Wno-incompatible-pointer-types -Wno-int-conversion")  # clang 23
# GBA colours throughout, blended in 5 bits per channel like the GBA: mGBA's sources take
# the definition, its generated flags.h the variable.
add_compile_definitions(COLOR_16_BIT)
set(COLOR_16_BIT ON CACHE BOOL "" FORCE)
foreach(option LIBMGBA_ONLY DISABLE_DEPS BUILD_STATIC)
    set(${option} ON CACHE BOOL "" FORCE)
endforeach()
foreach(option BUILD_SHARED M_CORE_GB USE_DEBUGGERS USE_GDB_STUB ENABLE_SCRIPTING BUILD_LTO)
    set(${option} OFF CACHE BOOL "" FORCE)
endforeach()
FetchContent_Declare(mgba URL "${GBAPORT_MGBA_URL}" URL_HASH "SHA256=${GBAPORT_MGBA_SHA256}")
FetchContent_MakeAvailable(mgba)
if(WIN32)  # mGBA links the maths library "m"; on Windows the C runtime has those functions
    add_library(m INTERFACE)
endif()

add_executable(mgbaref mgbaref.c "${CMAKE_BINARY_DIR}/salt.c")
target_include_directories(mgbaref PRIVATE "${mgba_SOURCE_DIR}/include" "${mgba_BINARY_DIR}/include")
target_compile_definitions(mgbaref PRIVATE BUILD_STATIC M_CORE_GBA)
target_link_libraries(mgbaref PRIVATE mgba)
```

Create `tests/mgbaref/mgbaref.c`:
```c
/* mgbaref.c - run a ROM in mGBA and write its picture: the renderer tests' reference.
 *
 *     mgbaref ROM FRAMES OUT
 *
 * Runs FRAMES frames from power-on (mGBA's own BIOS replacement, no BIOS file) and writes
 * the last picture to OUT as 240x160 little-endian 16-bit GBA colours (0BBBBBGGGGGRRRRR),
 * the form the runtime's tests compare in. mGBA is built with 16-bit colour, so it works
 * in GBA colours throughout, blending in 5 bits per channel like the GBA. mGBA's own
 * messages are dropped. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/gba/core.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
#error "mgbaref needs mGBA built with 16-bit BGR555 colour (CMakeLists.txt sets COLOR_16_BIT)"
#endif

static void quiet(struct mLogger *logger, int category, enum mLogLevel level, const char *format,
                  va_list args)
{
    (void)logger, (void)category, (void)level, (void)format, (void)args;
}

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s ROM FRAMES OUT\n", argv[0]);
        return 2;
    }
    static struct mLogger logger = {quiet, NULL};
    mLogSetDefaultLogger(&logger);
    struct mCore *core = GBACoreCreate();
    if (!core || !core->init(core)) {
        fprintf(stderr, "error: cannot start mGBA's core\n");
        return 3;
    }
    mCoreInitConfig(core, NULL);
    unsigned width, height;
    core->desiredVideoDimensions(core, &width, &height);
    color_t *pixels = calloc((size_t)width * height, sizeof *pixels);
    core->setVideoBuffer(core, pixels, width);
    if (!mCoreLoadFile(core, argv[1])) {
        fprintf(stderr, "error: mGBA cannot load %s\n", argv[1]);
        return 2;
    }
    core->reset(core);
    long frames = strtol(argv[2], NULL, 10);
    for (long i = 0; i < frames; i++)
        core->runFrame(core);
    FILE *out = fopen(argv[3], "wb");
    if (!out) {
        fprintf(stderr, "error: cannot write %s\n", argv[3]);
        return 3;
    }
    for (unsigned i = 0; i < width * height; i++) {
        fputc(pixels[i] & 0xFF, out);
        fputc((pixels[i] >> 8) & 0x7F, out);
    }
    fclose(out);
    core->deinit(core);
    return 0;
}
```

Create `tests/rendertest.py`:
```python
"""Renderer tests: a test ROM's picture, recompiled and run natively, against mGBA's.

Pictures are compared as GBA colours (15-bit), so the two ways of widening them to 24 bits
do not matter. When they differ, a PNG with mGBA's picture, ours and the differences (in
red) side by side is written to the test-ROM cache, and the message names it.
"""

import struct
import tempfile
import zlib
from pathlib import Path

from mgbaref import mgba_picture
from romtest import CACHE, TestRom, _digest, build_test_rom, read_bmp, run_rom


def gba_colour(pixel: int) -> int:
    """0x00RRGGBB, as the hosts widen a GBA colour, back to 0BBBBBGGGGGRRRRR."""
    return (pixel >> 19 & 31) | (pixel >> 11 & 31) << 5 | (pixel >> 3 & 31) << 10


def our_picture(rom: TestRom, frames: int) -> list[int]:
    with tempfile.TemporaryDirectory() as scratch:
        shot = Path(scratch) / "screen.bmp"
        run = run_rom(rom, frames=frames, args=("--screenshot", str(shot)))
        assert run.status in (0, 4), f"exit status {run.status}: {run.stderr}"
        return [gba_colour(p) for p in read_bmp(shot)]


def _png(path: Path, pictures: list[list[int]]) -> None:
    def rgb(c: int) -> bytes:
        return bytes([(c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3])

    rows = []
    for y in range(160):
        row = bytearray([0])
        for i, picture in enumerate(pictures):
            if i:
                row += b"\x80\x80\x80" * 4  # a grey gap between them
            for x in range(240):
                row += rgb(picture[y * 240 + x])
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    width = 240 * len(pictures) + 4 * (len(pictures) - 1)
    header = struct.pack(">IIBBBBB", width, 160, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def assert_same_picture(rom: TestRom, frames: int = 30) -> None:
    """The native build of ``rom`` shows what mGBA shows after ``frames`` frames."""
    ours, reference = our_picture(rom, frames), mgba_picture(rom.data, frames)
    if ours == reference:
        return
    wrong = [i for i in range(len(ours)) if ours[i] != reference[i]]
    differences = [0x001F if i in set(wrong) else 0 for i in range(len(ours))]
    picture = CACHE / "pictures" / f"{_digest(rom.data)}.png"
    _png(picture, [reference, ours, differences])
    x, y = wrong[0] % 240, wrong[0] // 240
    raise AssertionError(
        f"{len(wrong)} pixels differ from mGBA's picture, the first at ({x}, {y}): "
        f"{ours[wrong[0]]:#06x} instead of {reference[wrong[0]]:#06x} (see {picture})"
    )


def assert_test_rom_matches(name: str, data: str = "", frames: int = 30) -> None:
    assert_same_picture(build_test_rom(name, data), frames)
```

- [ ] **Step 5: Run the whole suite**

The first run downloads mGBA's source and builds it, which takes a few minutes.

Run: `uv run pytest`
Expected: 627 passed (621 + 6).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 6: Commit**

```bash
git add tests/mgbaref tests/mgbaref.py tests/rendertest.py tests/runtime/test_render_reference.py
git commit -m "test: mGBA 0.10.5, built from source, as the renderer's reference"
```

---

### Task 2: A line at a time, and the reference points

The renderer starts here. `gba_render_line` draws each line into `rt->screen` when its HDraw ends, before the HBlank interrupt and HBlank DMA. This task draws the bitmap modes 3, 4 and 5 through BG2's rotation/scaling: the reference points restart every frame, step after every line and follow the game's writes. `screen.c` keeps only the widening to 0x00RRGGBB.

**Files:**
- Create: `src/gbaport/runtime/render.c`
- Modify: `src/gbaport/runtime/gba_runtime.h` (`screen`, `affine_x`, `affine_y`; the three functions)
- Modify: `src/gbaport/runtime/scheduler.c` (draw at HBlank start; restart the reference points at line 160)
- Modify: `src/gbaport/runtime/io.c` (writes to BG2X/BG2Y/BG3X/BG3Y; reset)
- Modify: `src/gbaport/runtime/screen.c`
- Modify: `src/gbaport/native/build.py` (`RUNTIME_SOURCES` gains `render.c`)
- Create: `tests/gbaroms/affine_bitmap.c`
- Test: `tests/runtime/test_render_core.py`

**Interfaces:**
- Consumes: `rendertest.assert_test_rom_matches` (Task 1); `GbaRuntime.io`, `vram`, `palette`, `oam` (Plan 4a).
- **Produces, in `gba_runtime.h`:**
  - `uint16_t screen[GBA_SCREEN_HEIGHT][GBA_SCREEN_WIDTH]` in `GbaRuntime`: the picture, GBA colours.
  - `int32_t affine_x[2], affine_y[2]` in `GbaRuntime`: BG2's and BG3's internal reference points (20.8 fixed point).
  - `void gba_render_line(GbaRuntime *rt, int y)`: called by the scheduler when line y's HDraw ends (y < 160).
  - `void gba_render_frame_start(GbaRuntime *rt)`: reloads the reference points from BGxX/BGxY (at line 160, and on reset).
  - `void gba_render_reference_write(GbaRuntime *rt, uint32_t offset)`: reloads the point whose register (offset 0x28-0x2E or 0x38-0x3E) was written.
- **Inside `render.c`**, used by later tasks:
  - `IO(rt, offset)` and `CLEAR` (0x8000: no colour, what is below shows through).
  - `color_at(memory, offset)`: a palette or bitmap colour, 15 bits.
  - `reference(rt, offset)`: BGxX or BGxY as a signed 28-bit value.
  - `bitmap_line(rt, out, mode)`: BG2's line in modes 3-5, walked from its reference point.
  - `Layers` (`bg[4][240]`, one row per background) and `compose(rt, layers, enabled, row)`: per pixel, the topmost background with a colour (the lower priority number on top, BG0 before BG3 at equal priority), or the backdrop.
- **`affine_bitmap.c`** takes `DISPCNT`, `PA`-`PD`, `X`, `Y`, `WAVE` (HBlank DMA moves BG2X every line) and `RESTART` (a VCOUNT interrupt writes BG2Y at line 80) from `testdata.h`.

- [ ] **Step 1: Write the failing test and its test ROM**

Create `tests/gbaroms/affine_bitmap.c`:
```c
/* A bitmap mode picture through BG2's rotation/scaling: testdata.h sets DISPCNT, the
 * matrix (PA, PB, PC, PD) and the reference point (X, Y). With WAVE set, an HBlank
 * interrupt moves the reference point's X on every line, a raster effect; with RESTART
 * set, it writes BG2Y halfway down the screen, which restarts the walk from there. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BG2PA REG16(0x04000020)
#define REG_BG2PB REG16(0x04000022)
#define REG_BG2PC REG16(0x04000024)
#define REG_BG2PD REG16(0x04000026)
#define REG_BG2X REG32(0x04000028)
#define REG_BG2Y REG32(0x0400002C)

__attribute__((target("arm"))) static void on_hblank(void)
{
    uint32_t next = REG_VCOUNT + 1;
    if (next == 228)
        next = 0;
    if (WAVE && next < 160)
        REG_BG2X = (uint32_t)(X + (int32_t)((next * 37) & 63) * 64 - 32 * 64);
    if (RESTART && next == 80)
        REG_BG2Y = (uint32_t)Y;
    REG_IF = IRQ_HBLANK;
}

int main(void)
{
    PALETTE[0] = 0x7C00;  /* the backdrop: blue */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(i * 0x0421 & 0x7FFF);
    for (uint32_t y = 0; y < 160; y++) {
        for (uint32_t x = 0; x < 240; x += 2) {
            if ((DISPCNT & 7) == 3) {
                VRAM[y * 240 + x] = (uint16_t)((x & 31) | (y & 31) << 5 | ((x ^ y) & 16) << 6);
                VRAM[y * 240 + x + 1] = (uint16_t)(((x + 1) & 31) | (y & 31) << 5);
            } else if ((DISPCNT & 7) == 4) {
                VRAM[(y * 240 + x) / 2] = (uint16_t)(((x + y) & 255) | ((x * y + 1) & 255) << 8);
            } else if (x < 160 && y < 128) {
                VRAM[y * 160 + x] = (uint16_t)((x ^ y) & 0x7FFF);
                VRAM[y * 160 + x + 1] = (uint16_t)(((x + 1) * 3 ^ y) & 0x7FFF);
            }
        }
    }
    REG_BG2PA = (uint16_t)PA;
    REG_BG2PB = (uint16_t)PB;
    REG_BG2PC = (uint16_t)PC;
    REG_BG2PD = (uint16_t)PD;
    REG_BG2X = (uint32_t)X;
    REG_BG2Y = (uint32_t)Y;
    IRQ_VECTOR = (uint32_t)on_hblank;
    REG_DISPSTAT = WAVE || RESTART ? 0x10 : 0;  /* HBlank interrupt */
    REG_IE = IRQ_HBLANK;
    REG_IME = 1;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_halt();
}
```

Create `tests/runtime/test_render_core.py`:
```python
"""The renderer's core: a line at a time, the bitmap modes through BG2's rotation/scaling,
and reference points that restart every frame and follow writes (compared with mGBA)."""

import pytest
from rendertest import assert_test_rom_matches


def scene(dispcnt: int, pa=0x100, pb=0, pc=0, pd=0x100, x=0, y=0, wave=0, restart=0) -> str:
    return (
        f"#define DISPCNT 0x{dispcnt:04x}\n#define PA {pa}\n#define PB {pb}\n#define PC {pc}\n"
        f"#define PD {pd}\n#define X {x}\n#define Y {y}\n#define WAVE {wave}\n"
        f"#define RESTART {restart}\n"
    )


@pytest.mark.parametrize("data", [
    scene(0x0403, pa=0x80, pd=0x80),                                   # mode 3, twice the size
    scene(0x0403, pa=0xB5, pb=-0xB5, pc=0xB5, pd=0xB5, x=60 << 8),    # 45 degrees
    scene(0x0404, pa=0x200, pb=0x40, pc=-0x40, pd=0x180, x=-20 << 8, y=30 << 8),
    scene(0x0405, pa=-0x100, pd=-0x100, x=159 << 8, y=127 << 8),        # mode 5, turned round
    scene(0x0083),                                                      # forced blank
], ids=["scaled", "rotated", "sheared", "mode5-flipped", "forced-blank"])
def test_the_bitmap_modes_rotate_and_scale_like_mgba(data):
    assert_test_rom_matches("affine_bitmap", data)


@pytest.mark.parametrize("mode", [6, 7])
def test_the_modes_that_do_not_exist_show_what_mgba_shows(mode):
    assert_test_rom_matches("affine_bitmap", scene(0x0400 | mode))


def test_a_reference_point_written_between_lines_moves_the_lines_below():
    assert_test_rom_matches("affine_bitmap", scene(0x0403, pd=0x100, x=8 << 8, wave=1))


def test_writing_bg2y_mid_frame_restarts_the_walk_there():
    assert_test_rom_matches("affine_bitmap", scene(0x0403, pa=0x100, pd=0x80, y=10 << 8, restart=1))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_render_core.py`
Expected: FAIL — 6 failed, 3 passed.
- The six rotated, scaled, flipped and written-between-lines pictures fail with `AssertionError: N pixels differ from mGBA's picture, the first at (x, y): ...`. Plan 4c's screen copies modes 3-5 pixel for pixel, without BG2's matrix or reference point.
- Forced blank and modes 6 and 7 pass already: Plan 4c's screen draws them as mGBA does (white; the backdrop). Their tests keep it that way.

- [ ] **Step 3: Draw a line at a time**

In `src/gbaport/native/build.py`, replace:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c", "save.c", "screen.c",
)
```
with:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c", "save.c", "render.c",
    "screen.c",
)
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    uint16_t keys_last;                  /* at the last keypad check; 0x400: no match */
    GbaSave save;
```
with:
```c
    uint16_t keys_last;                  /* at the last keypad check; 0x400: no match */
    uint16_t screen[GBA_SCREEN_HEIGHT][GBA_SCREEN_WIDTH];  /* the picture, GBA colours */
    int32_t affine_x[2], affine_y[2];    /* BG2's and BG3's internal reference points */
    GbaSave save;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```
with:
```c

void gba_render_line(GbaRuntime *rt, int y);            /* when line y's HDraw ends */
void gba_render_frame_start(GbaRuntime *rt);            /* reference points start again */
void gba_render_reference_write(GbaRuntime *rt, uint32_t offset);  /* BGxX/BGxY written */

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```

In `src/gbaport/runtime/io.c`, replace:
```c
 * - Writing HALTCNT halts or stops the CPU.
 * - Timer counters are worked out from the cycle count; writes set the reload value.
```
with:
```c
 * - Writing HALTCNT halts or stops the CPU.
 * - Writing BG2X/BG2Y/BG3X/BG3Y moves the renderer's reference points there.
 * - Timer counters are worked out from the cycle count; writes set the reload value.
```

In `src/gbaport/runtime/io.c`, replace:
```c
    rt->keys_last = 0x400;
}
```
with:
```c
    rt->keys_last = 0x400;
    gba_render_frame_start(rt);
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
        IO(rt, offset) = merged;
        return;
```
with:
```c
        IO(rt, offset) = merged;
        if ((offset >= 0x28 && offset <= 0x2E) || (offset >= 0x38 && offset <= 0x3E))
            gba_render_reference_write(rt, offset);
        return;
```

Create `src/gbaport/runtime/render.c`:
```c
/* render.c - the GBA's picture, drawn one scanline at a time.
 *
 * gba_render_line(rt, y) draws line y into rt->screen when the line's HDraw ends, before
 * the HBlank interrupt and HBlank DMA (as mGBA does), from the registers, VRAM and palette
 * as they are then: a game that changes them between lines gets its raster effects. Each
 * enabled background is drawn into a line of its own; then every pixel takes the colour
 * of the topmost background there (the lower priority number; between equals, the lower
 * background number), or the backdrop, palette entry 0. Forced blank draws white.
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
 * an internal reference point: BGxX/BGxY at the start of every frame and whenever the game
 * writes them, moved by (PB, PD) after every line drawn while the background is on. Along
 * a line, each pixel moves it by (PA, PC). */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define CLEAR 0x8000u  /* no colour here: what is below shows through */

enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT };

typedef struct {
    uint16_t bg[4][W];  /* each background's colours on this line, or CLEAR */
} Layers;

static uint16_t color_at(const uint8_t *memory, uint32_t offset)
{
    return (uint16_t)((memory[offset] | memory[offset + 1] << 8) & 0x7FFF);
}

/* BGxX or BGxY (offset of its low half): a signed 28-bit 20.8 fixed-point value. */
static int32_t reference(const GbaRuntime *rt, uint32_t offset)
{
    uint32_t value = IO(rt, offset) | (uint32_t)IO(rt, offset + 2) << 16;
    return (int32_t)(value << 4) >> 4;
}

void gba_render_frame_start(GbaRuntime *rt)
{
    for (int n = 0; n < 2; n++) {
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
    }
}

void gba_render_reference_write(GbaRuntime *rt, uint32_t offset)
{
    int n = offset >= 0x38;  /* BG3 */
    if ((offset & 0xF) < 0xC)
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
    else
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
}

/* Modes 3-5: BG2 is a bitmap, walked like the rotation/scaling backgrounds. */
static void bitmap_line(const GbaRuntime *rt, uint16_t *out, uint32_t mode)
{
    int32_t x = rt->affine_x[0], y = rt->affine_y[0];
    int32_t dx = (int16_t)IO(rt, 0x20), dy = (int16_t)IO(rt, 0x24);  /* PA, PC */
    uint32_t page = IO(rt, GBA_REG_DISPCNT) & 0x10 ? 0xA000 : 0;
    int width = mode == 5 ? 160 : 240, height = mode == 5 ? 128 : 160;
    for (int i = 0; i < W; i++, x += dx, y += dy) {
        int tx = x >> 8, ty = y >> 8;
        out[i] = CLEAR;
        if (x < 0 || y < 0 || tx >= width || ty >= height)
            continue;
        if (mode == 3) {
            out[i] = color_at(rt->vram, (uint32_t)(ty * 240 + tx) * 2);
        } else if (mode == 4) {
            uint8_t index = rt->vram[page + (uint32_t)(ty * 240 + tx)];
            if (index)
                out[i] = color_at(rt->palette, index * 2u);
        } else {
            out[i] = color_at(rt->vram, page + (uint32_t)(ty * 160 + tx) * 2);
        }
    }
}

/* Every pixel: the topmost background with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned enabled, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    for (int x = 0; x < W; x++) {
        row[x] = backdrop;
        int found = 0;
        for (unsigned priority = 0; priority < 4 && !found; priority++) {
            for (int n = 0; n < 4 && !found; n++) {
                if ((enabled & (1u << n)) && (IO(rt, 0x08 + 2 * n) & 3) == priority &&
                    layers->bg[n][x] != CLEAR) {
                    row[x] = layers->bg[n][x];
                    found = 1;
                }
            }
        }
    }
}

void gba_render_line(GbaRuntime *rt, int y)
{
    uint16_t *row = rt->screen[y];
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    uint32_t mode = control & 7;
    if (control & 0x80) {  /* forced blank */
        for (int x = 0; x < W; x++)
            row[x] = 0x7FFF;
        return;
    }
    static Layers layers;
    unsigned enabled = 0;
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
        bitmap_line(rt, layers.bg[2], mode);
        enabled |= 1u << 2;
    }
    compose(rt, &layers, enabled, row);
    for (int n = 0; n < 2; n++) {
        if (mode != 0 && (control & (0x400u << n))) {
            rt->affine_x[n] += (int16_t)IO(rt, 0x22 + 0x10 * n);  /* PB */
            rt->affine_y[n] += (int16_t)IO(rt, 0x26 + 0x10 * n);  /* PD */
        }
    }
}
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    IO(rt, GBA_REG_DISPSTAT) |= 2;
```
with:
```c
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    if (IO(rt, GBA_REG_VCOUNT) < GBA_VISIBLE_LINES)  /* before HBlank DMA and interrupts */
        gba_render_line(rt, IO(rt, GBA_REG_VCOUNT));
    IO(rt, GBA_REG_DISPSTAT) |= 2;
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
    if (line == GBA_VISIBLE_LINES) {
        if (stat & 0x08)
```
with:
```c
    if (line == GBA_VISIBLE_LINES) {
        gba_render_frame_start(rt);
        if (stat & 0x08)
```

Create `src/gbaport/runtime/screen.c` (replacing the current version):
```c
/* screen.c - the picture for the host: the renderer's GBA colours as 0x00RRGGBB. */
#include "gba_runtime.h"

void gba_screen(const GbaRuntime *rt, uint32_t *pixels)
{
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++) {
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint32_t color = rt->screen[y][x];
            uint32_t r = color & 31, g = (color >> 5) & 31, b = (color >> 10) & 31;
            r = (r << 3) | (r >> 2);  /* five bits widened to eight */
            g = (g << 3) | (g >> 2);
            b = (b << 3) | (b >> 2);
            pixels[y * GBA_SCREEN_WIDTH + x] = r << 16 | g << 8 | b;
        }
    }
}
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 636 passed (627 + 9).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms/affine_bitmap.c tests/runtime/test_render_core.py
git commit -m "feat: the renderer draws a line at a time, the bitmap modes through BG2's reference points"
```

---

### Task 3: Text backgrounds, jsmolka's PPU test ROMs and raster effects

Text backgrounds are what most games draw with. This task draws them in modes 0 and 1:
- 4 and 8 bits per pixel, the four map sizes, scrolling with wrap-around, flips and palette banks;
- stacking by priority;
- tile data past background VRAM, which is transparent.

Two more kinds of test come with it:
- **jsmolka's three PPU test ROMs.** The jsmolka download moves from `test_public_roms.py` into a shared `tests/jsmolka.py`.
- **A raster test ROM.** It changes a register or a colour line after line with HBlank DMA.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Create: `tests/gbaroms/text_bg.c`, `tests/gbaroms/raster.c`
- Create: `tests/jsmolka.py` (moved out of `tests/runtime/test_public_roms.py`, with the PPU ROMs added)
- Modify: `tests/runtime/test_public_roms.py`
- Create: `tests/publicroms/jsmolka/hello.toml`, `shades.toml`, `stripes.toml`
- Modify: `tests/publicroms/jsmolka/README.md`
- Modify: `tests/runtime/test_screen.py` (mode 0 is no longer just the backdrop)
- Test: `tests/runtime/test_render_text.py`, `tests/runtime/test_render_public.py`, `tests/runtime/test_render_raster.py`

**Interfaces:**
- Consumes: `IO`, `CLEAR`, `color_at`, `Layers` and `compose` (Task 2); `romtest.TestRom` and `CACHE`.
- **Produces:**
  - **In `render.c`:**
    - `halfword(memory, offset)`.
    - `text_line(rt, n, y, out)` draws text background n's line y into `out` (240 colours or `CLEAR`).
    - `gba_render_line` draws the text backgrounds: BG0-BG3 in mode 0, BG0 and BG1 in mode 1.
  - **`jsmolka.py`:** `jsmolka_rom(name) -> romtest.TestRom`, `ROMS` (name: path in jsmolka's repository and SHA-1), `CONFIGS`, `COMMIT`, `SOURCE`. The ROMs are cached in `CACHE / "jsmolka"`.
  - **`raster.c`** takes `DISPCNT`, `SPLIT` and `TARGET` (the register HBlank DMA writes: BG0HOFS, or palette entry 0) from `testdata.h`.
  - **`test_public_roms.py`** keeps `REGISTERS = {"thumb": 7}`, the register holding a ROM's result when it is not r12.

- [ ] **Step 1: Write the failing tests, the test ROMs and the jsmolka kit**

Create `tests/gbaroms/raster.c`:
```c
/* Raster effects: a picture that changes between lines. Like scene.c, VRAM holds varied
 * tiles and maps; BG0 and BG2 show them. HBlank DMA copies a table of values into TARGET
 * line after line (BG0HOFS: a wave; palette entry 0, the backdrop: stripes of colour),
 * restarted by the VBlank interrupt; with SPLIT set, a
 * VCOUNT interrupt at line 80 switches DISPCNT from mode 0 to mode 1, so BG2 turns from a
 * text background into a rotation/scaling one halfway down. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static uint16_t wave[160];

static void restart_dma(void)
{
    REG_DMA_CNT_H(0) = 0;
    REG_DMA_SAD(0) = (uint32_t)&wave[1];  /* line 0 shows the value set at VBlank */
    REG_DMA_DAD(0) = TARGET;
    REG_DMA_CNT(0) = 1 | (0x8000u | 0x2000u | 0x0200u | 0x0040u) << 16;  /* on, HBlank, repeat, fixed */
}

__attribute__((target("arm"))) static void on_interrupt(void)
{
    uint16_t flags = REG_IF;
    if (flags & IRQ_VBLANK) {
        REG16(TARGET) = wave[0];
        restart_dma();
        REG_DISPCNT = DISPCNT;
    }
    if (flags & IRQ_VCOUNT)
        REG_DISPCNT = (uint16_t)((DISPCNT & ~7) | 1);
    REG_IF = flags;
}

int main(void)
{
    for (uint32_t i = 0; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i + 11) & 0x7FFF);
    for (uint32_t i = 0; i < 0x8000; i++) {
        uint32_t bits = mix(i + 1);
        if (i >= 0x4000)
            bits &= 0xFC7F;  /* map entries: tiles below 128 */
        else if ((i & 0xF) < 4)
            bits &= 0x0F0F;
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t y = 0; y < 160; y++)
        wave[y] = (uint16_t)((y * 7) & 31);
    REG16(0x04000008) = 0x1000 | 1;  /* BG0: screen block 16, priority 1 */
    REG16(0x0400000C) = 0x1404;      /* BG2: char block 1, screen block 20 */
    REG16(0x04000020) = 0xC0;        /* BG2's matrix, used in mode 1 */
    REG16(0x04000026) = 0xC0;
    IRQ_VECTOR = (uint32_t)on_interrupt;
    REG_DISPSTAT = (uint16_t)(0x08 | (SPLIT ? 0x20 | 80 << 8 : 0));
    REG_IE = (uint16_t)(IRQ_VBLANK | (SPLIT ? IRQ_VCOUNT : 0));
    REG_IME = 1;
    restart_dma();
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_halt();
}
```

Create `tests/gbaroms/text_bg.c`:
```c
/* Text backgrounds: VRAM's first 32 KiB holds varied tiles (with gaps that let layers
 * below show through) and the second 32 KiB varied map entries (tiles, flips, palette
 * banks). testdata.h sets DISPCNT and, for each background, BGnCNT, HOFSn and VOFSn, so a
 * scene picks sizes, colour depths, bases, scrolling and priorities. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BGCNT(n) REG16(0x04000008 + 2 * (n))
#define REG_BGHOFS(n) REG16(0x04000010 + 4 * (n))
#define REG_BGVOFS(n) REG16(0x04000012 + 4 * (n))

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

int main(void)
{
    PALETTE[0] = 0x5294;  /* the backdrop: grey */
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x4000; i++) {  /* tiles: 0x0000-0x7FFF */
        uint32_t bits = mix(i + 1);
        if ((i & 0xF) < 3)  /* the first rows of every tile are partly clear */
            bits &= 0x0F0F;
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t i = 0; i < 0x4000; i++)  /* maps: 0x8000-0xFFFF */
        VRAM[0x4000 + i] = (uint16_t)(mix(i * 7 + 3) & 0xFFFF);
    static const uint16_t control[4] = {BGCNT0, BGCNT1, BGCNT2, BGCNT3};
    static const uint16_t hofs[4] = {HOFS0, HOFS1, HOFS2, HOFS3};
    static const uint16_t vofs[4] = {VOFS0, VOFS1, VOFS2, VOFS3};
    for (int n = 0; n < 4; n++) {
        REG_BGCNT(n) = control[n];
        REG_BGHOFS(n) = hofs[n];
        REG_BGVOFS(n) = vofs[n];
    }
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
```

Create `tests/jsmolka.py`:
```python
"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md) for the tests.

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository.
"""

import hashlib
import urllib.request
from pathlib import Path

import romtest

CONFIGS = Path(__file__).parent / "publicroms" / "jsmolka"
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
    "hello": ("ppu/hello.gba", "813b7910a32be21a7baa08b1afcb7eaaf58a8b58"),
    "shades": ("ppu/shades.gba", "f4f81d3439c79362f416ccc1e94bac47429015f4"),
    "stripes": ("ppu/stripes.gba", "2c4682c47e19ffa7894399fb84e03b083261e7e7"),
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
```

In `tests/publicroms/jsmolka/README.md`, replace:
```markdown
Test ROMs from <https://github.com/jsmolka/gba-tests> (MIT licence), commit
`a7113b67e63f83a9b321696ddd7042ccfad6c881`. `tests/runtime/test_public_roms.py` downloads
them from that commit the first time, checks their SHA-1 and caches them with the other
test ROMs: like every `.gba` file, they are not in the repository. Each ROM runs its tests,
shows "All tests passed" or "Failed test N" in mode 4 and then idles; a register (r12, r7
```
with:
```markdown
Test ROMs from <https://github.com/jsmolka/gba-tests> (MIT licence), commit
`a7113b67e63f83a9b321696ddd7042ccfad6c881`. `tests/jsmolka.py` downloads them from that
commit the first time, checks their SHA-1 and caches them with the other test ROMs: like
every `.gba` file, they are not in the repository. Each CPU ROM runs its tests,
shows "All tests passed" or "Failed test N" in mode 4 and then idles; a register (r12, r7
```

In `tests/publicroms/jsmolka/README.md`, replace:
```markdown
| `bios.gba` | What reads of the BIOS area return, before and after a SWI and an interrupt |
| `sram.gba`, `flash64.gba`, `flash128.gba`, `none.gba` | The save chips, and a cartridge without one |

Each ROM's `.toml` is its `game.toml`: the ROM's SHA-1, the code addresses discovery
```
with:
```markdown
| `bios.gba` | What reads of the BIOS area return, before and after a SWI and an interrupt |
| `sram.gba`, `flash64.gba`, `flash128.gba`, `none.gba` | The save chips, and a cartridge without one |
| `ppu/hello.gba`, `ppu/shades.gba`, `ppu/stripes.gba` | Pictures (text in a tiled background, shades of a palette, stripes), which `tests/runtime/test_render_public.py` compares with mGBA's |

Each ROM's `.toml` is its `game.toml`: the ROM's SHA-1, the code addresses discovery
```

In `tests/publicroms/jsmolka/README.md`, replace:
```markdown

Not used: `ppu/` (the renderer comes in Plan 5); `nes.gba`, which copies its code to
VRAM and rewrites instructions there while they run, which a static recompiler cannot
```
with:
```markdown

Not used: `nes.gba`, which copies its code to
VRAM and rewrites instructions there while they run, which a static recompiler cannot
```

Create `tests/publicroms/jsmolka/hello.toml`:
```toml
# jsmolka/gba-tests ppu/hello.gba (see README.md)
[rom]
sha1 = "813b7910a32be21a7baa08b1afcb7eaaf58a8b58"
```

Create `tests/publicroms/jsmolka/shades.toml`:
```toml
# jsmolka/gba-tests ppu/shades.gba (see README.md)
[rom]
sha1 = "f4f81d3439c79362f416ccc1e94bac47429015f4"
```

Create `tests/publicroms/jsmolka/stripes.toml`:
```toml
# jsmolka/gba-tests ppu/stripes.gba (see README.md)
[rom]
sha1 = "2c4682c47e19ffa7894399fb84e03b083261e7e7"
```

In `tests/runtime/test_public_roms.py`, replace:
```python

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository. Each ROM runs its tests, shows the result and then idles. When the run reaches
its frame limit, a register (r12, r7 in thumb.gba) holds the number of the first test that
```
with:
```python

They come from tests/jsmolka.py. Each ROM runs its tests, shows the result and then idles. When the run reaches
its frame limit, a register (r12, r7 in thumb.gba) holds the number of the first test that
```

In `tests/runtime/test_public_roms.py`, replace:
```python

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
ROMS = {  # name: (path in jsmolka's repository, SHA-1, the register with the result)
    "arm": ("arm/arm.gba", "753d7f40f50735bf13faab215cf9268f76cf9065", 12),
    "thumb": ("thumb/thumb.gba", "bdcf58182e9a99b388acba5fbca87ac31e8f58eb", 7),
    "memory": ("memory/memory.gba", "5f989b9a4017f16a431f76fd78a95e9799aa8fca", 12),
    "bios": ("bios/bios.gba", "a65b88f609aa3488add7fe331792f1e3ba3372b2", 12),
    "sram": ("save/sram.gba", "4fc95dc85cb68fdbc04c6689c9d62329582a1856", 12),
    "flash64": ("save/flash64.gba", "354fe3dba476b54b869cb44aeb6968fdd72dabd3", 12),
    "flash128": ("save/flash128.gba", "9396b0525ae548e524d50cd6c48ea3e15b092504", 12),
    "none": ("save/none.gba", "6ea4c58075159aa51c1feecd04f17efe3050b70a", 12),
}
ALL_PASSED = "ae000eb0c97cf8ac296246c6d9eee1d1d2e1d428"  # SHA-1 of that picture's screenshot


def jsmolka_rom(name: str) -> romtest.TestRom:
    path, sha1, _ = ROMS[name]
    cached = romtest.CACHE / "jsmolka" / f"{name}.gba"
    if not cached.exists():
        with urllib.request.urlopen(SOURCE + path, timeout=60) as response:
            data = response.read()
        assert hashlib.sha1(data).hexdigest() == sha1, f"{SOURCE}{path} is not the expected file"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    config = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    return romtest.TestRom(cached.read_bytes(), config)


@pytest.mark.parametrize(
```
with:
```python

import hashlib
import re

import pytest
import romtest
from jsmolka import jsmolka_rom

from gbaport.analysis.config import ConfigError

REGISTERS = {"thumb": 7}  # the register with the result: r12, except in thumb.gba
ALL_PASSED = "ae000eb0c97cf8ac296246c6d9eee1d1d2e1d428"  # SHA-1 of that picture's screenshot


@pytest.mark.parametrize(
```

In `tests/runtime/test_public_roms.py`, replace:
```python
    assert run.status == 4, run.stderr
    register = ROMS[name][2]
    failed = int(re.search(rf" r{register}=([0-9a-f]{{8}})", run.stderr).group(1), 16)
```
with:
```python
    assert run.status == 4, run.stderr
    register = REGISTERS.get(name, 12)
    failed = int(re.search(rf" r{register}=([0-9a-f]{{8}})", run.stderr).group(1), 16)
```

Create `tests/runtime/test_render_public.py`:
```python
"""jsmolka's PPU test ROMs (tests/jsmolka.py), recompiled: their pictures match mGBA's."""

import pytest
from jsmolka import jsmolka_rom
from rendertest import assert_same_picture


@pytest.mark.parametrize("name", ["hello", "shades", "stripes"])
def test_jsmolka_ppu_rom_looks_like_mgba(name):
    assert_same_picture(jsmolka_rom(name), frames=60)
```

Create `tests/runtime/test_render_raster.py`:
```python
"""Raster effects, compared with mGBA: HBlank DMA writing a scroll register or a colour
line after line."""

import pytest
from rendertest import assert_test_rom_matches

BG0HOFS, BACKDROP = 0x04000010, 0x05000000


def raster(dispcnt: int, split: int, target: int) -> str:
    """testdata.h for raster.c."""
    return (f"#define DISPCNT 0x{dispcnt:04x}\n#define SPLIT {split}\n"
            f"#define TARGET 0x{target:08x}\n")


SCENES = {
    "hblank-dma-wave": raster(0x0500, 0, BG0HOFS),
    "hblank-dma-backdrop-colours": raster(0x0100, 0, BACKDROP),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_raster_effects_look_like_mgba(data):
    assert_test_rom_matches("raster", data)
```

Create `tests/runtime/test_render_text.py`:
```python
"""Text backgrounds (modes 0 and 1), compared with mGBA: colour depths, map sizes,
scrolling, flips, palette banks, and how four layers stack by priority."""

import pytest
from rendertest import assert_test_rom_matches


def bg(char: int = 0, screen: int = 16, size: int = 0, colors256: bool = False,
       priority: int = 0) -> int:
    """A BGnCNT value: char block (16 KiB), screen block (2 KiB), size 0-3."""
    return priority | char << 2 | (0x80 if colors256 else 0) | screen << 8 | size << 14


def scene(dispcnt: int, *bgs: tuple[int, int, int]) -> str:
    """testdata.h for text_bg.c: DISPCNT, then (BGnCNT, HOFS, VOFS) for BG0 upwards."""
    rows = list(bgs) + [(0, 0, 0)] * (4 - len(bgs))
    lines = [f"#define DISPCNT 0x{dispcnt:04x}"]
    for n, (control, hofs, vofs) in enumerate(rows):
        lines += [f"#define BGCNT{n} 0x{control:04x}", f"#define HOFS{n} {hofs}",
                  f"#define VOFS{n} {vofs}"]
    return "\n".join(lines) + "\n"


SCENES = {
    "4bpp-256x256": scene(0x0100, (bg(screen=16), 13, 7)),
    "8bpp-512x256": scene(0x0100, (bg(char=1, screen=18, size=1, colors256=True), 300, 20)),
    "256x512": scene(0x0200, (0, 0, 0), (bg(screen=20, size=2), 5, 300)),
    "512x512": scene(0x0400, (0, 0, 0), (0, 0, 0), (bg(char=1, screen=24, size=3), 400, 450)),
    "four-layers": scene(
        0x0F00,
        (bg(screen=16, priority=3), 3, 1),
        (bg(char=1, screen=18, priority=1), 100, 50),
        (bg(screen=20, colors256=True, priority=1), 7, 9),
        (bg(char=1, screen=22, priority=0), 250, 130),
    ),
    "mode1": scene(0x0301, (bg(screen=16, priority=1), 0, 0), (bg(char=1, screen=18), 33, 44)),
    "mode2-has-no-text-backgrounds": scene(0x0302, (bg(screen=16), 0, 0), (bg(screen=18), 0, 0)),
    "tiles-past-bg-vram": scene(0x0100, (bg(char=3, screen=16), 0, 0)),
    "scroll-past-511": scene(0x0100, (bg(screen=16, size=3), 0xFFFF, 0xFE01)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_text_backgrounds_look_like_mgba(data):
    assert_test_rom_matches("text_bg", data)
```

In `tests/runtime/test_screen.py`, replace:
```python
"""The picture the hosts show: the bitmap modes, until the scanline renderer (Plan 5)."""

import pytest
```
with:
```python
"""The picture the hosts show, for the bitmap modes (the other layers: test_render_*.py)."""

import pytest
```

In `tests/runtime/test_screen.py`, replace:
```python
    0x0003,  # mode 3 with BG2 off: backdrop
    0x0100,  # mode 0 (tiles): backdrop until the renderer arrives
    0x0483,  # forced blank: white
```
with:
```python
    0x0003,  # mode 3 with BG2 off: backdrop
    0x0483,  # forced blank: white
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_render_text.py tests/runtime/test_render_public.py tests/runtime/test_render_raster.py`
Expected: FAIL — 12 failed, 2 passed.
- The eight text scenes, the two raster scenes and jsmolka's `shades` and `stripes` fail with `AssertionError: N pixels differ from mGBA's picture, ...`: tiled backgrounds are not drawn yet, so the picture is the backdrop.
- `mode2-has-no-text-backgrounds` passes already (nothing to draw). jsmolka's `hello` passes too: it draws in mode 3.
- The first run downloads the three PPU ROMs (about 2 KB) from GitHub.

- [ ] **Step 3: Draw the text backgrounds**

In `src/gbaport/runtime/render.c`, replace:
```c
 * background number), or the backdrop, palette entry 0. Forced blank draws white.
 *
```
with:
```c
 * background number), or the backdrop, palette entry 0. Forced blank draws white.
 *
 * Text backgrounds (BG0-BG3 in mode 0, BG0 and BG1 in mode 1) are 8x8 tiles named by a
 * map of 32x32 entries per 2 KiB screen block: 256 or 512 pixels each way, scrolled by
 * BGnHOFS/BGnVOFS with wrap-around. An entry holds the tile number, flips and (for 16-colour
 * tiles) a palette bank. Tile data past background VRAM (0x10000) is transparent.
 *
```

In `src/gbaport/runtime/render.c`, replace:
```c

static uint16_t color_at(const uint8_t *memory, uint32_t offset)
{
    return (uint16_t)((memory[offset] | memory[offset + 1] << 8) & 0x7FFF);
}
```
with:
```c

static uint16_t halfword(const uint8_t *memory, uint32_t offset)
{
    return (uint16_t)(memory[offset] | memory[offset + 1] << 8);
}

static uint16_t color_at(const uint8_t *memory, uint32_t offset)
{
    return halfword(memory, offset) & 0x7FFF;
}
```

In `src/gbaport/runtime/render.c`, replace:
```c
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
}
```
with:
```c
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
}

/* A text background's line. */
static void text_line(const GbaRuntime *rt, int n, int y, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    unsigned size = control >> 14, colors256 = control & 0x80;
    unsigned in_y = (unsigned)(y + IO(rt, 0x12 + 4 * n)) & 0x1FF;
    unsigned hofs = IO(rt, 0x10 + 4 * n);
    uint32_t row = (in_y & 0xF8) * 4;  /* the map entry that starts this row of tiles */
    if (size == 2)
        row += (in_y & 0x100) * 4;  /* 256x512: the lower half is the next block */
    else if (size == 3)
        row += (in_y & 0x100) * 8;  /* 512x512: two blocks further */
    for (int x = 0; x < W; x++) {
        unsigned in_x = (x + hofs) & 0x1FF;
        uint32_t index = row + (in_x & 0xF8) / 8;
        if (size & 1)
            index += (in_x & 0x100) * 4;  /* the right half is the next block */
        uint32_t entry = halfword(rt->vram, screen_base + index * 2);
        unsigned tx = in_x & 7, ty = in_y & 7;
        if (entry & 0x400)
            tx = 7 - tx;
        if (entry & 0x800)
            ty = 7 - ty;
        uint32_t tile = entry & 0x3FF, address;
        out[x] = CLEAR;
        if (colors256)
            address = char_base + tile * 64 + ty * 8 + tx;
        else
            address = char_base + tile * 32 + ty * 4 + tx / 2;
        if (address >= 0x10000)
            continue;
        unsigned color = rt->vram[address];
        if (!colors256)
            color = tx & 1 ? color >> 4 : color & 15;
        if (color)
            out[x] = color_at(rt->palette, (colors256 ? color : (entry >> 12) * 16 + color) * 2);
    }
}
```

In `src/gbaport/runtime/render.c`, replace:
```c
    unsigned enabled = 0;
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
```
with:
```c
    unsigned enabled = 0;
    for (int n = 0; n < 4; n++) {
        int text = mode == 0 || (mode == 1 && n < 2);
        if (text && (control & (0x100u << n))) {
            text_line(rt, n, y, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 649 passed (636 + 14 new, less test_screen's mode 0 case).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/gbaroms/text_bg.c tests/gbaroms/raster.c tests/jsmolka.py tests/publicroms/jsmolka tests/runtime/test_public_roms.py tests/runtime/test_screen.py tests/runtime/test_render_text.py tests/runtime/test_render_public.py tests/runtime/test_render_raster.py
git commit -m "feat: text backgrounds; jsmolka's PPU test ROMs and HBlank DMA raster effects match mGBA"
```

---

### Task 4: Rotation/scaling backgrounds

BG2 in mode 1, and BG2 and BG3 in mode 2, are rotation/scaling backgrounds: 128 to 1024 pixels square, made of 256-colour tiles named by one-byte map entries. Outside the square they are transparent, or wrap around when BGnCNT bit 13 says so. Each line walks the background from its internal reference point (Task 2) by (PA, PC) per pixel. With these in place, the raster test can switch from mode 0 to mode 1 at line 80.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Create: `tests/gbaroms/affine_bg.c`
- Test: `tests/runtime/test_render_affine.py`
- Modify: `tests/runtime/test_render_raster.py` (the mode switch at line 80)

**Interfaces:**
- Consumes: `IO`, `CLEAR`, `color_at`, `Layers`, `compose`, `rt->affine_x`/`affine_y` and their stepping in `gba_render_line` (Task 2); `text_line` (Task 3); `raster.c`'s `SPLIT` (Task 3).
- **Produces:**
  - **In `render.c`:** `affine_line(rt, n, out)` draws BG2's or BG3's line from its reference point. `gba_render_line` draws BG2 in mode 1, and BG2 and BG3 in mode 2.
  - **`affine_bg.c`** takes `DISPCNT`, `BGCNT0`, `BGCNT2`, `BGCNT3`, each background's matrix (`PA2`..`PD2`, `PA3`..`PD3`) and reference point (`X2`, `Y2`, `X3`, `Y3`) from `testdata.h`.

- [ ] **Step 1: Write the failing tests and the test ROM**

Create `tests/gbaroms/affine_bg.c`:
```c
/* Rotation/scaling backgrounds (modes 1 and 2): VRAM's first 32 KiB holds varied
 * 256-colour tiles with gaps, the second 32 KiB varied one-byte map entries, and BG0 (a
 * text background in mode 1) a tile map of its own. testdata.h sets DISPCNT, BG2CNT and
 * BG3CNT, each background's matrix (PA2..PD2, PA3..PD3) and reference point (X2, Y2, X3,
 * Y3); BG0 uses BGCNT0. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define REG_BGCNT(n) REG16(0x04000008 + 2 * (n))
#define REG_BGP(n, i) REG16(0x04000020 + 0x10 * ((n) - 2) + 2 * (i))
#define REG_BGX(n) REG32(0x04000028 + 0x10 * ((n) - 2))
#define REG_BGY(n) REG32(0x0400002C + 0x10 * ((n) - 2))

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

int main(void)
{
    PALETTE[0] = 0x5294;
    for (uint32_t i = 1; i < 256; i++)
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x4000; i++) {  /* tiles: 0x0000-0x7FFF, every 8th row clear */
        uint32_t bits = mix(i + 1);
        VRAM[i] = (uint16_t)((i & 0x1C) == 0 ? 0 : bits);
    }
    for (uint32_t i = 0; i < 0x4000; i++)  /* maps: 0x8000-0xFFFF */
        VRAM[0x4000 + i] = (uint16_t)(mix(i * 7 + 3) & 0xFFFF);
    REG_BGCNT(0) = BGCNT0;
    REG_BGCNT(2) = BGCNT2;
    REG_BGCNT(3) = BGCNT3;
    static const int16_t matrix[2][4] = {{PA2, PB2, PC2, PD2}, {PA3, PB3, PC3, PD3}};
    static const int32_t point[2][2] = {{X2, Y2}, {X3, Y3}};
    for (int n = 2; n < 4; n++) {
        for (int i = 0; i < 4; i++)
            REG_BGP(n, i) = (uint16_t)matrix[n - 2][i];
        REG_BGX(n) = (uint32_t)point[n - 2][0];
        REG_BGY(n) = (uint32_t)point[n - 2][1];
    }
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
```

Create `tests/runtime/test_render_affine.py`:
```python
"""Rotation/scaling backgrounds (BG2 in modes 1 and 2, BG3 in mode 2), compared with
mGBA: sizes, wrap-around or transparency outside, matrices, and stacking."""

import pytest
from rendertest import assert_test_rom_matches


def bg(char: int = 0, screen: int = 16, size: int = 0, wrap: bool = False,
       priority: int = 0) -> int:
    return priority | char << 2 | screen << 8 | (0x2000 if wrap else 0) | size << 14


IDENTITY = (0x100, 0, 0, 0x100)


def scene(dispcnt: int, bg2: int = 0, m2=IDENTITY, p2=(0, 0), bg3: int = 0, m3=IDENTITY,
          p3=(0, 0), bg0: int = 0) -> str:
    """testdata.h for affine_bg.c."""
    values = {"DISPCNT": dispcnt, "BGCNT0": bg0, "BGCNT2": bg2, "BGCNT3": bg3}
    for name, value in zip(("PA2", "PB2", "PC2", "PD2"), m2):
        values[name] = value
    for name, value in zip(("PA3", "PB3", "PC3", "PD3"), m3):
        values[name] = value
    values |= {"X2": p2[0], "Y2": p2[1], "X3": p3[0], "Y3": p3[1]}
    return "".join(f"#define {name} {value}\n" for name, value in values.items())


ROTATE = (0xDD, -0x80, 0x80, 0xDD)  # about 30 degrees
SCENES = {
    "128-clear-outside": scene(0x0402, bg2=bg(screen=16), m2=ROTATE, p2=(-40 << 8, -20 << 8)),
    "256-wrap": scene(0x0402, bg2=bg(screen=18, size=1, wrap=True), m2=(0x180, 0x30, -0x30, 0x80),
                      p2=(100 << 8, -30 << 8)),
    "512": scene(0x0402, bg2=bg(char=1, screen=20, size=2), m2=(0x300, 0, 0, 0x300),
                 p2=(5 << 8, 7 << 8)),
    "1024-wrap": scene(0x0402, bg2=bg(screen=24, size=3, wrap=True), m2=(-0xC0, 0x90, -0x90, -0xC0),
                       p2=(700 << 8, 900 << 8)),
    "bg2-and-bg3": scene(0x0C02, bg2=bg(screen=16, size=1, priority=1), m2=ROTATE,
                         bg3=bg(char=1, screen=26, size=1, wrap=True), m3=(0x100, 0, 0x40, 0x100),
                         p3=(-8 << 8, 0)),
    "mode1-text-and-affine": scene(0x0501, bg0=0x1E00 | 1, bg2=bg(char=1, screen=16, size=1),
                                   m2=(0x80, 0, 0, 0x80)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_rotation_scaling_backgrounds_look_like_mgba(data):
    assert_test_rom_matches("affine_bg", data)
```

In `tests/runtime/test_render_raster.py`, replace:
```python
"""Raster effects, compared with mGBA: HBlank DMA writing a scroll register or a colour
line after line."""

import pytest
```
with:
```python
"""Raster effects, compared with mGBA: HBlank DMA writing a scroll register or a colour
line after line, and an interrupt switching modes halfway down the screen."""

import pytest
```

In `tests/runtime/test_render_raster.py`, replace:
```python
    "hblank-dma-backdrop-colours": raster(0x0100, 0, BACKDROP),
}
```
with:
```python
    "hblank-dma-backdrop-colours": raster(0x0100, 0, BACKDROP),
    "mode-switch-at-line-80": raster(0x0500, 1, BG0HOFS),
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_render_affine.py tests/runtime/test_render_raster.py`
Expected: FAIL — 7 failed, 2 passed: the six rotation/scaling scenes and `mode-switch-at-line-80` fail with `AssertionError: N pixels differ from mGBA's picture, ...`. The other two raster scenes pass (Task 3).

- [ ] **Step 3: Draw the rotation/scaling backgrounds**

In `src/gbaport/runtime/render.c`, replace:
```c
 * tiles) a palette bank. Tile data past background VRAM (0x10000) is transparent.
 *
```
with:
```c
 * tiles) a palette bank. Tile data past background VRAM (0x10000) is transparent.
 *
 * Rotation/scaling backgrounds (BG2 in mode 1, BG2 and BG3 in mode 2) are 128 to 1024
 * pixels square, of 256-colour tiles named by one-byte map entries. Outside the square
 * they are transparent, or wrap around when BGnCNT bit 13 says so.
 *
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* Modes 3-5: BG2 is a bitmap, walked like the rotation/scaling backgrounds. */
```
with:
```c

/* A rotation/scaling background's line (n = 2 or 3). */
static void affine_line(const GbaRuntime *rt, int n, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    int32_t size = 128 << (control >> 14);  /* pixels each way */
    int k = n - 2;
    int32_t x = rt->affine_x[k], y = rt->affine_y[k];
    int32_t dx = (int16_t)IO(rt, 0x20 + 0x10 * k), dy = (int16_t)IO(rt, 0x24 + 0x10 * k);
    for (int i = 0; i < W; i++, x += dx, y += dy) {
        int32_t tx = x >> 8, ty = y >> 8;
        out[i] = CLEAR;
        if (control & 0x2000) {  /* wrap around */
            tx &= size - 1;
            ty &= size - 1;
        } else if (tx < 0 || ty < 0 || tx >= size || ty >= size) {
            continue;
        }
        uint32_t tile = rt->vram[screen_base + (uint32_t)((ty >> 3) * (size >> 3) + (tx >> 3))];
        uint8_t color = rt->vram[char_base + tile * 64 + (uint32_t)((ty & 7) * 8 + (tx & 7))];
        if (color)
            out[i] = color_at(rt->palette, color * 2u);
    }
}

/* Modes 3-5: BG2 is a bitmap, walked like the rotation/scaling backgrounds. */
```

In `src/gbaport/runtime/render.c`, replace:
```c
    }
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
```
with:
```c
    }
    for (int n = 2; n < 4; n++) {
        int affine = (mode == 1 && n == 2) || mode == 2;
        if (affine && (control & (0x100u << n))) {
            affine_line(rt, n, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 656 passed (649 + 7).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/gbaroms/affine_bg.c tests/runtime/test_render_affine.py tests/runtime/test_render_raster.py
git commit -m "feat: rotation/scaling backgrounds, and a mode switch halfway down the screen"
```

---

### Task 5: Sprites

The sprite layer:
- **Shape and size.** OAM's 128 entries, in order, in 12 sizes from 8x8 to 64x64.
- **Colours and tiles.** 16 or 256 colours, tiles laid out in 1D or in a 2D sheet 32 tiles wide, flips.
- **Rotation/scaling.** One of 32 matrices, sampled around the sprite's centre, in a box twice its size with "double size".
- **Where the picture is cut.** The screen's edges, and the wrap past line 255 and column 511.
- **Bitmap modes.** The tiles below 512 belong to the picture and are not drawn.
- **Priority.** Sprites stack among themselves and against backgrounds, with mGBA's rule for a later sprite's transparent pixel.
- **Line time.** A line takes sprites only while it has time: 1210 cycles (954 with "HBlank interval free"). A sprite costs its width, or 10 plus twice its box's width when it rotates.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Create: `tests/gbaroms/sprites.c`
- Test: `tests/runtime/test_render_sprites.py`

**Interfaces:**
- Consumes: `IO`, `CLEAR`, `halfword`, `color_at`, `Layers`, `compose` (Tasks 2 and 3).
- **Produces:**
  - **In `render.c`:**
    - `Layers` gains `obj[240]` (the sprites' colours, or `CLEAR`) and `obj_priority[240]` (4 where no sprite drew).
    - `SPRITE_SIZES[16][2]` gives width and height by `shape * 4 + size` (shape 3: 0x0, nothing drawn).
    - `sprite_line(rt, entry, in_y, layers)` draws one sprite's part of a line.
    - `sprites_line(rt, y, layers)` draws line y of the sprite layer, within the line's time.
    - `compose` puts sprites above backgrounds of the same priority. `gba_render_line` draws sprites when DISPCNT bit 12 is set.
  - **`sprites.c`** takes `DISPCNT`, `BGCNT0`, `OBJS` (`{attr0, attr1, attr2}` each; the other entries are disabled) and `MATRICES` (`{PA, PB, PC, PD}` each) from `testdata.h`.
  - **`test_render_sprites.py`** has `obj(x, y, shape, size, tile, palette, priority, colors256, hflip, vflip, affine, double, mode) -> (attr0, attr1, attr2)` and `IDENTITY`. Task 6 moves both to `rendertest`.

- [ ] **Step 1: Write the failing test and the test ROM**

Create `tests/gbaroms/sprites.c`:
```c
/* Sprites: OBJ VRAM holds varied tiles with gaps, BG VRAM a text background (BG0, as
 * BGCNT0 says) to stack them against. testdata.h sets DISPCNT, BGCNT0, the sprites (OBJS:
 * {attr0, attr1, attr2} each, the rest disabled) and the rotation/scaling matrices
 * (MATRICES: {PA, PB, PC, PD} each). In the bitmap modes BG2 shows a mode 3 or 4 picture. */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define OAM ((volatile uint16_t *)0x07000000)
#define REG_BGCNT0 REG16(0x04000008)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static const uint16_t objs[][3] = OBJS;
static const int16_t matrices[][4] = MATRICES;

int main(void)
{
    PALETTE[0] = 0x5294;
    for (uint32_t i = 1; i < 512; i++)  /* both palettes */
        PALETTE[i] = (uint16_t)(mix(i) & 0x7FFF);
    for (uint32_t i = 0; i < 0x8000; i++) {  /* BG tiles and maps, then OBJ tiles */
        uint32_t bits = mix(i + 1);
        if ((i & 0xF) < 4)  /* the first rows of every tile are partly clear */
            bits &= 0x00F0;
        if (i >= 0x4000 && i < 0x8000)
            bits = mix(i * 5) & 0x0FFF;  /* maps: low tile numbers, no flips, bank 0 */
        VRAM[i] = (uint16_t)bits;
    }
    for (uint32_t i = 0x8000; i < 0xC000; i++) {
        uint32_t bits = mix(i * 3 + 1);
        if ((i & 0xF) < 4)
            bits &= 0x0F00;
        VRAM[i] = (uint16_t)bits;
    }
    if ((DISPCNT & 7) == 3) {
        for (uint32_t i = 0; i < 240 * 160; i++)
            VRAM[i] = (uint16_t)(i * 37 & 0x7FFF);
    }
    for (int i = 0; i < 128; i++) {
        OAM[i * 4] = 0x0200;  /* disabled */
        OAM[i * 4 + 1] = 0;
        OAM[i * 4 + 2] = 0;
    }
    for (unsigned i = 0; i < sizeof objs / sizeof objs[0]; i++) {
        OAM[i * 4] = objs[i][0];
        OAM[i * 4 + 1] = objs[i][1];
        OAM[i * 4 + 2] = objs[i][2];
    }
    for (unsigned i = 0; i < sizeof matrices / sizeof matrices[0]; i++) {
        for (int k = 0; k < 4; k++)
            OAM[(i * 4 + k) * 4 + 3] = (uint16_t)matrices[i][k];
    }
    REG_BGCNT0 = BGCNT0;
    irq_init();
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = DISPCNT;
    for (;;)
        bios_vblank_wait();
}
```

Create `tests/runtime/test_render_sprites.py`:
```python
"""Sprites, compared with mGBA: shapes and sizes, colour depths, 1D and 2D tile mapping,
flips, rotation/scaling and double size, the screen's edges, priorities among sprites and
against backgrounds, the bitmap modes, and how many sprites a line has time for."""

import pytest
from rendertest import assert_test_rom_matches

IDENTITY = (0x100, 0, 0, 0x100)


def obj(x: int, y: int, shape: int = 0, size: int = 0, tile: int = 0, palette: int = 0,
        priority: int = 0, colors256: bool = False, hflip: bool = False, vflip: bool = False,
        affine: int | None = None, double: bool = False, mode: int = 0) -> tuple[int, int, int]:
    """OAM attributes 0-2 of a sprite (affine: its matrix number)."""
    a0 = (y & 0xFF) | mode << 10 | (0x2000 if colors256 else 0) | shape << 14
    a1 = (x & 0x1FF) | size << 14
    if affine is None:
        a1 |= hflip << 12 | vflip << 13
    else:
        a0 |= 0x100 | (0x200 if double else 0)
        a1 |= affine << 9
    return a0, a1, tile | priority << 10 | palette << 12


def scene(dispcnt: int, objs: list[tuple[int, int, int]], matrices=(IDENTITY,), bgcnt0: int = 0) -> str:
    """testdata.h for sprites.c."""
    rows = ", ".join(f"{{{a}, {b}, {c}}}" for a, b, c in objs)
    mats = ", ".join(f"{{{a}, {b}, {c}, {d}}}" for a, b, c, d in matrices)
    return (f"#define DISPCNT 0x{dispcnt:04x}\n#define BGCNT0 0x{bgcnt0:04x}\n"
            f"#define OBJS {{{rows}}}\n#define MATRICES {{{mats}}}\n")


ALL_SIZES = [(shape, size) for shape in range(3) for size in range(4)]
GRID = [(8 + 58 * (i % 4), 4 + 52 * (i // 4)) for i in range(12)]

SCENES = {
    "shapes-16-colours-1d": scene(0x1040, [
        obj(x, y, shape, size, tile=24 * i, palette=i, hflip=i % 3 == 1, vflip=i % 4 == 2)
        for i, ((shape, size), (x, y)) in enumerate(zip(ALL_SIZES, GRID))
    ]),
    "shapes-256-colours-2d": scene(0x1000, [
        obj(x, y, shape, size, tile=37 * i + 1, colors256=True, hflip=i % 2 == 1)
        for i, ((shape, size), (x, y)) in enumerate(zip(ALL_SIZES, GRID))
    ]),
    "screen-edges": scene(0x1040, [
        obj(500, 20, 0, 2, tile=10), obj(230, 60, 1, 3, tile=200), obj(40, 250, 0, 3, tile=300),
        obj(100, 140, 2, 3, tile=400, colors256=True), obj(240, 10, 0, 1, tile=5),
        obj(10, 160, 0, 1, tile=6), obj(470, 200, 1, 3, tile=50),
    ]),
    "rotation-scaling": scene(0x1040, [
        obj(10, 10, 0, 2, tile=64, affine=0), obj(60, 10, 0, 2, tile=96, affine=1, double=True),
        obj(140, 20, 1, 3, tile=128, affine=2, colors256=True), obj(20, 90, 2, 3, tile=256, affine=3),
        obj(100, 90, 0, 3, tile=512, affine=0, double=True), obj(200, 120, 0, 1, tile=7, affine=1),
    ], matrices=[(0xDD, -0x80, 0x80, 0xDD), (0x80, 0, 0, 0x80), (0x100, 0x60, 0, 0x100),
                 (-0x120, 0x30, -0x30, 0x150)]),
    "matrices-that-make-no-picture": scene(0x1040, [
        obj(10, 10, 0, 2, tile=64, affine=0), obj(60, 10, 0, 3, tile=96, affine=1, double=True),
        obj(140, 40, 1, 3, tile=128, affine=2), obj(20, 90, 0, 3, tile=200, affine=3, double=True),
    ], matrices=[(0, 0, 0, 0), (0x7FFF, 0x7FFF, -0x8000, 0x7FFF), (-0x8000, 0, 0, -0x8000),
                 (1, 0, 0, 1)]),
    "priorities": scene(0x1140, [
        obj(20, 20, 0, 3, tile=0, priority=2), obj(50, 40, 0, 3, tile=64, priority=0),
        obj(90, 30, 0, 3, tile=128, priority=1), obj(120, 60, 0, 3, tile=192, priority=3),
        obj(30, 90, 1, 3, tile=256, priority=1), obj(40, 100, 1, 3, tile=320, priority=1),
    ], bgcnt0=0x1000 | 1),
    "bitmap-mode-keeps-low-tiles-for-the-picture": scene(0x1443, [
        obj(20, 20, 0, 3, tile=100), obj(100, 20, 0, 3, tile=600), obj(40, 90, 1, 3, tile=511),
        obj(140, 90, 1, 3, tile=700, colors256=True),
    ]),
    "line-time-runs-out": scene(0x1040, [
        obj(8 * i, 30 + i, 0, 3, tile=64 * (i % 8), affine=i % 2, double=True) for i in range(16)
    ], matrices=[(0x100, 0, 0, 0x100), (0xC0, 0x40, -0x40, 0xC0)]),
    "hblank-free-has-less-time": scene(0x1060, [
        obj(8 * i, 30 + i, 0, 3, tile=64 * (i % 8), affine=i % 2, double=True) for i in range(16)
    ], matrices=[(0x100, 0, 0, 0x100), (0xC0, 0x40, -0x40, 0xC0)]),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_sprites_look_like_mgba(data):
    assert_test_rom_matches("sprites", data)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_render_sprites.py`
Expected: FAIL — 9 failed: every sprite scene fails with `AssertionError: N pixels differ from mGBA's picture, ...`; no sprite is drawn yet.

- [ ] **Step 3: Draw the sprites**

In `src/gbaport/runtime/render.c`, replace:
```c
 * as they are then: a game that changes them between lines gets its raster effects. Each
 * enabled background is drawn into a line of its own; then every pixel takes the colour
 * of the topmost background there (the lower priority number; between equals, the lower
 * background number), or the backdrop, palette entry 0. Forced blank draws white.
 *
```
with:
```c
 * as they are then: a game that changes them between lines gets its raster effects. Each
 * enabled layer is drawn into a line of its own; then every pixel takes the colour of the
 * topmost layer there, or the backdrop, palette entry 0. The lower priority number is on
 * top; at equal priority sprites come before backgrounds, and BG0 before BG3. Forced blank
 * draws white.
 *
```

In `src/gbaport/runtime/render.c`, replace:
```c
 * they are transparent, or wrap around when BGnCNT bit 13 says so.
 *
```
with:
```c
 * they are transparent, or wrap around when BGnCNT bit 13 says so.
 *
 * Sprites (OAM's 128 entries, in order) come in 12 sizes from 8x8 to 64x64, 16 or 256
 * colours, with tiles laid out in 1D (DISPCNT bit 6) or in a 2D sheet 32 tiles wide; in
 * the bitmap modes the tiles below 512 belong to the picture and are not drawn. A
 * rotation/scaling sprite samples its tiles through one of 32 matrices kept in OAM, around
 * its centre, in a box twice its size with "double size". Like mGBA, an earlier sprite
 * wins at equal priority, a later sprite's transparent pixel still passes its lower
 * priority number to the pixel below it, and a line takes sprites only while it has time:
 * 1210 cycles (954 with "HBlank interval free"), a sprite costing its width, or 10 plus
 * twice its box's width when it rotates.
 *
```

In `src/gbaport/runtime/render.c`, replace:
```c

typedef struct {
    uint16_t bg[4][W];  /* each background's colours on this line, or CLEAR */
} Layers;

static uint16_t halfword(const uint8_t *memory, uint32_t offset)
```
with:
```c

typedef struct {
    uint16_t bg[4][W];         /* each background's colours on this line, or CLEAR */
    uint16_t obj[W];           /* the sprites' colours, or CLEAR */
    uint8_t obj_priority[W];   /* the sprites' priority; 4 where none drew */
} Layers;

static const uint8_t SPRITE_SIZES[16][2] = {  /* by shape * 4 + size: width, height */
    {8, 8}, {16, 16}, {32, 32}, {64, 64}, {16, 8}, {32, 8}, {32, 16}, {64, 32},
    {8, 16}, {8, 32}, {16, 32}, {32, 64}, {0, 0}, {0, 0}, {0, 0}, {0, 0},
};

static uint16_t halfword(const uint8_t *memory, uint32_t offset)
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* Every pixel: the topmost background with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned enabled, uint16_t *row)
```
with:
```c

/* One sprite's part of line y (in_y: the line within its box). */
static void sprite_line(const GbaRuntime *rt, const uint8_t *entry, int in_y, Layers *layers)
{
    uint16_t a0 = halfword(entry, 0), a1 = halfword(entry, 2), a2 = halfword(entry, 4);
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    int width = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][0];
    int height = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][1];
    int affine = a0 & 0x100, twice = affine && (a0 & 0x200);
    int box_w = width << twice, box_h = height << twice;
    int left = (int)(a1 & 0x1FF) - ((a1 & 0x100) ? 512 : 0);
    unsigned colors256 = a0 & 0x2000, one_d = control & 0x40, tile = a2 & 0x3FF;
    if ((control & 7) >= 3 && tile < 512)
        return;
    if (colors256 && !one_d)
        tile &= ~1u;
    uint32_t start = tile * 32;
    uint32_t stride = one_d ? (uint32_t)width * (colors256 ? 8 : 4) / 8 : 0x80;  /* per line of tiles */
    uint32_t across = one_d ? 0x7FFF : 0x3FF, row_base = one_d ? 0 : start & 0x7C00;
    uint32_t palette = 0x200 + (colors256 ? 0 : (a2 >> 12) * 32u);
    uint8_t priority = (a2 >> 10) & 3;
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
    if (affine) {
        const uint8_t *matrix = rt->oam + ((a1 >> 9) & 31) * 32;
        pa = (int16_t)halfword(matrix, 6);
        pb = (int16_t)halfword(matrix, 14);
        pc = (int16_t)halfword(matrix, 22);
        pd = (int16_t)halfword(matrix, 30);
    }
    for (int x = left < 0 ? 0 : left; x < left + box_w && x < W; x++) {
        int tx = x - left, ty = in_y;
        if (affine) {
            int32_t cx = tx - box_w / 2, cy = in_y - box_h / 2;
            tx = (pa * cx + pb * cy + (width << 7)) >> 8;
            ty = (pc * cx + pd * cy + (height << 7)) >> 8;
            if (tx < 0 || ty < 0 || tx >= width || ty >= height)
                continue;
        } else {
            if (a1 & 0x1000)
                tx = width - 1 - tx;
            if (a1 & 0x2000)
                ty = height - 1 - ty;
        }
        uint32_t x_part, y_part;
        if (colors256) {
            x_part = (uint32_t)(tx & ~7) * 8 + (uint32_t)(tx & 7);
            y_part = (uint32_t)(ty & ~7) * stride + (uint32_t)(ty & 7) * 8;
        } else {
            x_part = (uint32_t)(tx & ~7) * 4 + (uint32_t)(tx & 7) / 2;
            y_part = (uint32_t)(ty & ~7) * stride + (uint32_t)(ty & 7) * 4;
        }
        unsigned color = rt->vram[0x10000 + ((y_part + row_base + ((x_part + start) & across)) & 0x7FFF)];
        if (!colors256)
            color = tx & 1 ? color >> 4 : color & 15;
        if (layers->obj_priority[x] <= priority)
            continue;  /* an earlier sprite, or one with a lower priority number, is on top */
        if (color) {
            layers->obj[x] = color_at(rt->palette, palette + color * 2);
            layers->obj_priority[x] = priority;
        } else if (layers->obj[x] != CLEAR) {
            layers->obj_priority[x] = priority;  /* the transparent pixel still passes its priority */
        }
    }
}

/* Line y of the sprite layer. */
static void sprites_line(const GbaRuntime *rt, int y, Layers *layers)
{
    for (int x = 0; x < W; x++) {
        layers->obj[x] = CLEAR;
        layers->obj_priority[x] = 4;
    }
    int time = IO(rt, GBA_REG_DISPCNT) & 0x20 ? 954 : 1210;
    for (int i = 0; i < 128; i++) {
        const uint8_t *entry = rt->oam + i * 8;
        uint16_t a0 = halfword(entry, 0), a1 = halfword(entry, 2);
        int affine = a0 & 0x100;
        if (!affine && (a0 & 0x200))
            continue;  /* hidden */
        int width = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][0];
        int height = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][1];
        int twice = affine && (a0 & 0x200);
        int top = a0 & 0xFF, left = a1 & 0x1FF, box_w = width << twice, box_h = height << twice;
        if ((top >= H && top + box_h < 228) || (left >= W && left + box_w < 512))
            continue;  /* nowhere on the screen */
        int bottom = top + box_h;
        if ((y < top && (bottom < 256 || y >= bottom - 256)) || y >= bottom)
            continue;  /* not on this line */
        int in_y = y - top;
        if (affine ? in_y < 0 : top + height >= 256)
            in_y += 256;  /* the sprite wraps past line 255 */
        if (((a0 >> 10) & 3) != 2)  /* OBJ window sprites draw no colour */
            sprite_line(rt, entry, in_y, layers);
        time -= affine ? 10 + box_w * 2 : width;
        if (time <= 0)
            break;
    }
}

/* Every pixel: the topmost layer with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned enabled, uint16_t *row)
```

In `src/gbaport/runtime/render.c`, replace:
```c
        for (unsigned priority = 0; priority < 4 && !found; priority++) {
            for (int n = 0; n < 4 && !found; n++) {
```
with:
```c
        for (unsigned priority = 0; priority < 4 && !found; priority++) {
            if ((enabled & 0x10) && layers->obj_priority[x] == priority && layers->obj[x] != CLEAR) {
                row[x] = layers->obj[x];
                found = 1;
            }
            for (int n = 0; n < 4 && !found; n++) {
```

In `src/gbaport/runtime/render.c`, replace:
```c
    }
    compose(rt, &layers, enabled, row);
```
with:
```c
    }
    if (control & 0x1000) {
        sprites_line(rt, y, &layers);
        enabled |= 0x10;
    }
    compose(rt, &layers, enabled, row);
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 665 passed (656 + 9).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/gbaroms/sprites.c tests/runtime/test_render_sprites.py
git commit -m "feat: sprites: sizes, colours, tile layouts, rotation/scaling, priorities and line time"
```

---

### Task 6: Windows

Windows choose which layers show where. With any of DISPCNT bits 13-15 set, every pixel takes the layer bits of the first window it is in:
- WIN0, then WIN1: rectangles from WINnH/WINnV. A rectangle whose end comes before its start wraps around. Coordinates past the screen are cut back to its edge, as in mGBA.
- Then the OBJ window: where a sprite in mode 2 has a colour. That sprite is not drawn itself.
- Otherwise WINOUT.

This task also adds a general test ROM, `scene.c`, which Tasks 6-8 share. VRAM holds varied tiles, maps and sprite tiles, and `testdata.h` lists the register writes to make. So `obj`, `IDENTITY` and a `scene` helper move into `rendertest`.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Create: `tests/gbaroms/scene.c`
- Modify: `tests/rendertest.py` (`IDENTITY`, `obj`, `scene`)
- Modify: `tests/runtime/test_render_sprites.py` (imports `IDENTITY` and `obj` from `rendertest`)
- Test: `tests/runtime/test_render_windows.py`

**Interfaces:**
- Consumes: `Layers`, `sprite_line`, `sprites_line`, `compose` (Task 5).
- **Produces:**
  - **In `render.c`:**
    - `Layers` gains `obj_window[240]`: where an OBJ window sprite has a colour.
    - `inside(value, limit, at)`: whether `at` is inside a WINnH/WINnV range, with mGBA's clamping.
    - `window_line(rt, y, layers, region)` fills each pixel's layer bits: BG0-BG3, OBJ, and bit 5 for effects (used by Task 7).
    - `compose(rt, layers, all, y, row)` draws only the layers each pixel's window allows.
  - **In `rendertest.py`:**
    - `IDENTITY = (0x100, 0, 0, 0x100)`.
    - `obj(...)`, as in Task 5.
    - `scene(io: list[tuple[int, int]], objs=(), matrices=(IDENTITY,)) -> str`: `testdata.h` for `scene.c`.
  - **`scene.c`** takes `IO_WRITES` (`{offset from 0x04000000, halfword}` each, written in order after VRAM and OAM are filled), `OBJS` and `MATRICES` from `testdata.h`.

- [ ] **Step 1: Write the failing test, the scene ROM and the shared helpers**

Create `tests/gbaroms/scene.c`:
```c
/* A general scene for the renderer tests. VRAM holds varied background tiles with gaps
 * (0x0000-0x7FFF), maps of varied entries (0x8000-0xFFFF: low tile numbers, flips, palette
 * banks) and varied sprite tiles (0x10000-0x17FFF); both palettes hold varied colours.
 * testdata.h gives the sprites (OBJS: {attr0, attr1, attr2} each, the rest disabled), their
 * matrices (MATRICES: {PA, PB, PC, PD} each) and the register writes to make, in order
 * (IO_WRITES: {offset from 0x04000000, halfword} each). */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define OAM ((volatile uint16_t *)0x07000000)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static const uint16_t objs[][3] = OBJS;
static const int16_t matrices[][4] = MATRICES;
static const uint16_t io_writes[][2] = IO_WRITES;

int main(void)
{
    for (uint32_t i = 0; i < 512; i++)
        PALETTE[i] = (uint16_t)(mix(i + 11) & 0x7FFF);
    for (uint32_t i = 0; i < 0xC000; i++) {
        uint32_t bits = mix(i + 1);
        if (i >= 0x4000 && i < 0x8000) {
            bits &= 0xFC7F;  /* map entries: tiles below 128 */
        } else if ((i & 0xF) < 4) {
            bits &= 0x0F0F;  /* the first rows of every tile are partly clear */
        }
        VRAM[i] = (uint16_t)bits;
    }
    for (int i = 0; i < 128; i++) {
        OAM[i * 4] = 0x0200;  /* disabled */
        OAM[i * 4 + 1] = 0;
        OAM[i * 4 + 2] = 0;
    }
    for (unsigned i = 0; i < sizeof objs / sizeof objs[0]; i++) {
        OAM[i * 4] = objs[i][0];
        OAM[i * 4 + 1] = objs[i][1];
        OAM[i * 4 + 2] = objs[i][2];
    }
    for (unsigned i = 0; i < sizeof matrices / sizeof matrices[0]; i++) {
        for (int k = 0; k < 4; k++)
            OAM[(i * 4 + k) * 4 + 3] = (uint16_t)matrices[i][k];
    }
    for (unsigned i = 0; i < sizeof io_writes / sizeof io_writes[0]; i++)
        REG16(0x04000000 + io_writes[i][0]) = io_writes[i][1];
    irq_init();
    REG_DISPSTAT = (uint16_t)(REG_DISPSTAT | 0x08);
    REG_IE = IRQ_VBLANK;
    for (;;)
        bios_vblank_wait();
}
```

In `tests/rendertest.py`, replace:
```python
    assert_same_picture(build_test_rom(name, data), frames)
```
with:
```python
    assert_same_picture(build_test_rom(name, data), frames)


IDENTITY = (0x100, 0, 0, 0x100)


def obj(x: int, y: int, shape: int = 0, size: int = 0, tile: int = 0, palette: int = 0,
        priority: int = 0, colors256: bool = False, hflip: bool = False, vflip: bool = False,
        affine: int | None = None, double: bool = False, mode: int = 0) -> tuple[int, int, int]:
    """OAM attributes 0-2 of a sprite (affine: its matrix number)."""
    a0 = (y & 0xFF) | mode << 10 | (0x2000 if colors256 else 0) | shape << 14
    a1 = (x & 0x1FF) | size << 14
    if affine is None:
        a1 |= hflip << 12 | vflip << 13
    else:
        a0 |= 0x100 | (0x200 if double else 0)
        a1 |= affine << 9
    return a0, a1, tile | priority << 10 | palette << 12


def scene(io: list[tuple[int, int]], objs=(), matrices=(IDENTITY,)) -> str:
    """testdata.h for scene.c: register writes ({offset, value}, in order), sprites and
    matrices."""
    writes = ", ".join(f"{{0x{offset:03x}, 0x{value:04x}}}" for offset, value in io)
    rows = ", ".join(f"{{{a}, {b}, {c}}}" for a, b, c in objs) or "{0x0200, 0, 0}"
    mats = ", ".join(f"{{{a}, {b}, {c}, {d}}}" for a, b, c, d in matrices)
    return f"#define IO_WRITES {{{writes}}}\n#define OBJS {{{rows}}}\n#define MATRICES {{{mats}}}\n"
```

In `tests/runtime/test_render_sprites.py`, replace:
```python
against backgrounds, the bitmap modes, and how many sprites a line has time for."""

import pytest
from rendertest import assert_test_rom_matches

IDENTITY = (0x100, 0, 0, 0x100)


def obj(x: int, y: int, shape: int = 0, size: int = 0, tile: int = 0, palette: int = 0,
        priority: int = 0, colors256: bool = False, hflip: bool = False, vflip: bool = False,
        affine: int | None = None, double: bool = False, mode: int = 0) -> tuple[int, int, int]:
    """OAM attributes 0-2 of a sprite (affine: its matrix number)."""
    a0 = (y & 0xFF) | mode << 10 | (0x2000 if colors256 else 0) | shape << 14
    a1 = (x & 0x1FF) | size << 14
    if affine is None:
        a1 |= hflip << 12 | vflip << 13
    else:
        a0 |= 0x100 | (0x200 if double else 0)
        a1 |= affine << 9
    return a0, a1, tile | priority << 10 | palette << 12


def scene(dispcnt: int, objs: list[tuple[int, int, int]], matrices=(IDENTITY,), bgcnt0: int = 0) -> str:
```
with:
```python
against backgrounds, the bitmap modes, and how many sprites a line has time for."""

import pytest
from rendertest import IDENTITY, assert_test_rom_matches, obj


def scene(dispcnt: int, objs: list[tuple[int, int, int]], matrices=(IDENTITY,), bgcnt0: int = 0) -> str:
```

Create `tests/runtime/test_render_windows.py`:
```python
"""Windows, compared with mGBA: WIN0 and WIN1 (rectangles, wrapping, coordinates past the
screen), the OBJ window that sprites draw, and which window wins where they overlap."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG1CNT = 0x000, 0x008, 0x00A
WIN0H, WIN1H, WIN0V, WIN1V, WININ, WINOUT = 0x040, 0x042, 0x044, 0x046, 0x048, 0x04A
LAYERS = [(BG0CNT, 0x1000 | 1), (BG1CNT, 0x1204 | 2)]  # BG0 over BG1
SPRITES = [obj(20, 20, 0, 3, tile=0, priority=0), obj(150, 70, 1, 3, tile=64, priority=0),
           obj(90, 100, 0, 2, tile=200, priority=0)]
SHAPES = [obj(60, 40, 0, 3, tile=300, mode=2), obj(120, 10, 2, 3, tile=400, mode=2)]


def windows(dispcnt: int, *writes: tuple[int, int], objs=SPRITES) -> str:
    return scene([*LAYERS, *writes, (DISPCNT, dispcnt)], objs)


BASE = 0x1340  # mode 0, BG0, BG1, sprites, 1D tiles
SCENES = {
    "win0": windows(BASE | 0x2000, (WIN0H, 40 << 8 | 200), (WIN0V, 30 << 8 | 120),
                    (WININ, 0x0011), (WINOUT, 0x0002)),
    "win0-over-win1": windows(BASE | 0x6000, (WIN0H, 20 << 8 | 140), (WIN0V, 20 << 8 | 100),
                              (WIN1H, 100 << 8 | 220), (WIN1V, 60 << 8 | 150),
                              (WININ, 0x1201), (WINOUT, 0x0010)),
    "wrapped": windows(BASE | 0x2000, (WIN0H, 200 << 8 | 40), (WIN0V, 120 << 8 | 30),
                       (WININ, 0x0013), (WINOUT, 0x0000)),
    "past-the-edges": windows(BASE | 0x6000, (WIN0H, 100 << 8 | 250), (WIN0V, 10 << 8 | 200),
                              (WIN1H, 245 << 8 | 20), (WIN1V, 170 << 8 | 50),
                              (WININ, 0x0201), (WINOUT, 0x0010)),
    "obj-window": windows(BASE | 0x8000, (WINOUT, 0x1201), objs=SPRITES + SHAPES),
    "obj-window-under-win0": windows(BASE | 0xA000, (WIN0H, 0 << 8 | 100), (WIN0V, 0 << 8 | 160),
                                     (WININ, 0x0010), (WINOUT, 0x0302), objs=SHAPES + SPRITES),
    "nothing-inside": windows(BASE | 0x2000, (WIN0H, 50 << 8 | 190), (WIN0V, 40 << 8 | 120),
                              (WININ, 0x0000), (WINOUT, 0x001F)),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_windows_look_like_mgba(data):
    assert_test_rom_matches("scene", data)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_render_windows.py tests/runtime/test_render_sprites.py`
Expected: FAIL — 7 failed, 9 passed: the seven window scenes fail with `AssertionError: N pixels differ from mGBA's picture, ...`. The sprite tests pass with their helpers moved to `rendertest`.

- [ ] **Step 3: Windows**

In `src/gbaport/runtime/render.c`, replace:
```c
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
```
with:
```c
 *
 * Windows choose which layers show where. With any of DISPCNT bits 13-15 set, every pixel
 * takes the layer bits of the first window it is in: WIN0, then WIN1 (rectangles, from
 * WINnH/WINnV), then the OBJ window (where OBJ window sprites have a colour), and
 * otherwise WINOUT. A rectangle whose end comes before its start wraps around; coordinates
 * past the screen are cut back to its edge, as in mGBA.
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
```

In `src/gbaport/runtime/render.c`, replace:
```c
    uint8_t obj_priority[W];   /* the sprites' priority; 4 where none drew */
} Layers;
```
with:
```c
    uint8_t obj_priority[W];   /* the sprites' priority; 4 where none drew */
    uint8_t obj_window[W];     /* where an OBJ window sprite has a colour */
} Layers;
```

In `src/gbaport/runtime/render.c`, replace:
```c
    uint8_t priority = (a2 >> 10) & 3;
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
```
with:
```c
    uint8_t priority = (a2 >> 10) & 3;
    int window = ((a0 >> 10) & 3) == 2;  /* draws the OBJ window, not colours */
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
```

In `src/gbaport/runtime/render.c`, replace:
```c
            color = tx & 1 ? color >> 4 : color & 15;
        if (layers->obj_priority[x] <= priority)
```
with:
```c
            color = tx & 1 ? color >> 4 : color & 15;
        if (window) {
            if (color)
                layers->obj_window[x] = 1;
            continue;
        }
        if (layers->obj_priority[x] <= priority)
```

In `src/gbaport/runtime/render.c`, replace:
```c
        layers->obj_priority[x] = 4;
    }
```
with:
```c
        layers->obj_priority[x] = 4;
        layers->obj_window[x] = 0;
    }
```

In `src/gbaport/runtime/render.c`, replace:
```c
            in_y += 256;  /* the sprite wraps past line 255 */
        if (((a0 >> 10) & 3) != 2)  /* OBJ window sprites draw no colour */
            sprite_line(rt, entry, in_y, layers);
        time -= affine ? 10 + box_w * 2 : width;
```
with:
```c
            in_y += 256;  /* the sprite wraps past line 255 */
        sprite_line(rt, entry, in_y, layers);
        time -= affine ? 10 + box_w * 2 : width;
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* Every pixel: the topmost layer with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned enabled, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    for (int x = 0; x < W; x++) {
        row[x] = backdrop;
```
with:
```c

/* WINnH or WINnV: start (high byte) and end (low byte), cut back to the screen as mGBA
 * does; returns whether position `at` is inside. */
static int inside(uint16_t value, int limit, int at)
{
    int start = value >> 8, end = value & 0xFF;
    if (start > limit && start > end)
        start = 0;
    if (end > limit) {
        end = limit;
        if (start > limit)
            start = limit;
    }
    if (end >= start)
        return at >= start && at < end;
    return at >= start || at < end;  /* wraps around */
}

/* Each pixel's layer bits (BG0-BG3, sprites, effects) on line y. */
static void window_line(const GbaRuntime *rt, int y, const Layers *layers, uint8_t *region)
{
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    if (!(control & 0xE000)) {
        for (int x = 0; x < W; x++)
            region[x] = 0x3F;
        return;
    }
    uint16_t win_in = IO(rt, 0x48), win_out = IO(rt, 0x4A);
    int in0 = (control & 0x2000) && inside(IO(rt, 0x44), H, y);
    int in1 = (control & 0x4000) && inside(IO(rt, 0x46), H, y);
    for (int x = 0; x < W; x++) {
        if (in0 && inside(IO(rt, 0x40), W, x))
            region[x] = win_in & 0x3F;
        else if (in1 && inside(IO(rt, 0x42), W, x))
            region[x] = (win_in >> 8) & 0x3F;
        else if ((control & 0x8000) && layers->obj_window[x])
            region[x] = (win_out >> 8) & 0x3F;
        else
            region[x] = win_out & 0x3F;
    }
}

/* Every pixel: the topmost layer with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned all, int y, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    uint8_t region[W];
    window_line(rt, y, layers, region);
    for (int x = 0; x < W; x++) {
        unsigned enabled = all & region[x];
        row[x] = backdrop;
```

In `src/gbaport/runtime/render.c`, replace:
```c
        enabled |= 0x10;
    }
    compose(rt, &layers, enabled, row);
    for (int n = 0; n < 2; n++) {
```
with:
```c
        enabled |= 0x10;
    } else {
        for (int x = 0; x < W; x++)
            layers.obj_window[x] = 0;  /* no sprites, no OBJ window */
    }
    compose(rt, &layers, enabled, y, row);
    for (int n = 0; n < 2; n++) {
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 672 passed (665 + 7).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/gbaroms/scene.c tests/rendertest.py tests/runtime/test_render_sprites.py tests/runtime/test_render_windows.py
git commit -m "feat: windows: WIN0, WIN1, the OBJ window and WINOUT"
```

---

### Task 7: Colour special effects

BLDCNT's effects work on the topmost layer when it is a 1st target and the window allows effects:
- **Alpha blending** with the layer right below it, when that is a 2nd target. BLDALPHA's factors count up to 16/16; the sum saturates at 31 per channel.
- **Brightening or darkening** by BLDY, up to 16/16.

The arithmetic is 5 bits per channel, like the GBA's. A semi-transparent sprite (OAM mode 1) on top of a 2nd target blends with it whatever BLDCNT's effect and the window say. Anywhere else it takes BLDCNT's effect like any other sprite, as GBATEK describes and mGBA does.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Test: `tests/runtime/test_render_effects.py`

**Interfaces:**
- Consumes: `Layers`, `sprite_line`, `window_line` (bit 5: effects allowed), `compose` (Tasks 5 and 6); `rendertest.obj` and `scene` (Task 6).
- **Produces, in `render.c`:**
  - `Layers` gains `obj_semi[240]`: the sprite colour there is semi-transparent.
  - `weight(value)`: an effect factor, 0-16 sixteenths.
  - `mix(a, b, wa, wb)`: alpha blending with saturation.
  - `brightness(color, evy, up)`: brightening or darkening.
  - `compose` finds the top two layers of every pixel (0-3 a background, 4 the sprites, 5 the backdrop) and applies the effect.

- [ ] **Step 1: Write the failing test**

Create `tests/runtime/test_render_effects.py`:
```python
"""Colour special effects, compared with mGBA: alpha blending, brightening, darkening,
semi-transparent sprites, the backdrop as a target, and windows that switch effects off."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG1CNT, WIN0H, WIN0V, WININ, WINOUT = 0x000, 0x008, 0x00A, 0x040, 0x044, 0x048, 0x04A
BLDCNT, BLDALPHA, BLDY = 0x050, 0x052, 0x054
BG0, BG1, BG2, BG3, OBJ, BD = 1, 2, 4, 8, 16, 32
ALPHA, BRIGHTEN, DARKEN = 1 << 6, 2 << 6, 3 << 6
LAYERS = [(BG0CNT, 0x1000 | 1), (BG1CNT, 0x1204 | 2)]  # BG0 over BG1
SPRITES = [obj(20, 20, 0, 3, tile=0, priority=0), obj(150, 70, 1, 3, tile=64, priority=1),
           obj(90, 100, 0, 2, tile=200, priority=0, mode=1), obj(60, 40, 0, 3, tile=300, mode=1)]


def effects(*writes: tuple[int, int], dispcnt: int = 0x1340, objs=SPRITES) -> str:
    return scene([*LAYERS, *writes, (DISPCNT, dispcnt)], objs)


SCENES = {
    "alpha": effects((BLDCNT, BG0 | ALPHA | BG1 << 8), (BLDALPHA, 6 << 8 | 10)),
    "alpha-past-16-saturates": effects((BLDCNT, BG0 | OBJ | ALPHA | (BG1 | BD) << 8),
                                       (BLDALPHA, 31 << 8 | 31)),
    "alpha-onto-a-layer-that-is-no-target": effects((BLDCNT, BG0 | ALPHA | BG3 << 8), (BLDALPHA, 8 << 8 | 8)),
    "brighten": effects((BLDCNT, BG0 | BD | BRIGHTEN), (BLDY, 9)),
    "darken-past-16": effects((BLDCNT, BG0 | BG1 | OBJ | DARKEN), (BLDY, 25)),
    "semi-transparent-sprites": effects((BLDCNT, BG1 << 8 | BD << 8), (BLDALPHA, 4 << 8 | 12)),
    "semi-transparent-sprites-with-brighten": effects((BLDCNT, OBJ | BRIGHTEN | (BG0 | BG1) << 8),
                                                      (BLDALPHA, 9 << 8 | 7), (BLDY, 12)),
    "window-switches-effects-off": effects(
        (BLDCNT, BG0 | OBJ | ALPHA | (BG1 | BD) << 8), (BLDALPHA, 10 << 8 | 6),
        (WIN0H, 40 << 8 | 180), (WIN0V, 30 << 8 | 130), (WININ, 0x001F), (WINOUT, 0x003F),
        dispcnt=0x3340),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_colour_effects_look_like_mgba(data):
    assert_test_rom_matches("scene", data)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_render_effects.py`
Expected: FAIL — 7 failed, 1 passed: the scenes with an effect fail with `AssertionError: N pixels differ from mGBA's picture, ...`. `alpha-onto-a-layer-that-is-no-target` passes already: nothing blends there.

- [ ] **Step 3: Blend, brighten and darken**

In `src/gbaport/runtime/render.c`, replace:
```c
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
```
with:
```c
 *
 * Colour special effects (BLDCNT) work on the topmost layer when it is a 1st target and
 * the window allows effects: alpha blending with the layer right below it, when that is a
 * 2nd target (BLDALPHA's factors, at most 16/16), or brightening or darkening (BLDY, at
 * most 16/16), in 5 bits per channel like the GBA. A semi-transparent sprite on top of a
 * 2nd target blends with it whatever BLDCNT's effect and the window say; anywhere else it
 * takes BLDCNT's effect like any other sprite (as GBATEK describes and mGBA does).
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
```

In `src/gbaport/runtime/render.c`, replace:
```c
    uint8_t obj_window[W];     /* where an OBJ window sprite has a colour */
} Layers;
```
with:
```c
    uint8_t obj_window[W];     /* where an OBJ window sprite has a colour */
    uint8_t obj_semi[W];       /* the sprite colour there is semi-transparent */
} Layers;
```

In `src/gbaport/runtime/render.c`, replace:
```c
    int window = ((a0 >> 10) & 3) == 2;  /* draws the OBJ window, not colours */
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
```
with:
```c
    int window = ((a0 >> 10) & 3) == 2;  /* draws the OBJ window, not colours */
    uint8_t semi = ((a0 >> 10) & 3) == 1;
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
```

In `src/gbaport/runtime/render.c`, replace:
```c
            layers->obj_priority[x] = priority;
        } else if (layers->obj[x] != CLEAR) {
            layers->obj_priority[x] = priority;  /* the transparent pixel still passes its priority */
        }
```
with:
```c
            layers->obj_priority[x] = priority;
            layers->obj_semi[x] = semi;
        } else if (layers->obj[x] != CLEAR) {
            layers->obj_priority[x] = priority;  /* the transparent pixel still passes its priority, */
            layers->obj_semi[x] = semi;          /* and whether it is semi-transparent */
        }
```

In `src/gbaport/runtime/render.c`, replace:
```c
        layers->obj_window[x] = 0;
    }
```
with:
```c
        layers->obj_window[x] = 0;
        layers->obj_semi[x] = 0;
    }
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* Every pixel: the topmost layer with a colour there, or the backdrop. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned all, int y, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    uint8_t region[W];
```
with:
```c

static unsigned weight(unsigned value)  /* an effect factor: 0-16 sixteenths */
{
    value &= 0x1F;
    return value > 16 ? 16 : value;
}

static uint16_t mix(uint16_t a, uint16_t b, unsigned wa, unsigned wb)
{
    uint16_t out = 0;
    for (int shift = 0; shift < 15; shift += 5) {
        unsigned c = (((a >> shift) & 31) * wa + ((b >> shift) & 31) * wb) / 16;
        out |= (uint16_t)((c > 31 ? 31 : c) << shift);
    }
    return out;
}

static uint16_t brightness(uint16_t color, unsigned evy, int up)
{
    uint16_t out = 0;
    for (int shift = 0; shift < 15; shift += 5) {
        unsigned c = (color >> shift) & 31;
        c = up ? c + (31 - c) * evy / 16 : c - c * evy / 16;
        out |= (uint16_t)(c << shift);
    }
    return out;
}

/* Every pixel: the topmost layer with a colour there (layer 0-3: a background, 4: the
 * sprites, 5: the backdrop), with the colour effects. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned all, int y, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    uint16_t targets = IO(rt, 0x50), factors = IO(rt, 0x52);
    unsigned effect = (targets >> 6) & 3, eva = weight(factors), evb = weight(factors >> 8);
    unsigned evy = weight(IO(rt, 0x54));
    uint8_t region[W];
```

In `src/gbaport/runtime/render.c`, replace:
```c
        unsigned enabled = all & region[x];
        row[x] = backdrop;
        int found = 0;
        for (unsigned priority = 0; priority < 4 && !found; priority++) {
            if ((enabled & 0x10) && layers->obj_priority[x] == priority && layers->obj[x] != CLEAR) {
                row[x] = layers->obj[x];
                found = 1;
            }
            for (int n = 0; n < 4 && !found; n++) {
                if ((enabled & (1u << n)) && (IO(rt, 0x08 + 2 * n) & 3) == priority &&
                    layers->bg[n][x] != CLEAR) {
                    row[x] = layers->bg[n][x];
                    found = 1;
                }
            }
        }
    }
```
with:
```c
        unsigned enabled = all & region[x];
        int layer[2] = {5, 5}, found = 0;
        uint16_t color[2] = {backdrop, backdrop};
        for (unsigned priority = 0; priority < 4 && found < 2; priority++) {
            if ((enabled & 0x10) && layers->obj_priority[x] == priority && layers->obj[x] != CLEAR) {
                layer[found] = 4;
                color[found++] = layers->obj[x];
            }
            for (int n = 0; n < 4 && found < 2; n++) {
                if ((enabled & (1u << n)) && (IO(rt, 0x08 + 2 * n) & 3) == priority &&
                    layers->bg[n][x] != CLEAR) {
                    layer[found] = n;
                    color[found++] = layers->bg[n][x];
                }
            }
        }
        int second = (targets >> 8) & (1u << layer[1]);
        if (layer[0] == 4 && layers->obj_semi[x] && second) {
            color[0] = mix(color[0], color[1], eva, evb);
        } else if ((region[x] & 0x20) && (targets & (1u << layer[0]))) {
            if (effect == 1 && second)
                color[0] = mix(color[0], color[1], eva, evb);
            else if (effect >= 2)
                color[0] = brightness(color[0], evy, effect == 2);
        }
        row[x] = color[0];
    }
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 680 passed (672 + 8).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/runtime/test_render_effects.py
git commit -m "feat: colour special effects: alpha blending, brightening, darkening, semi-transparent sprites"
```

---

### Task 8: Mosaic, and a busy picture

Mosaic shows blocks. It applies to backgrounds with BGnCNT bit 6 and sprites with OAM bit 12, sized by the MOSAIC register. Every line repeats the first line of its group of lines, and every pixel the first pixel of its group of pixels. Groups are counted from the screen's top-left corner. As in mGBA:
- a rotation/scaling or bitmap background whose group starts outside the background tries again at the next pixel;
- a sprite's line comes from its first line inside the group;
- a plain sprite widens to the end of its last group, repeating its edge.

To share the vertical step back, the rotation/scaling and bitmap backgrounds now go through one walker, `affine_line`, that reads texels with `texel`.

The busy-picture test (Review Focus 5) comes with this task, because it needs every feature:
- Its picture test fails until mosaic is drawn.
- Its speed test may already pass here. It guards against a renderer too slow for the GBA's frame rate.

**Files:**
- Modify: `src/gbaport/runtime/render.c`
- Test: `tests/runtime/test_render_mosaic.py`, `tests/runtime/test_render_speed.py`

**Interfaces:**
- Consumes: `text_line`, `affine_line`, `bitmap_line`, `sprite_line`, `sprites_line`, `compose` (Tasks 2-7); `rendertest.obj`, `scene`, `our_picture`, `assert_same_picture` (Tasks 1 and 6); `romtest.build_test_rom`.
- **Produces, in `render.c`:**
  - `hold(line, size)`: horizontal mosaic on a drawn line.
  - `texel(rt, n, mode, tx, ty, &outside)`: BG2's or BG3's colour at a texel, in modes 1-5, or `CLEAR`. `*outside` says the texel is off the background.
  - `affine_line(rt, n, y, mode, out)` replaces `affine_line(rt, n, out)` and `bitmap_line`. It walks from the reference point, stepped back to the mosaic group's first line.
  - `sprite_line(rt, entry, in_y, group, layers)` gains `group`: the mosaic's width for that sprite, 1 without mosaic.

- [ ] **Step 1: Write the failing tests**

Create `tests/runtime/test_render_mosaic.py`:
```python
"""Mosaic, compared with mGBA: text, rotation/scaling and bitmap backgrounds, and sprites
(plain and rotating), including groups cut by a window."""

import pytest
from rendertest import assert_test_rom_matches, obj, scene

DISPCNT, BG0CNT, BG2CNT, BG0HOFS, BG0VOFS = 0x000, 0x008, 0x00C, 0x010, 0x012
BG2PA, BG2PB, BG2PC, BG2PD, BG2X, BG2Y = 0x020, 0x022, 0x024, 0x026, 0x028, 0x02C
WIN0H, WIN0V, WININ, WINOUT, MOSAIC = 0x040, 0x044, 0x048, 0x04A, 0x04C


def mosaic(bg_h: int, bg_v: int, obj_h: int = 1, obj_v: int = 1) -> tuple[int, int]:
    return MOSAIC, (bg_h - 1) | (bg_v - 1) << 4 | (obj_h - 1) << 8 | (obj_v - 1) << 12


ROTATE = [(BG2PA, 0xDD), (BG2PB, 0xFF80), (BG2PC, 0x80), (BG2PD, 0xDD),
          (BG2X, 0xD800), (BG2X + 2, 0xFFFF), (BG2Y, 0xEC00), (BG2Y + 2, 0xFFFF)]  # (-40, -20)
SPRITES = [obj(3, 10, 0, 3, tile=0), obj(70, 20, 1, 3, tile=64, hflip=True),
           obj(150, 30, 2, 3, tile=128, vflip=True), obj(201, 100, 0, 2, tile=200),
           obj(40, 250, 0, 3, tile=300)]
SPRITES = [(a0 | 0x1000, a1, a2) for a0, a1, a2 in SPRITES]  # all with mosaic
TURNING = [(a0 | 0x1000, a1, a2) for a0, a1, a2 in [
    obj(10, 10, 0, 2, tile=0, affine=0), obj(80, 30, 0, 3, tile=64, affine=1, double=True),
    obj(160, 70, 1, 3, tile=128, affine=0),
]]
MATRICES = [(0xDD, -0x80, 0x80, 0xDD), (0x80, 0x20, -0x20, 0x80)]

SCENES = {
    "text": scene([(BG0CNT, 0x1040), (BG0HOFS, 5), (BG0VOFS, 3), mosaic(4, 3), (DISPCNT, 0x0100)]),
    "text-cut-by-a-window": scene([
        (BG0CNT, 0x1040), mosaic(6, 5), (WIN0H, 37 << 8 | 150), (WIN0V, 21 << 8 | 130),
        (WININ, 0x0001), (WINOUT, 0x0001), (DISPCNT, 0x2100),
    ]),
    "rotation-scaling": scene([(BG2CNT, 0x1040), *ROTATE, mosaic(5, 5), (DISPCNT, 0x0402)]),
    "bitmap": scene([(BG2CNT, 0x0040), (BG2PA, 0x90), (BG2PD, 0xC0), mosaic(7, 2), (DISPCNT, 0x0403)]),
    "sprites": scene([(BG0CNT, 0x1000 | 1), mosaic(1, 1, 4, 4), (DISPCNT, 0x1140)], SPRITES),
    "sprites-wide-groups": scene([mosaic(1, 1, 9, 2), (DISPCNT, 0x1040)], SPRITES),
    "turning-sprites": scene([mosaic(1, 1, 3, 5), (DISPCNT, 0x1040)], TURNING, MATRICES),
}


@pytest.mark.parametrize("data", SCENES.values(), ids=SCENES.keys())
def test_mosaic_looks_like_mgba(data):
    assert_test_rom_matches("scene", data)
```

Create `tests/runtime/test_render_speed.py`:
```python
"""A busy picture: four backgrounds, 128 rotating sprites, both windows and the sprite
window, blending and mosaic, all at once. It looks like mGBA's, and the native build draws
it faster than the GBA shows it.

Two things mGBA does differently from the GBA are left out: it draws the sprites that make
the OBJ window without mosaic, and it restarts a 256-colour background's mosaic where a
window starts. So those sprites and BG2 (256 colours) have no mosaic here."""

import math
import time

from rendertest import assert_same_picture, obj, our_picture, scene
from romtest import build_test_rom

DISPCNT, BGCNT, MOSAIC = 0x000, 0x008, 0x04C
WIN0H, WIN1H, WIN0V, WIN1V, WININ, WINOUT = 0x040, 0x042, 0x044, 0x046, 0x048, 0x04A
BLDCNT, BLDALPHA = 0x050, 0x052
MATRICES = [
    (round(256 * math.cos(a) / s), round(-256 * math.sin(a) / s),
     round(256 * math.sin(a) / s), round(256 * math.cos(a) / s))
    for a, s in ((2 * math.pi * i / 32, 0.75 + i / 40) for i in range(32))
]
SPRITES = [
    obj(37 * i % 240, 23 * i % 160, i % 3, 2 + i % 2, tile=16 * i % 1024, palette=i % 16,
        priority=i % 4, affine=i % 32, double=True, mode=i % 3)
    for i in range(128)
]
BUSY = scene([
    (BGCNT, 0x1040 | 3), (BGCNT + 2, 0x1244 | 2), (BGCNT + 4, 0x1480 | 1), (BGCNT + 6, 0x1644),
    (0x010, 13), (0x016, 7), (0x018, 300), (0x01E, 99),
    (MOSAIC, 2 | 1 << 4 | 1 << 8 | 2 << 12),
    (WIN0H, 20 << 8 | 200), (WIN0V, 10 << 8 | 150), (WIN1H, 60 << 8 | 230), (WIN1V, 40 << 8 | 120),
    (WININ, 0x2F3F), (WINOUT, 0x371B), (BLDCNT, 0x3E41), (BLDALPHA, 9 << 8 | 7),
    (DISPCNT, 0xFF40),
], [(a0 if i % 3 == 2 else a0 | 0x1000, a1, a2) for i, (a0, a1, a2) in enumerate(SPRITES)],
    MATRICES)
FRAMES = 600  # ten seconds on a GBA


def test_a_busy_picture_looks_like_mgba():
    assert_same_picture(build_test_rom("scene", BUSY))


def test_a_busy_picture_is_drawn_faster_than_the_gba_shows_it():
    rom = build_test_rom("scene", BUSY)
    our_picture(rom, frames=1)  # builds the program
    start = time.perf_counter()
    our_picture(rom, frames=FRAMES)
    seconds = time.perf_counter() - start
    assert seconds < FRAMES / 59.73, f"{FRAMES} frames took {seconds:.1f} s"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_render_mosaic.py tests/runtime/test_render_speed.py`
Expected: FAIL — 8 failed, 1 passed.
- The seven mosaic scenes and `test_a_busy_picture_looks_like_mgba` fail with `AssertionError: N pixels differ from mGBA's picture, ...`.
- `test_a_busy_picture_is_drawn_faster_than_the_gba_shows_it` passes already. It guards the speed from here on.

- [ ] **Step 3: Mosaic**

In `src/gbaport/runtime/render.c`, replace:
```c
 * takes BLDCNT's effect like any other sprite (as GBATEK describes and mGBA does).
 *
```
with:
```c
 * takes BLDCNT's effect like any other sprite (as GBATEK describes and mGBA does).
 *
 * Mosaic (MOSAIC, for backgrounds with BGnCNT bit 6 and sprites with OAM bit 12) shows
 * blocks: every line repeats the first line of its group of lines, every pixel the first
 * pixel of its group of pixels, groups counted from the screen's top-left corner. As in
 * mGBA, a rotation/scaling or bitmap background whose group starts outside it tries again
 * at the next pixel; a sprite's line comes from its first line inside the group, and a
 * plain sprite widens to the end of its last group, repeating its edge.
 *
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* A text background's line. */
static void text_line(const GbaRuntime *rt, int n, int y, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
```
with:
```c

/* Horizontal mosaic: every group of `size` pixels shows its first pixel. */
static void hold(uint16_t *line, unsigned size)
{
    for (int x = 0; size > 1 && x < W; x++)
        line[x] = line[x - x % size];
}

/* A text background's line. */
static void text_line(const GbaRuntime *rt, int n, int y, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n), mosaic = IO(rt, 0x4C);
    if (control & 0x40)
        y -= y % (int)(((mosaic >> 4) & 15) + 1);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
```

In `src/gbaport/runtime/render.c`, replace:
```c
    }
}

/* A rotation/scaling background's line (n = 2 or 3). */
static void affine_line(const GbaRuntime *rt, int n, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    int32_t size = 128 << (control >> 14);  /* pixels each way */
    int k = n - 2;
    int32_t x = rt->affine_x[k], y = rt->affine_y[k];
    int32_t dx = (int16_t)IO(rt, 0x20 + 0x10 * k), dy = (int16_t)IO(rt, 0x24 + 0x10 * k);
    for (int i = 0; i < W; i++, x += dx, y += dy) {
        int32_t tx = x >> 8, ty = y >> 8;
        out[i] = CLEAR;
        if (control & 0x2000) {  /* wrap around */
            tx &= size - 1;
            ty &= size - 1;
        } else if (tx < 0 || ty < 0 || tx >= size || ty >= size) {
            continue;
        }
        uint32_t tile = rt->vram[screen_base + (uint32_t)((ty >> 3) * (size >> 3) + (tx >> 3))];
        uint8_t color = rt->vram[char_base + tile * 64 + (uint32_t)((ty & 7) * 8 + (tx & 7))];
        if (color)
            out[i] = color_at(rt->palette, color * 2u);
    }
}

/* Modes 3-5: BG2 is a bitmap, walked like the rotation/scaling backgrounds. */
static void bitmap_line(const GbaRuntime *rt, uint16_t *out, uint32_t mode)
{
    int32_t x = rt->affine_x[0], y = rt->affine_y[0];
    int32_t dx = (int16_t)IO(rt, 0x20), dy = (int16_t)IO(rt, 0x24);  /* PA, PC */
    uint32_t page = IO(rt, GBA_REG_DISPCNT) & 0x10 ? 0xA000 : 0;
    int width = mode == 5 ? 160 : 240, height = mode == 5 ? 128 : 160;
    for (int i = 0; i < W; i++, x += dx, y += dy) {
        int tx = x >> 8, ty = y >> 8;
        out[i] = CLEAR;
        if (x < 0 || y < 0 || tx >= width || ty >= height)
            continue;
        if (mode == 3) {
            out[i] = color_at(rt->vram, (uint32_t)(ty * 240 + tx) * 2);
        } else if (mode == 4) {
            uint8_t index = rt->vram[page + (uint32_t)(ty * 240 + tx)];
            if (index)
                out[i] = color_at(rt->palette, index * 2u);
        } else {
            out[i] = color_at(rt->vram, page + (uint32_t)(ty * 160 + tx) * 2);
        }
```
with:
```c
    }
    if (control & 0x40)
        hold(out, (mosaic & 15) + 1u);
}

/* The colour of BG2/BG3's texel (tx, ty), or CLEAR; *outside says it is off a background
 * that does not wrap around. mode is DISPCNT's: 1-2 tiles, 3-5 a bitmap (BG2). */
static uint16_t texel(const GbaRuntime *rt, int n, uint32_t mode, int32_t tx, int32_t ty, int *outside)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    *outside = 0;
    if (mode >= 3) {
        uint32_t page = IO(rt, GBA_REG_DISPCNT) & 0x10 ? 0xA000 : 0;
        int width = mode == 5 ? 160 : 240, height = mode == 5 ? 128 : 160;
        if (tx < 0 || ty < 0 || tx >= width || ty >= height) {
            *outside = 1;
            return CLEAR;
        }
        if (mode == 3)
            return color_at(rt->vram, (uint32_t)(ty * 240 + tx) * 2);
        if (mode == 5)
            return color_at(rt->vram, page + (uint32_t)(ty * 160 + tx) * 2);
        uint8_t index = rt->vram[page + (uint32_t)(ty * 240 + tx)];
        return index ? color_at(rt->palette, index * 2u) : CLEAR;
    }
    int32_t size = 128 << (control >> 14);  /* pixels each way */
    if (control & 0x2000) {  /* wrap around */
        tx &= size - 1;
        ty &= size - 1;
    } else if (tx < 0 || ty < 0 || tx >= size || ty >= size) {
        *outside = 1;
        return CLEAR;
    }
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    uint32_t tile = rt->vram[screen_base + (uint32_t)((ty >> 3) * (size >> 3) + (tx >> 3))];
    uint8_t color = rt->vram[char_base + tile * 64 + (uint32_t)((ty & 7) * 8 + (tx & 7))];
    return color ? color_at(rt->palette, color * 2u) : CLEAR;
}

/* A line of BG2 or BG3 outside mode 0, walked from its reference point. */
static void affine_line(const GbaRuntime *rt, int n, int y, uint32_t mode, uint16_t *out)
{
    int k = n - 2;
    int32_t x = rt->affine_x[k], v = rt->affine_y[k];
    int32_t dx = (int16_t)IO(rt, 0x20 + 0x10 * k), dy = (int16_t)IO(rt, 0x24 + 0x10 * k);
    unsigned size = 1, wait = 0;
    uint16_t held = CLEAR;
    if (IO(rt, 0x08 + 2 * n) & 0x40) {  /* mosaic: from the group's first line */
        uint16_t mosaic = IO(rt, 0x4C);
        int back = y % (int)(((mosaic >> 4) & 15) + 1);
        x -= back * (int16_t)IO(rt, 0x22 + 0x10 * k);  /* PB */
        v -= back * (int16_t)IO(rt, 0x26 + 0x10 * k);  /* PD */
        size = (mosaic & 15) + 1u;
    }
    for (int i = 0; i < W; i++, x += dx, v += dy) {
        if (wait) {
            wait--;
            out[i] = held;
            continue;
        }
        int outside;
        out[i] = texel(rt, n, mode, x >> 8, v >> 8, &outside);
        if (!outside) {  /* a group that starts outside starts again at the next pixel */
            held = out[i];
            wait = size - 1;
        }
```

In `src/gbaport/runtime/render.c`, replace:
```c

/* One sprite's part of line y (in_y: the line within its box). */
static void sprite_line(const GbaRuntime *rt, const uint8_t *entry, int in_y, Layers *layers)
{
```
with:
```c

/* One sprite's part of line y (in_y: the line within its box; group: its mosaic's width). */
static void sprite_line(const GbaRuntime *rt, const uint8_t *entry, int in_y, int group,
                        Layers *layers)
{
```

In `src/gbaport/runtime/render.c`, replace:
```c
    }
    for (int x = left < 0 ? 0 : left; x < left + box_w && x < W; x++) {
        int tx = x - left, ty = in_y;
        if (affine) {
            int32_t cx = tx - box_w / 2, cy = in_y - box_h / 2;
            tx = (pa * cx + pb * cy + (width << 7)) >> 8;
            ty = (pc * cx + pd * cy + (height << 7)) >> 8;
            if (tx < 0 || ty < 0 || tx >= width || ty >= height)
                continue;
        } else {
            if (a1 & 0x1000)
```
with:
```c
    }
    int right = left + box_w;
    if (group > 1 && right < W && right % group)
        right += group - right % group;  /* mosaic: on to the end of the last group */
    int first = left < 0 ? 0 : left;
    int32_t cy = in_y - box_h / 2, cx = first - 1 - left - box_w / 2;
    int held_x = (pa * cx + pb * cy + (width << 7)) >> 8;  /* a rotating sprite's sample */
    int held_y = (pc * cx + pd * cy + (height << 7)) >> 8;
    for (int x = first; x < right && x < W; x++) {
        int tx, ty = in_y;
        if (affine) {
            if (x % group == 0) {  /* every group samples where it starts */
                cx = x - left - box_w / 2;
                held_x = (pa * cx + pb * cy + (width << 7)) >> 8;
                held_y = (pc * cx + pd * cy + (height << 7)) >> 8;
            }
            tx = held_x;
            ty = held_y;
            if (tx < 0 || ty < 0 || tx >= width || ty >= height)
                continue;
        } else {
            tx = x - x % group - left;
            if (a1 & 0x1000)
```

In `src/gbaport/runtime/render.c`, replace:
```c
                ty = height - 1 - ty;
        }
```
with:
```c
                ty = height - 1 - ty;
            tx = tx < 0 ? 0 : tx >= width ? width - 1 : tx;  /* mosaic past the edges */
        }
```

In `src/gbaport/runtime/render.c`, replace:
```c
    int time = IO(rt, GBA_REG_DISPCNT) & 0x20 ? 954 : 1210;
    for (int i = 0; i < 128; i++) {
```
with:
```c
    int time = IO(rt, GBA_REG_DISPCNT) & 0x20 ? 954 : 1210;
    uint16_t mosaic = IO(rt, 0x4C);
    int group_w = ((mosaic >> 8) & 15) + 1, group_h = ((mosaic >> 12) & 15) + 1;
    for (int i = 0; i < 128; i++) {
```

In `src/gbaport/runtime/render.c`, replace:
```c
            continue;  /* not on this line */
        int in_y = y - top;
        if (affine ? in_y < 0 : top + height >= 256)
            in_y += 256;  /* the sprite wraps past line 255 */
        sprite_line(rt, entry, in_y, layers);
        time -= affine ? 10 + box_w * 2 : width;
```
with:
```c
            continue;  /* not on this line */
        int line = y, mosaic_on = a0 & 0x1000;
        if (mosaic_on && group_h > 1) {  /* the group's first line that is inside the sprite */
            line = y - y % group_h;
            if (line < top && top < H)
                line = top;
            if (line >= (bottom & 0xFF))
                line = bottom - 1;
        }
        int in_y = line - top;
        if (affine ? in_y < 0 : top + height >= 256)
            in_y += 256;  /* the sprite wraps past line 255 */
        sprite_line(rt, entry, in_y, mosaic_on ? group_w : 1, layers);
        time -= affine ? 10 + box_w * 2 : width;
```

In `src/gbaport/runtime/render.c`, replace:
```c
    for (int n = 2; n < 4; n++) {
        int affine = (mode == 1 && n == 2) || mode == 2;
        if (affine && (control & (0x100u << n))) {
            affine_line(rt, n, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
    if (mode >= 3 && mode <= 5 && (control & 0x400)) {
        bitmap_line(rt, layers.bg[2], mode);
        enabled |= 1u << 2;
    }
```
with:
```c
    for (int n = 2; n < 4; n++) {
        int affine = (mode == 1 && n == 2) || mode == 2 || (mode >= 3 && mode <= 5 && n == 2);
        if (affine && (control & (0x100u << n))) {
            affine_line(rt, n, y, mode, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 689 passed (680 + 9).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/render.c tests/runtime/test_render_mosaic.py tests/runtime/test_render_speed.py
git commit -m "feat: mosaic for backgrounds and sprites; a busy picture matches mGBA at full speed"
```

---

### Task 9: README, spec, and the user's game on screen

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
`gbaport-romcache`. They also download and run jsmolka's CPU test ROMs (MIT licence;
`tests/publicroms/jsmolka` has their configs), so the first run needs a network
connection. The window tests build SDL3 the first time (see below) and run with SDL's
dummy video driver, so no window opens.

## Commands
```
with:
```markdown
The runtime tests build small GBA test ROMs from C (`tests/gbaroms`) with clang and
ld.lld, recompile them and run them natively; ROMs and builds are cached in
`gbaport-romcache`. They also download and run jsmolka's CPU and PPU test ROMs (MIT
licence; `tests/publicroms/jsmolka` has their configs), so the first run needs a network
connection. The window tests build SDL3 the first time (see below) and run with SDL's
dummy video driver, so no window opens.

The renderer tests compare every picture, pixel for pixel, with mGBA's: they build mGBA
0.10.5's GBA core (MPL-2.0, a development tool only; nothing ships it) from source the
first time, with the same CMake, Ninja and clang as SDL3, into the same cache folder. A
picture that differs is written next to mGBA's in `gbaport-romcache/pictures`, and the
test's message names the file.

## Commands
```

In `README.md`, replace:
```markdown
works too: its right face button is A, the bottom one B. The game runs at the GBA's 59.73
frames a second (`--fast`: as fast as it can), and the picture grows with the window by
whole steps (`--scale`: the starting size, 3 by default). Until the renderer arrives
(Plan 5) only the bitmap modes are drawn; a game that draws with tiles shows its backdrop
colour. Closing the window ends the run.

The first build also builds SDL3 3.4.18 from source, once, into `%LOCALAPPDATA%\gbaport`
```
with:
```markdown
works too: its right face button is A, the bottom one B. The game runs at the GBA's 59.73
frames a second (`--fast`: as fast as it can), and the picture grows with the window by
whole steps (`--scale`: the starting size, 3 by default). The renderer draws every
line as the GBA does (tiled, rotating and bitmap backgrounds, sprites, windows, blending,
mosaic) from the registers as they are at the end of that line, so effects that change
them between lines work. Closing the window ends the run.

The first build also builds SDL3 3.4.18 from source, once, into `%LOCALAPPDATA%\gbaport`
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.

## Risks
```
with:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
- mGBA 0.10.5's GBA core, built from source by the tests (16-bit colour, no dependencies)
  as the renderer's reference — Plan 5.

## Risks
```

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest`
Expected: 689 passed.

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 3: Smoke-test the user's game**

Run, from the repo root:

```bash
uv run python -m gbaport.cli build roms/mygame.gba --out build/bt4e-headless --host headless
build/bt4e-headless/build/BT4E-headless.exe roms/mygame.gba --frames 120 --screenshot build/bt4e-headless/frame120.bmp; echo "exit $?"
uv run python -c "
import sys; sys.path[:0] = ['tests']
from pathlib import Path
from mgbaref import mgba_picture
from rendertest import gba_colour
from romtest import read_bmp
ours = [gba_colour(p) for p in read_bmp(Path('build/bt4e-headless/frame120.bmp'))]
reference = mgba_picture(Path('roms/mygame.gba').read_bytes(), 120)
print(sum(a != b for a, b in zip(ours, reference)), 'pixels differ from mGBA at frame 120')
"
uv run python -m gbaport.cli build roms/mygame.gba --out build/bt4e
build/bt4e/build/BT4E.exe roms/mygame.gba --frames 600 --save build/bt4e/bt4e.sav; echo "exit $?"
```

Expected (validated before this plan was approved):
- **Headless build:** `config games\BT4E\game.toml`, `functions 577`, `lift issues 0`, then `built build\bt4e-headless\build\BT4E-headless.exe`.
- **Frame 120:** `stopped after 120 frames`, exit 4, and `0 pixels differ from mGBA at frame 120`.
- **In a real window**, shown on the desktop for about ten seconds: the game's own pictures, tiles and sprites, where Plan 4c showed only the backdrop colour. It closes by itself with `stopped after 600 frames` and exit 4. Later frames can differ from mGBA's in timing (Known limitations).
- `build/` is ignored by git. The screenshot and the save stay on this machine.

Record the numbers in the ledger.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: the renderer, and mGBA as the tests' reference picture"
```

---

## Done criteria for Plan 5

- `uv run pytest` passes 689 tests and `uv run ruff check src tests` is clean.
- **Every renderer feature matches mGBA pixel for pixel** on the tests' scenes:
  - modes 0-5, and the modes that do not exist;
  - text and rotation/scaling backgrounds;
  - sprites, with their sizes, colours, tile layouts, matrices, priorities and line time;
  - WIN0, WIN1, the OBJ window and WINOUT;
  - alpha blending, brightening, darkening and semi-transparent sprites;
  - mosaic.
- **Raster effects work:** HBlank DMA writing a scroll register or a colour, a reference point written between lines, and a mode switch from a VCOUNT interrupt.
- **jsmolka's PPU test ROMs** `hello`, `shades` and `stripes` match mGBA.
- **A busy picture** with every feature at once matches mGBA and is drawn faster than the GBA shows it.
- **The user's game** shows its pictures, and frame 120 is the same as mGBA's.
