# Plan 7a: Lockstep with mGBA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gbaport verify` plays a game natively and in mGBA, from power-on with the same input file, and compares their pictures frame by frame. To make that comparison meaningful, the runtime counts cycles the way mGBA counts them, so the user's game reaches each picture when mGBA does, give or take a frame.

**Architecture:**
- **Plan 7 in two.** The spec's P7 is "first game on desktop + lockstep harness". This plan, 7a, builds the harness and the timing it needs. Plan 7b takes the user's game from the title screen to its first fight: a trace recorder driven by mGBA, returns that unwind past calls (the game switches between tasks), and an input file that plays the way in.
- **mGBA as a gbaport tool.** The tests' `mgbaref` becomes `gbaport.native.mgba`, built the same way into the cache folder. Its program, `gbaport-mgba`, holds the keys an input file names, and writes a hash of every frame's picture. `tests/mgbaref.py` keeps its helpers on top of it.
- **Input files.** `gbaport/inputs.py`: a line each time the keys change (`900 A`, `906 none`). Both hosts read them with `--input FILE`, and the 64-press cap goes. With `--hashes PATH` the hosts write the same hashes as mGBA.
- **`gbaport verify`.**
  - It builds the game's headless program and plays it and mGBA for N frames.
  - It walks the two sequences of pictures (runs of equal frames) side by side. A picture may come up to `--slack` frames early or late, and a picture only one of them shows may last that long.
  - Otherwise it names the frame where they part and writes both pictures there to a PNG file.
- **Timing as mGBA counts it.** Up to now each block added a rough estimate. Now:
  - The lifter costs each instruction as mGBA's ARM core does: the fetch of the next instruction at the wait states of the code's memory, plus internal cycles.
  - The runtime keeps mGBA's wait-state tables in `GbaCtx`, rebuilt from WAITCNT.
  - Static costs are added in pieces, just before each memory access, so a timer or VCOUNT read sees exactly the cycles before it.
  - Data accesses, multiplies and jumps add their waits where they happen. Data accesses go through mGBA's model of the cartridge's prefetch buffer.
  - An interrupt's entry and exit cost what mGBA's BIOS stand-in takes. A pending interrupt is taken as soon as the CPSR's I bit clears.
- **DMA and the EEPROM.** DMA costs 3 cycles to start, then each unit costs its waits. The EEPROM is busy for 115000 cycles after writing a block.
- **Checked against mGBA directly.** A test ROM times kinds of code with timer 0 under four WAITCNT settings and draws the counts as pixels. The tests read mGBA's counts from its picture and the runtime's from its own, and they must be equal.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime built with clang 23; mGBA 0.10.5 (MPL-2.0), built from source with CMake and Ninja as Plans 5 and 6 did.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Roadmap row P7, verbatim: "P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6". This plan delivers `gbaport verify` and the replay; Plan 7b delivers the gameplay.
  - Verification strategy, verbatim: "Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences". This plan compares pictures; RAM is in Known limitations.
  - "Emulators are dev-time test oracles only." mGBA is built by gbaport for development and the tests, and never linked into a game. Where mGBA takes a shortcut the GBA does not take, the runtime follows the GBA and says so (Known limitations).
  - "No ROM-derived bytes in git." Test ROMs are built at test time; input files hold key names and frame numbers only.
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Never commit a `.gba` file: the user's ROMs stay untracked.
  - Tests never open a window and never play sound.
- **Commands:**
  - Use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher.
  - Run `uv run pytest` and `uv run ruff check src tests` as separate commands.
  - mGBA's program is built again after Task 1 (its source moves), which takes a minute or two. Every test program is built again after Tasks 4 and 5 (the runtime changes), which can take several minutes.

## Review Focus

1. **Input files written by a Windows editor.** Notepad may save a UTF-8 byte order mark and CRLF line ends; the file reads like any other, in Python, in mGBA's program and in the hosts. Pinned in Task 1 (`test_an_input_file_saved_by_a_windows_editor_reads_the_same`, `test_mgba_takes_any_file_names_and_an_input_file_from_a_windows_editor`) and Task 2 (`test_an_input_file_from_a_windows_editor_plays_the_same`).
2. **Paths outside the ANSI code page.** A ROM or input file in a folder named with any characters reaches mGBA's program intact, as it reaches the hosts. Pinned in Task 1 (`test_mgba_takes_any_file_names_and_an_input_file_from_a_windows_editor`).
3. **A long replay that parts early.** `gbaport verify --frames 216000` on a game that goes its own way at frame 2 answers at once, not after quadratic work. Pinned in Task 3 (`test_a_long_replay_that_parts_early_is_compared_at_once`).
4. **A game that stops itself before the last frame.** BIOS Stop with nothing to wake it: verify says so and does not claim the frames it never compared. Pinned in Task 3 (`test_verify_says_when_the_game_stopped_itself`).
5. **Interrupt-heavy code.** An interrupt at every HBlank slows the CPU as much as in mGBA, within 4 cycles an interrupt. Pinned in Task 4 (`test_an_hblank_interrupt_slows_the_cpu_about_as_much_as_in_mgba`).

## Known limitations (deliberate; later plans)

- **When an interrupt comes in.** Recompiled code checks for interrupts at loop heads and function returns, not after every instruction, so an interrupt can run a few dozen cycles later than in mGBA. Most pictures still come on the same frame, but some come a frame early or late. That is `gbaport verify`'s `--slack` (1 frame by default). On the user's game, every picture matches from frame 45 to frame 862; with `--slack 0` the two part at frame 863.
- **Differences with mGBA kept small and tested:**
  - An interrupt's entry and exit cost 27 cycles plus the jump back, taken to be to Thumb code in the cartridge. That is mGBA's BIOS stand-in counted instruction by instruction. mGBA measures about 3 cycles more an interrupt; the cause is not found.
  - mGBA starts a DMA 3 cycles after it is asked for and lets the CPU run on until then. Here the CPU waits those 3 cycles at once, so a transfer ends a cycle or two later.
- **BIOS calls** take the runtime's own estimates. mGBA runs its BIOS stand-in's code, which takes 2-3 times as long for Div and CpuSet. The user's game calls Div about once a frame, so this is under 0.1% of a frame.
- **Flash** erases and programs instantly. mGBA makes a byte take 650 cycles and a sector 30000, reading 0x5F meanwhile. With that, it fails jsmolka's Flash tests, which the real chip and this runtime pass.
- **The sound FIFOs' DMA** is not charged to the CPU (Plan 6), 0.1-0.3% of its time.
- **RAM.** `gbaport verify` compares pictures, not RAM. A picture that moves by a frame leaves harmless differences in RAM (stack contents, sound buffers), so a RAM comparison needs timing exact to the cycle.
- **mGBA's redrawing.** mGBA redraws only the scanlines something changed for. A game that changes nothing for a while after power-on may keep a few white lines of the start-up frame in mGBA, and verify would report them. The tests' `input_echo` ROM writes a changing colour to avoid this.
- **The first frame** is left out of every comparison: the game starts in line 126, halfway down it.

---

### Task 1: mGBA as a gbaport tool, and input files

The tests' `mgbaref` program moves into the package as `gbaport.native.mgba`, so `gbaport verify` can build and run it too. Its program, `gbaport-mgba`, takes options instead of positions. It plays an input file and writes a hash of every frame's picture. `tests/mgbaref.py` keeps `mgba_picture` and `mgba_sound` on top of it. Input files get a Python module, `gbaport/inputs.py`.

**Files:**
- Create: `src/gbaport/inputs.py`
- Create: `src/gbaport/native/mgba.py`, `src/gbaport/native/mgba_oracle/mgba.c`, `src/gbaport/native/mgba_oracle/CMakeLists.txt`
- Delete: `tests/mgbaref/mgbaref.c`, `tests/mgbaref/CMakeLists.txt`
- Modify: `tests/mgbaref.py`
- Create: `tests/gbaroms/input_echo.c`
- Test: `tests/test_inputs.py`, `tests/test_mgba.py`

**Interfaces:**
- Consumes: Plan 5's mgbaref build (`gbaport.native.sdl3.cache_folder`, `gbaport.native.build.SALTED_REBUILDS`, `_starts`, `gbaport.native.toolchain`); `romtest.build_test_rom`; testlib's `wait_vcount`.
- **Produces:**
  - **`gbaport/inputs.py`:** `KEY_NAMES`, `InputError(ValueError)`, `Press(frame: int, keys: int)` with `names()`, `keys_from_names(text) -> int`, `parse_input(text, source="input") -> list[Press]`, `format_input(presses) -> str`, `load_input(path) -> list[Press]`.
  - **`gbaport/native/mgba.py`:**
    - `MGBA_VERSION`, `MGBA_URL`, `MGBA_SHA256`, `SOURCE`, `MgbaError(RuntimeError)`.
    - `mgba_program(log=print) -> Path`.
    - `run_mgba(rom, frames, *, input=None, picture=None, sound=None, hashes=None, log=print) -> None`.
  - **`gbaport-mgba ROM --frames N [--input FILE] [--picture PATH] [--sound PATH] [--hashes PATH]`:** the picture and sound as `mgbaref` wrote them. The hashes are a line a frame: 16 hex digits of the 64-bit FNV-1a hash of the picture's colours, two bytes each, low byte first (bit 15 dropped).
  - **`tests/mgbaref.py`:** `mgba_picture(rom, frames, input=None)`, `mgba_sound(rom, frames)`.
  - **`input_echo.c`:** at each VBlank the backdrop becomes the keys held (KEYINPUT's pressed bits), so the next picture shows them.
  - **`test_mgba.py`:** `INPUT` and `picture_hash(colours) -> str`, which Tasks 2 and 3 use.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-07a-lockstep
```

- [ ] **Step 2: Write the failing tests and the test ROM**

Create `tests/gbaroms/input_echo.c`:
```c
/* Shows the keys held: at each VBlank the backdrop colour becomes KEYINPUT's pressed bits
 * (a held key sets its bit), so the next picture tells which keys the game saw. */
#include "testlib.h"

#define BACKDROP MEM16(0x05000000)

int main(void)
{
    REG_DISPCNT = 0;  /* mode 0, no layers: the whole picture is the backdrop */
    for (unsigned frame = 0;; frame++) {
        wait_vcount(160);
        /* Bit 15 does not show, but a colour that changes has mGBA draw every line again:
         * it keeps lines nothing has changed for (the start-up picture's white ones). */
        BACKDROP = (~REG_KEYINPUT & 0x3FF) | (~frame & 1) << 15;
        wait_vcount(161);
    }
}
```

Create `tests/test_inputs.py`:
```python
"""Input files (gbaport/inputs.py): the keys held, frame by frame."""

import pytest

from gbaport.inputs import (
    InputError,
    Press,
    format_input,
    keys_from_names,
    load_input,
    parse_input,
)

TEXT = """\
# the title screen, then the menu
900 A
906 none

3900 RIGHT+A   # walk and hit
"""


def test_an_input_file_holds_its_keys_from_each_frame_on():
    assert parse_input(TEXT) == [Press(900, 0x001), Press(906, 0), Press(3900, 0x011)]


def test_an_input_file_reads_back_as_written():
    presses = parse_input(TEXT)
    assert format_input(presses) == "900 A\n906 none\n3900 A+RIGHT\n"
    assert parse_input(format_input(presses)) == presses


def test_key_names_are_the_hosts():
    assert keys_from_names("A+B+SELECT+START+RIGHT+LEFT+UP+DOWN+R+L") == 0x3FF
    assert keys_from_names("none") == 0


@pytest.mark.parametrize(("text", "message"), [
    ("900 A\nhello\n", "game.input, line 2: expected 'FRAME KEYS', got 'hello'"),
    ("900 A\n10 B\n", "game.input, line 2: frame 10 comes before frame 900"),
    ("900 JUMP\n", "game.input, line 1: unknown key 'JUMP'"),
    ("-5 A\n", "game.input, line 1: expected 'FRAME KEYS', got '-5 A'"),
])
def test_a_bad_input_file_says_which_line(text, message):
    with pytest.raises(InputError, match="^" + message.replace("(", r"\(").replace(")", r"\)")):
        parse_input(text, "game.input")


def test_an_input_file_saved_by_a_windows_editor_reads_the_same(tmp_path):
    """A UTF-8 byte order mark and CRLF line ends, as Notepad may write them."""
    path = tmp_path / "game.input"
    path.write_bytes(b"\xef\xbb\xbf# the title\r\n900 A\r\n906 none\r\n")
    assert load_input(path) == [Press(900, 0x001), Press(906, 0)]
```

Create `tests/test_mgba.py`:
```python
"""mGBA as gbaport's reference (gbaport/native/mgba.py): it plays a ROM with the keys an
input file names and writes a hash of each frame's picture."""

import pytest
from mgbaref import mgba_picture
from romtest import build_test_rom

from gbaport.native.mgba import MgbaError, run_mgba

INPUT = "0 none\n10 A\n20 B+UP\n30 none\n"


def picture_hash(colours: list[int]) -> str:
    """A picture's FNV-1a hash, as gbaport-mgba and the hosts write it."""
    h = 0xCBF29CE484222325
    for colour in colours:
        for byte in (colour & 0xFF, colour >> 8 & 0x7F):
            h = (h ^ byte) * 0x100000001B3 & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def echo(tmp_path):
    rom, path = build_test_rom("input_echo"), tmp_path / "echo.gba"
    path.write_bytes(rom.data)
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    return rom, path


def test_mgba_holds_the_keys_the_input_file_names(tmp_path):
    rom, _ = echo(tmp_path)
    # keys held from the 10th VBlank on are read at it and drawn in the picture after it
    assert set(mgba_picture(rom.data, 15, INPUT)) == {0x0001}  # A
    assert set(mgba_picture(rom.data, 25, INPUT)) == {0x0042}  # B, UP
    assert set(mgba_picture(rom.data, 35, INPUT)) == {0x0000}


def test_mgba_writes_a_hash_of_each_frames_picture(tmp_path):
    _, path = echo(tmp_path)
    run_mgba(path, 40, input=tmp_path / "game.input", hashes=tmp_path / "mgba.hashes")
    hashes = (tmp_path / "mgba.hashes").read_text(encoding="utf-8").split("\n")
    black, a, b_up = (picture_hash([colour] * 38400) for colour in (0, 0x0001, 0x0042))
    # a line a frame; the first is the start-up frame, which begins in line 126
    assert hashes[1:] == [black] * 9 + [a] * 10 + [b_up] * 10 + [black] * 10 + [""]


def test_a_bad_input_file_stops_mgba_with_its_line(tmp_path):
    _, path = echo(tmp_path)
    (tmp_path / "bad.input").write_text("10 A\n5 B\n", encoding="utf-8")
    with pytest.raises(MgbaError, match=r"exit status 2\): error: .*bad\.input, line 2"):
        run_mgba(path, 10, input=tmp_path / "bad.input")


def test_mgba_takes_any_file_names_and_an_input_file_from_a_windows_editor(tmp_path):
    """Paths outside the ANSI code page (Windows hands them to programs in UTF-16), and an
    input file with a UTF-8 byte order mark and CRLF line ends."""
    folder = tmp_path / "jeu-é-ゲーム"
    folder.mkdir()
    rom = build_test_rom("input_echo")
    (folder / "echo.gba").write_bytes(rom.data)
    (folder / "game.input").write_bytes(b"\xef\xbb\xbf0 none\r\n10 B\r\n")
    run_mgba(folder / "echo.gba", 15, input=folder / "game.input", picture=folder / "p.raw",
             hashes=folder / "h.hashes")
    assert (folder / "h.hashes").read_text(encoding="utf-8").split()[-1] == \
        picture_hash([0x0002] * 38400)
    assert (folder / "p.raw").stat().st_size == 2 * 38400
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_inputs.py tests/test_mgba.py`
Expected: FAIL — 2 errors: `ModuleNotFoundError: No module named 'gbaport.inputs'` (test_inputs.py) and `ModuleNotFoundError: No module named 'gbaport.native.mgba'` (test_mgba.py).

- [ ] **Step 4: Input files, and mGBA as gbaport's reference**

Create `src/gbaport/inputs.py`:
```python
"""Input files: the keys a game is played with, frame by frame.

An input file is text with one change of the keys held per line, so the same play can be
replayed by mGBA and by the native build::

    # comments and blank lines are ignored
    900 A
    906 none
    3900 RIGHT+A

``FRAME KEYS`` holds KEYS from the FRAME-th VBlank on, until the next line: names joined
with ``+`` (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or ``none``. Frames never
go down. The hosts' ``--press FRAME:KEYS`` options mean the same.
"""

from dataclasses import dataclass
from pathlib import Path

KEY_NAMES = ("A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L")


class InputError(ValueError):
    """An input file that is not one."""


@dataclass(frozen=True)
class Press:
    frame: int
    keys: int  # KEYINPUT bits that are held (1 = pressed)

    def names(self) -> str:
        held = [name for bit, name in enumerate(KEY_NAMES) if self.keys >> bit & 1]
        return "+".join(held) or "none"


def keys_from_names(text: str) -> int:
    """``A+START`` -> the KEYINPUT bits; ``none`` -> 0. Raises ``ValueError``."""
    if text == "none":
        return 0
    keys = 0
    for name in text.split("+"):
        if name not in KEY_NAMES:
            raise ValueError(f"unknown key {name!r} (keys: {', '.join(KEY_NAMES)}, or none)")
        keys |= 1 << KEY_NAMES.index(name)
    return keys


def parse_input(text: str, source: str = "input") -> list[Press]:
    presses: list[Press] = []
    for number, line in enumerate(text.removeprefix("\ufeff").splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2 or not fields[0].isdigit():
            raise InputError(f"{source}, line {number}: expected 'FRAME KEYS', got {line!r}")
        try:
            keys = keys_from_names(fields[1])
        except ValueError as error:
            raise InputError(f"{source}, line {number}: {error}") from None
        frame = int(fields[0])
        if presses and frame < presses[-1].frame:
            raise InputError(f"{source}, line {number}: frame {frame} comes before frame "
                             f"{presses[-1].frame}")
        presses.append(Press(frame, keys))
    return presses


def format_input(presses: list[Press]) -> str:
    return "".join(f"{press.frame} {press.names()}\n" for press in presses)


def load_input(path: str | Path) -> list[Press]:
    return parse_input(Path(path).read_text(encoding="utf-8"), str(path))
```

Create `src/gbaport/native/mgba.py`:
```python
"""mGBA as gbaport's reference: the tests and ``gbaport verify`` compare with it.

mGBA's GBA core is the spec's development-time oracle (MPL-2.0; no game ships it). The
pinned source release is downloaded once (its SHA-256 checked) and built with CMake, Ninja
and clang, together with ``mgba_oracle/mgba.c``, into the cache folder next to SDL3 (see
``sdl3.cache_folder``); a change to ``mgba_oracle`` builds it again. A program Windows
refuses to start is linked again with a new ``salt.c``, like every program gbaport builds.
"""

import hashlib
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.sdl3 import cache_folder
from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

MGBA_VERSION = "0.10.5"
MGBA_URL = f"https://github.com/mgba-emu/mgba/archive/refs/tags/{MGBA_VERSION}.tar.gz"
MGBA_SHA256 = "91d6fbd32abcbdf030d58d3f562de25ebbc9d56040d513ff8e5c19bee9dacf14"
SOURCE = Path(__file__).parent / "mgba_oracle"
SOURCE_FILES = ("CMakeLists.txt", "mgba.c")


class MgbaError(RuntimeError):
    """mGBA could not run the ROM as asked."""


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
        raise ToolchainError(f"building mGBA failed ({what}):\n{output}")


def mgba_program(log: Callable[[str], None] = print) -> Path:
    """The reference program, building it first if it is not there yet (again when its
    sources change)."""
    digest = hashlib.sha1(b"".join((SOURCE / name).read_bytes() for name in SOURCE_FILES))
    folder = cache_folder() / f"mgba-{MGBA_VERSION}-{digest.hexdigest()[:8]}"
    program = folder / ("gbaport-mgba.exe" if os.name == "nt" else "gbaport-mgba")
    if (folder / "started").exists():  # written once Windows let it start
        return program
    log(f"building mGBA {MGBA_VERSION} into {folder} (once; it takes a few minutes)")
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
    salt.write_text('const char mgba_salt[] = "";\n', encoding="utf-8")
    _run(configure, "configure")
    for _ in range(native.SALTED_REBUILDS + 1):
        salt.write_text(f'const char mgba_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _run([cmake, "--build", str(folder)], "build")
        if native._starts(program):
            (folder / "started").write_text("", encoding="utf-8")
            return program
    raise ToolchainError(f"Windows refused to start {program} after {native.SALTED_REBUILDS} rebuilds")


def run_mgba(rom: Path, frames: int, *, input: Path | None = None, picture: Path | None = None,
             sound: Path | None = None, hashes: Path | None = None,
             log: Callable[[str], None] = print) -> None:
    """Runs ``rom`` in mGBA for ``frames`` frames and writes what was asked for (see
    ``mgba_oracle/mgba.c``)."""
    command = [str(mgba_program(log)), str(rom), "--frames", str(frames)]
    for option, path in (("--input", input), ("--picture", picture), ("--sound", sound),
                         ("--hashes", hashes)):
        if path is not None:
            command += [option, str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if result.returncode != 0:
        raise MgbaError(f"mGBA failed (exit status {result.returncode}): {result.stderr.strip()}")
```

Create `src/gbaport/native/mgba_oracle/CMakeLists.txt`:
```cmake
# Builds mGBA's GBA core and mgba.c, gbaport's reference (gbaport/native/mgba.py runs
# this). The source release is GBAPORT_MGBA_URL (mgba.py downloads it first) and must match
# GBAPORT_MGBA_SHA256; mgba.py writes salt.c into the build folder.
cmake_minimum_required(VERSION 3.28)
project(gbaport_mgba LANGUAGES C)

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

add_executable(gbaport-mgba mgba.c "${CMAKE_BINARY_DIR}/salt.c")
target_include_directories(gbaport-mgba PRIVATE "${mgba_SOURCE_DIR}/include" "${mgba_BINARY_DIR}/include")
target_compile_definitions(gbaport-mgba PRIVATE BUILD_STATIC M_CORE_GBA)
target_link_libraries(gbaport-mgba PRIVATE mgba)
```

Create `src/gbaport/native/mgba_oracle/mgba.c`:
```c
/* mgba.c - run a ROM in mGBA: the reference the tests and `gbaport verify` compare with.
 *
 *     gbaport-mgba ROM --frames N [--input FILE] [--picture PATH] [--sound PATH]
 *                  [--hashes PATH]
 *
 * Runs N frames from power-on (mGBA's own BIOS replacement, no BIOS file), holding the keys
 * an input file names (gbaport/inputs.py: "FRAME KEYS" lines, held from the FRAME-th VBlank
 * on). Then:
 * - --picture writes the last picture as 240x160 little-endian 16-bit GBA colours
 *   (0BBBBBGGGGGRRRRR), the form the runtime's tests compare in;
 * - --sound writes every sample mGBA mixes (32768 a second, before it resamples them for
 *   playback) as little-endian 16-bit left and right values;
 * - --hashes writes one line a frame: the picture's 64-bit FNV-1a hash (over its colours
 *   as two bytes each, low byte first), as 16 hex digits, the same the hosts write.
 * mGBA is built with 16-bit colour, so it works in GBA colours throughout, blending in 5
 * bits per channel like the GBA (its partial darkening rounds differently;
 * test_render_effects.py checks that one against GBATEK's formula). mGBA's own messages
 * are dropped. Exit status: 0, or 2 for a bad command line or input file, 3 when mGBA
 * cannot start or a file cannot be read or written. Paths are UTF-8, as in the hosts:
 * Windows hands programs their arguments in UTF-16, so there they are converted, and
 * files are opened by their UTF-16 names (mGBA opens the ROM that way itself). */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>

static char *utf8(const wchar_t *text)
{
    int size = WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL);
    char *out = malloc(size > 0 ? (size_t)size : 1);
    if (out && WideCharToMultiByte(CP_UTF8, 0, text, -1, out, size, NULL, NULL) <= 0)
        out[0] = 0;
    return out;
}

static wchar_t *wide(const char *text)
{
    int size = MultiByteToWideChar(CP_UTF8, 0, text, -1, NULL, 0);
    wchar_t *out = malloc((size > 0 ? (size_t)size : 1) * sizeof *out);
    if (out && MultiByteToWideChar(CP_UTF8, 0, text, -1, out, size) <= 0)
        out[0] = 0;
    return out;
}

static FILE *open_file(const char *path, const char *mode)
{
    wchar_t *name = wide(path), *how = wide(mode);
    FILE *f = name && how ? _wfopen(name, how) : NULL;
    free(name);
    free(how);
    return f;
}

static char **utf8_arguments(int *argc, char **argv)
{
    int count;
    wchar_t **wargs = CommandLineToArgvW(GetCommandLineW(), &count);
    char **args = wargs ? malloc((size_t)(count + 1) * sizeof *args) : NULL;
    if (!args)
        return argv;
    for (int i = 0; i < count; i++)
        args[i] = utf8(wargs[i]);
    args[count] = NULL;
    LocalFree(wargs);
    *argc = count;
    return args;
}
#else
#define open_file fopen
#endif

#include <mgba/core/core.h>
#include <mgba/core/interface.h>
#include <mgba/core/log.h>
#include <mgba/gba/core.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
#error "gbaport-mgba needs mGBA built with 16-bit BGR555 colour (CMakeLists.txt sets COLOR_16_BIT)"
#endif

static FILE *sound;

static void record(struct mAVStream *stream, int16_t left, int16_t right)
{
    (void)stream;
    unsigned char bytes[4] = {left & 0xFF, (left >> 8) & 0xFF, right & 0xFF, (right >> 8) & 0xFF};
    fwrite(bytes, 1, sizeof bytes, sound);
}

static void quiet(struct mLogger *logger, int category, enum mLogLevel level, const char *format,
                  va_list args)
{
    (void)logger, (void)category, (void)level, (void)format, (void)args;
}

/* ---- input files ------------------------------------------------------------------- */

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};

typedef struct {
    long frame;
    uint32_t keys;
} Press;

static Press *presses;
static size_t press_count;

/* "A+START" or "none" into KEYINPUT bits; -1 when a name is not a key. */
static long key_bits(const char *names)
{
    if (strcmp(names, "none") == 0)
        return 0;
    long keys = 0;
    while (*names) {
        size_t n = strcspn(names, "+");
        int found = -1;
        for (int i = 0; i < 10; i++)
            if (strlen(KEY_NAMES[i]) == n && strncmp(names, KEY_NAMES[i], n) == 0)
                found = i;
        if (found < 0)
            return -1;
        keys |= 1L << found;
        names += n + (names[n] == '+');
    }
    return keys;
}

static int load_input(const char *path)
{
    FILE *f = open_file(path, "rb");
    if (!f) {
        fprintf(stderr, "error: cannot read %s\n", path);
        return 3;
    }
    char line[256];
    for (int number = 1; fgets(line, sizeof line, f); number++) {
        if (number == 1 && strncmp(line, "\xEF\xBB\xBF", 3) == 0)
            memmove(line, line + 3, strlen(line + 3) + 1);  /* a UTF-8 byte order mark */
        line[strcspn(line, "#\r\n")] = 0;
        char names[200];
        long frame;
        int fields = sscanf(line, "%ld %199s", &frame, names);
        if (fields <= 0)
            continue;  /* a blank line or a comment */
        long keys = fields == 2 ? key_bits(names) : -1;
        if (keys < 0 || frame < 0 || (press_count && frame < presses[press_count - 1].frame)) {
            fprintf(stderr, "error: %s, line %d: expected 'FRAME KEYS', frames in order\n",
                    path, number);
            fclose(f);
            return 2;
        }
        presses = realloc(presses, (press_count + 1) * sizeof *presses);
        presses[press_count++] = (Press){frame, (uint32_t)keys};
    }
    fclose(f);
    return 0;
}

/* ---- pictures ---------------------------------------------------------------------- */

static uint64_t picture_hash(const color_t *pixels, unsigned count)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (unsigned i = 0; i < count; i++) {
        h = (h ^ (pixels[i] & 0xFF)) * 0x100000001B3ull;
        h = (h ^ ((pixels[i] >> 8) & 0x7F)) * 0x100000001B3ull;
    }
    return h;
}

static FILE *open_out(const char *path)
{
    FILE *f = path ? open_file(path, "wb") : NULL;
    if (path && !f)
        fprintf(stderr, "error: cannot write %s\n", path);
    return f;
}

int main(int argc, char **argv)
{
    const char *rom = NULL, *input = NULL, *picture = NULL, *sound_path = NULL, *hashes_path = NULL;
    long frames = -1;
#ifdef _WIN32
    argv = utf8_arguments(&argc, argv);
#endif
    for (int i = 1; i < argc; i++) {
        const char *value = i + 1 < argc ? argv[i + 1] : NULL;
        if (strcmp(argv[i], "--frames") == 0 && value)
            frames = strtol(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--input") == 0 && value)
            input = argv[++i];
        else if (strcmp(argv[i], "--picture") == 0 && value)
            picture = argv[++i];
        else if (strcmp(argv[i], "--sound") == 0 && value)
            sound_path = argv[++i];
        else if (strcmp(argv[i], "--hashes") == 0 && value)
            hashes_path = argv[++i];
        else if (!rom && argv[i][0] != '-')
            rom = argv[i];
        else
            rom = NULL, i = argc;
    }
    if (!rom || frames < 0) {
        fprintf(stderr, "usage: %s ROM --frames N [--input FILE] [--picture PATH] [--sound PATH] "
                "[--hashes PATH]\n", argv[0]);
        return 2;
    }
    int status = input ? load_input(input) : 0;
    if (status)
        return status;
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
    if (!mCoreLoadFile(core, rom)) {
        fprintf(stderr, "error: mGBA cannot load %s\n", rom);
        return 3;
    }
    static struct mAVStream stream = {.postAudioFrame = record};
    FILE *hashes = open_out(hashes_path);
    sound = open_out(sound_path);
    if ((sound_path && !sound) || (hashes_path && !hashes))
        return 3;
    if (sound)
        core->setAVStream(core, &stream);
    core->reset(core);
    size_t next = 0;
    uint32_t keys = 0;
    for (long i = 0; i < frames; i++) {
        while (next < press_count && presses[next].frame <= i)
            keys = presses[next++].keys;
        core->setKeys(core, keys);
        core->runFrame(core);
        if (hashes)
            fprintf(hashes, "%016llx\n", (unsigned long long)picture_hash(pixels, width * height));
    }
    if (hashes)
        fclose(hashes);
    if (sound)
        fclose(sound);
    FILE *out = open_out(picture);
    if (picture && !out)
        return 3;
    if (out) {
        for (unsigned i = 0; i < width * height; i++) {
            fputc(pixels[i] & 0xFF, out);
            fputc((pixels[i] >> 8) & 0x7F, out);
        }
        fclose(out);
    }
    core->deinit(core);
    return 0;
}
```

Create `tests/mgbaref.py` (replacing the current version):
```python
"""mGBA as the reference picture and sound for the renderer and sound tests.

``gbaport.native.mgba`` builds mGBA's GBA core with gbaport's reference program (once, into
the cache folder) and runs it; these helpers hand it a test ROM and read back what it wrote.
"""

import struct
import tempfile
from pathlib import Path

from gbaport.native.mgba import run_mgba


def _reference(rom: bytes, frames: int, sound: bool, input: str | None) -> tuple[bytes, bytes]:
    """mGBA's picture and (with ``sound``) sound files after ``frames`` frames, holding the
    keys ``input`` (an input file's text) names."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        rom_path, picture, sound_path = folder / "game.gba", folder / "picture.raw", folder / "sound.raw"
        rom_path.write_bytes(rom)
        input_path = None
        if input is not None:
            input_path = folder / "input.txt"
            input_path.write_text(input, encoding="utf-8")
        run_mgba(rom_path, frames, input=input_path, picture=picture,
                 sound=sound_path if sound else None, log=lambda line: None)
        return picture.read_bytes(), sound_path.read_bytes() if sound else b""


def mgba_picture(rom: bytes, frames: int, input: str | None = None) -> list[int]:
    """mGBA's picture after ``frames`` frames: 240x160 GBA colours (0BBBBBGGGGGRRRRR),
    top row first."""
    return list(struct.unpack("<38400H", _reference(rom, frames, False, input)[0]))


def mgba_sound(rom: bytes, frames: int) -> list[tuple[int, int]]:
    """The samples mGBA mixes in ``frames`` frames, 32768 a second: (left, right) pairs of
    signed 16-bit values, before mGBA resamples them for playback."""
    data = _reference(rom, frames, True, None)[1][8:]  # mGBA's first 2 come before any
    values = struct.unpack(f"<{len(data) // 2}h", data)      # sound: its mixer starts late
    return list(zip(values[0::2], values[1::2], strict=True))
```

Delete `tests/mgbaref/CMakeLists.txt`:
```bash
git rm tests/mgbaref/CMakeLists.txt
```

Delete `tests/mgbaref/mgbaref.c`:
```bash
git rm tests/mgbaref/mgbaref.c
```

- [ ] **Step 5: Run the whole suite**

The first test that needs mGBA builds `gbaport-mgba` (its source moved), which takes a minute or two.

Run: `uv run pytest`
Expected: 755 passed (743 + 12).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/inputs.py src/gbaport/native tests/mgbaref.py tests/gbaroms/input_echo.c tests/test_inputs.py tests/test_mgba.py
git commit -m "feat: mGBA as a gbaport tool that plays input files and hashes each frame's picture"
```

---

### Task 2: The hosts play input files and hash their pictures

Both hosts take `--input FILE`: any number of key changes, read by the same rules as mGBA's program. The fixed list of 64 presses gives way to one that grows. `--hashes PATH` writes each frame's picture hash, exactly as `gbaport-mgba` writes it.

**Files:**
- Modify: `src/gbaport/runtime/host_common.c`, `host_common.h`, `host_headless.c`, `host_sdl.c` (usage comments)
- Test: `tests/runtime/test_input_files.py`

**Interfaces:**
- Consumes: `run_mgba`, `INPUT`, `picture_hash`, `input_echo` (Task 1); `romtest.run_rom`.
- **Produces:**
  - **The hosts' options:** `--input FILE` and `--hashes PATH`, next to `--press`.
  - **`host_common.h`:** `HostOptions` gains `hashes`, `hashes_file`, and `presses` as a growing list (`press_capacity`); `uint64_t host_picture_hash(const GbaRuntime *rt)`.
  - A bad input file prints `error: FILE, line N: expected 'FRAME KEYS', frames in order`, and the host exits with status 2.

- [ ] **Step 1: Write the failing test**

Create `tests/runtime/test_input_files.py`:
```python
"""The hosts play an input file (--input) and write each frame's picture hash (--hashes),
as gbaport-mgba does: the same keys give the same pictures, frame for frame."""

import pytest
from romtest import build_test_rom, run_rom
from test_mgba import INPUT, picture_hash

from gbaport.native.mgba import run_mgba


@pytest.mark.parametrize("host", ["headless", "sdl"])
def test_the_hosts_show_what_mgba_shows_for_an_input_file(tmp_path, host):
    rom = build_test_rom("input_echo")
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    (tmp_path / "echo.gba").write_bytes(rom.data)
    run = run_rom(rom, frames=40, host=host, args=(
        "--input", str(tmp_path / "game.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    run_mgba(tmp_path / "echo.gba", 40, input=tmp_path / "game.input",
             hashes=tmp_path / "mgba.hashes")
    ours = (tmp_path / "ours.hashes").read_text(encoding="utf-8").split("\n")
    mgba = (tmp_path / "mgba.hashes").read_text(encoding="utf-8").split("\n")
    assert len(ours) == len(mgba) == 41
    assert ours[1:] == mgba[1:]  # (the start-up frame begins in line 126)


def test_an_input_file_holds_more_presses_than_a_command_line_could(tmp_path):
    presses = "".join(f"{frame} {'A' if frame % 2 else 'B'}\n" for frame in range(10, 210))
    (tmp_path / "many.input").write_text(presses + "210 UP+L\n", encoding="utf-8")
    run = run_rom(build_test_rom("input_echo"), frames=215, args=(
        "--input", str(tmp_path / "many.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    hashes = (tmp_path / "ours.hashes").read_text(encoding="utf-8").split()
    assert len(hashes) == 215
    # line k is the picture drawn after VBlank k, with the keys held from that VBlank on
    assert hashes[101] == picture_hash([0x0001] * 38400)  # A: frame 101 is odd
    assert hashes[-1] == picture_hash([0x0240] * 38400)  # UP, L


def test_a_bad_input_file_stops_the_host_with_its_line(tmp_path):
    (tmp_path / "bad.input").write_text("# fine\n10 A\n10 JUMP\n", encoding="utf-8")
    run = run_rom(build_test_rom("input_echo"), frames=20, args=(
        "--input", str(tmp_path / "bad.input")))
    assert run.status == 2
    assert "bad.input, line 3: expected 'FRAME KEYS', frames in order" in run.stderr


def test_an_input_file_from_a_windows_editor_plays_the_same(tmp_path):
    """A UTF-8 byte order mark and CRLF line ends, as Notepad may write them."""
    (tmp_path / "game.input").write_bytes(b"\xef\xbb\xbf# keys\r\n0 none\r\n10 R\r\n")
    run = run_rom(build_test_rom("input_echo"), frames=15, args=(
        "--input", str(tmp_path / "game.input"), "--hashes", str(tmp_path / "ours.hashes")))
    assert run.status == 4, run.stderr
    assert (tmp_path / "ours.hashes").read_text(encoding="utf-8").split()[-1] == \
        picture_hash([0x0100] * 38400)  # R
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_input_files.py`
Expected: FAIL — 5 failed: the hosts do not know `--input` yet, so each run ends with their usage line and exit status 2 (`AssertionError: usage: ...game.exe ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... ...`).

- [ ] **Step 3: --input and --hashes**

In `src/gbaport/runtime/host_common.c`, replace:
```c
 * joined with '+' (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or "none", held from
 * the FRAME-th VBlank on. While the game is stopped, time does not pass, so the next
 * scripted press comes at once. */
#define _CRT_SECURE_NO_WARNINGS
```
with:
```c
 * joined with '+' (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or "none", held from
 * the FRAME-th VBlank on. An input file (--input FILE, gbaport/inputs.py) holds any number
 * of them, a "FRAME KEYS" line each. While the game is stopped, time does not pass, so the
 * next scripted press comes at once. With --hashes PATH each frame's picture hash goes to
 * a text file, a line a frame, the same gbaport-mgba writes (`gbaport verify` compares
 * them). */
#define _CRT_SECURE_NO_WARNINGS
```

In `src/gbaport/runtime/host_common.c`, replace:
```c

/* "FRAME:KEYS" into a press; returns 0, or -1 when it is not one. */
static int parse_press(const char *text, HostPress *press)
{
    char *end;
    press->frame = strtoul(text, &end, 10);
    if (end == text || *end != ':')
        return -1;
```
with:
```c

/* "FRAME:KEYS" (separator ':') or "FRAME KEYS" (' ') into a press; returns 0, or -1 when
 * it is not one. */
static int parse_press(const char *text, char separator, HostPress *press)
{
    char *end;
    press->frame = strtoul(text, &end, 10);
    if (end == text || *end != separator || *text == '-')
        return -1;
```

In `src/gbaport/runtime/host_common.c`, replace:
```c

int host_parse(HostOptions *o, int argc, char **argv)
```
with:
```c

/* Adds a press after the others; -1 when it comes before the last one. */
static int add_press(HostOptions *o, HostPress press)
{
    if (o->press_count && press.frame < o->presses[o->press_count - 1].frame)
        return -1;
    if (o->press_count == o->press_capacity) {
        o->press_capacity = o->press_capacity ? 2 * o->press_capacity : 64;
        o->presses = realloc(o->presses, (size_t)o->press_capacity * sizeof *o->presses);
    }
    o->presses[o->press_count++] = press;
    return 0;
}

/* The presses of an input file; returns 0, or -1 after printing what is wrong. */
static int load_input(HostOptions *o, const char *path)
{
    FILE *f = open_file(path, "rb");
    if (!f) {
        fprintf(stderr, "error: cannot read %s\n", path);
        return -1;
    }
    char line[256];
    int ok = 1;
    for (int number = 1; ok && fgets(line, sizeof line, f); number++) {
        if (number == 1 && strncmp(line, "\xEF\xBB\xBF", 3) == 0)
            memmove(line, line + 3, strlen(line + 3) + 1);  /* a UTF-8 byte order mark */
        line[strcspn(line, "#\r\n")] = 0;
        char *start = line + strspn(line, " \t"), *stop = start + strlen(start);
        while (stop > start && (stop[-1] == ' ' || stop[-1] == '\t'))
            *--stop = 0;
        if (!*start)
            continue;  /* a blank line or a comment */
        char *gap = start + strcspn(start, " \t");
        if (*gap) {  /* "FRAME   KEYS": one separator */
            char *keys = gap + strspn(gap, " \t");
            memmove(gap + 1, keys, strlen(keys) + 1);
            *gap = ' ';
        }
        HostPress press;
        ok = parse_press(start, ' ', &press) == 0 && add_press(o, press) == 0;
        if (!ok)
            fprintf(stderr, "error: %s, line %d: expected 'FRAME KEYS', frames in order\n",
                    path, number);
    }
    fclose(f);
    return ok ? 0 : -1;
}

int host_parse(HostOptions *o, int argc, char **argv)
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
        } else if (strcmp(arg, "--press") == 0 && value) {
            HostPress *press = &o->presses[o->press_count];
            if (o->press_count == HOST_MAX_PRESSES || parse_press(value, press) != 0 ||
                (o->press_count && press->frame < press[-1].frame))
                bad = 1;
            else
                o->press_count++;
            i++;
```
with:
```c
        } else if (strcmp(arg, "--press") == 0 && value) {
            HostPress press;
            if (parse_press(value, ':', &press) != 0 || add_press(o, press) != 0)
                bad = 1;
            i++;
        } else if (strcmp(arg, "--input") == 0 && value) {
            if (load_input(o, value) != 0)
                return 2;
            i++;
        } else if (strcmp(arg, "--hashes") == 0 && value) {
            o->hashes = value;
            i++;
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
                "usage: %s ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... "
                "[--registers] [--screenshot PATH] [--audio PATH]%s\n",
                argv[0], o->window ? " [--scale N] [--fast]" : "");
```
with:
```c
                "usage: %s ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... "
                "[--input FILE] [--registers] [--screenshot PATH] [--audio PATH] "
                "[--hashes PATH]%s\n",
                argv[0], o->window ? " [--scale N] [--fast]" : "");
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
    }
    while (o->next_press < o->press_count && o->presses[o->next_press].frame == 0)
```
with:
```c
    }
    if (o->hashes) {
        o->hashes_file = open_file(o->hashes, "wb");
        if (!o->hashes_file) {
            fprintf(stderr, "error: cannot write %s\n", o->hashes);
            return 2;
        }
    }
    while (o->next_press < o->press_count && o->presses[o->next_press].frame == 0)
```

In `src/gbaport/runtime/host_common.c`, replace:
```c

void host_frame(HostOptions *o, GbaRuntime *rt)
```
with:
```c

uint64_t host_picture_hash(const GbaRuntime *rt)
{
    uint64_t h = 0xCBF29CE484222325ull;
    for (int y = 0; y < GBA_SCREEN_HEIGHT; y++)
        for (int x = 0; x < GBA_SCREEN_WIDTH; x++) {
            uint16_t colour = rt->screen[y][x];
            h = (h ^ (colour & 0xFF)) * 0x100000001B3ull;
            h = (h ^ ((colour >> 8) & 0x7F)) * 0x100000001B3ull;
        }
    return h;
}

void host_frame(HostOptions *o, GbaRuntime *rt)
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
    write_sound(o);
    while (o->next_press < o->press_count && o->presses[o->next_press].frame <= rt->frames)
```
with:
```c
    write_sound(o);
    if (o->hashes_file)
        fprintf(o->hashes_file, "%016llx\n", (unsigned long long)host_picture_hash(rt));
    while (o->next_press < o->press_count && o->presses[o->next_press].frame <= rt->frames)
```

In `src/gbaport/runtime/host_common.c`, replace:
```c
    }
    if (o->registers) {
```
with:
```c
    }
    if (o->hashes_file && fclose(o->hashes_file) != 0)
        fprintf(stderr, "warning: cannot finish %s\n", o->hashes);
    o->hashes_file = NULL;
    if (o->registers) {
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
/* host_common.h - what both hosts do the same way: the command line, the ROM and save
 * files, scripted key presses, the frame limit, the sound file and the end of a run. */
#ifndef HOST_COMMON_H
```
with:
```c
/* host_common.h - what both hosts do the same way: the command line, the ROM and save
 * files, scripted key presses and input files, the frame limit, the sound file, the
 * pictures' hashes and the end of a run. */
#ifndef HOST_COMMON_H
```

In `src/gbaport/runtime/host_common.h`, replace:
```c

#include "gba_runtime.h"

enum { HOST_MAX_PRESSES = 64 };

typedef struct {
```
with:
```c

#include "gba_runtime.h"

typedef struct {
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
    const char *audio;          /* write the sound there (WAV) */
    void *audio_file;           /* the open WAV file (a FILE *) */
```
with:
```c
    const char *audio;          /* write the sound there (WAV) */
    const char *hashes;         /* write each frame's picture hash there */
    void *hashes_file;          /* the open hashes file (a FILE *) */
    void *audio_file;           /* the open WAV file (a FILE *) */
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
    int scale;                  /* window: initial size in GBA screens */
    HostPress presses[HOST_MAX_PRESSES];
    int press_count, next_press;
    uint16_t script_keys;       /* what the presses so far hold */
```
with:
```c
    int scale;                  /* window: initial size in GBA screens */
    HostPress *presses;         /* from --press and --input, in frame order */
    int press_count, press_capacity, next_press;
    uint16_t script_keys;       /* what the presses so far hold */
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host);
/* Once a frame: the frame's samples (o->sound) and the sound file, scripted presses due
 * by now, the save file, the frame limit. */
void host_frame(HostOptions *o, GbaRuntime *rt);
```
with:
```c
int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host);
/* Once a frame: the frame's samples (o->sound) and the sound file, the picture's hash,
 * scripted presses due by now, the save file, the frame limit. */
void host_frame(HostOptions *o, GbaRuntime *rt);
```

In `src/gbaport/runtime/host_common.h`, replace:
```c
double host_sound_speed(double queued, double target);
/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
```
with:
```c
double host_sound_speed(double queued, double target);
/* The picture's 64-bit FNV-1a hash, over its colours as two bytes each (low first). */
uint64_t host_picture_hash(const GbaRuntime *rt);
/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
```

In `src/gbaport/runtime/host_headless.c`, replace:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--registers]
 *              [--screenshot PATH] [--audio PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Keys come only from --press (host_common.c). --registers prints the CPU registers when
 * the run ends; --screenshot writes the last picture as a BMP file; --audio writes the
 * sound as a WAV file.
 * Exit status: 0 the game executed Stop and no scripted press was left to wake it, 2 bad
```
with:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--input FILE]
 *              [--registers] [--screenshot PATH] [--audio PATH] [--hashes PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Keys come only from --press and --input (host_common.c). --registers prints the CPU
 * registers when the run ends; --screenshot writes the last picture as a BMP file; --audio
 * writes the sound as a WAV file; --hashes writes each frame's picture hash.
 * Exit status: 0 the game executed Stop and no scripted press was left to wake it, 2 bad
```

In `src/gbaport/runtime/host_sdl.c`, replace:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--registers]
 *              [--screenshot PATH] [--audio PATH] [--scale N] [--fast]
 *
```
with:
```c
 *
 *     game ROM [--frames N] [--save PATH] [--press FRAME:KEYS]... [--input FILE]
 *              [--registers] [--screenshot PATH] [--audio PATH] [--hashes PATH]
 *              [--scale N] [--fast]
 *
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 760 passed (755 + 5).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime tests/runtime/test_input_files.py
git commit -m "feat: the hosts play input files and write each frame's picture hash"
```

---

### Task 3: `gbaport verify`

`gbaport verify ROM` recompiles the game into a headless program (in `build/<game_code>-verify`). It plays that program and mGBA for `--frames` frames with the same `--input`, and compares the two hash files. It walks the sequences of pictures (runs of equal frames) side by side, in one pass:
- A picture both show may come up to `--slack` frames apart.
- A picture only one of them shows (a frame caught halfway through a change) may last up to `--slack` frames.
- The first picture that breaks either rule is where they part. Both pictures there go side by side into `frame-N.png`, and the exit status is 1.
- The first frame is left out: the game starts in line 126.
- If the native build stops first, through an error or a BIOS Stop that nothing wakes, verify says so and does not claim the frames it never played.

**Files:**
- Create: `src/gbaport/verify.py`
- Modify: `src/gbaport/cli.py` (the `verify` command), `src/gbaport/native/mgba.py` (`MgbaError` becomes an `OSError`, which the command line reports as an error)
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `run_mgba` (Task 1); `--input`, `--hashes`, `--screenshot` (Task 2, Plan 4c); `cli._recompile`, `native.build.compile_native`; `inputs.load_input`.
- **Produces:**
  - **`gbaport/verify.py`:**
    - `Comparison(frames, pictures, apart, parted)` and `compare(ours, theirs, slack=1) -> Comparison`, with frames counted from 1.
    - `report(comparison) -> str`, `read_hashes(path) -> list[str]`, `play(program, rom, frames, input, folder, extra=())`.
    - `write_png(path, pictures)` and `where_they_part(program, rom, parted, input, folder) -> Path`.
    - `verify(program, rom, frames, input, folder, slack=1) -> int`.
  - **`gbaport verify ROM [--frames N] [--input FILE] [--slack N] [--config] [--trace]... [--out DIR]`:** prints `verified N frames: P pictures in the same order, at most A frame(s) apart`, or `the pictures part at frame F (mGBA's frame G)` and `wrote DIR/frame-F.png (ours, then mGBA's)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify.py`:
```python
"""``gbaport verify``: the native build's pictures against mGBA's, frame by frame."""

import struct
import time

from romtest import build_test_rom
from test_mgba import INPUT

from gbaport.cli import main
from gbaport.verify import Comparison, compare, report, where_they_part


def frames(*pictures: tuple[str, int]) -> list[str]:
    """('a', 3), ('b', 2) -> the hashes of five frames."""
    return [name for name, count in pictures for _ in range(count)]


def test_the_same_pictures_on_the_same_frames_agree():
    hashes = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(hashes, hashes) == Comparison(11, 2, 0, None)


def test_a_picture_a_frame_late_is_within_the_slack():
    ours = frames(("start", 1), ("a", 6), ("b", 4))
    mgba = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, mgba) == Comparison(11, 2, 1, None)


def test_a_picture_two_frames_late_is_where_they_part():
    ours = frames(("start", 1), ("a", 7), ("b", 3))
    mgba = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, mgba).parted == (9, 7)  # frames counted from 1
    assert compare(ours, mgba, slack=2).parted is None


def test_a_picture_only_one_shows_may_last_a_frame():
    ours = frames(("start", 1), ("a", 5), ("b", 5))
    assert compare(ours, frames(("start", 1), ("a", 5), ("x", 1), ("b", 4))).parted is None
    assert compare(ours, frames(("start", 1), ("a", 5), ("x", 2), ("b", 3))).parted == (7, 7)


def test_the_first_frame_is_left_out():
    assert compare(frames(("ours", 1), ("a", 5)), frames(("mgba", 1), ("a", 5))).parted is None


def test_a_build_that_stopped_is_compared_over_the_frames_it_played():
    assert compare(frames(("s", 1), ("a", 3)), frames(("s", 1), ("a", 5), ("b", 5))) == \
        Comparison(4, 1, 0, None)


def test_the_report_says_how_far_apart_or_where_they_part():
    assert report(Comparison(900, 472, 1, None)) == \
        "verified 900 frames: 472 pictures in the same order, at most 1 frame apart"
    assert report(Comparison(40, 4, 0, None)).endswith("at most 0 frames apart")
    assert report(Comparison(4200, 1500, 1, (3837, 3836))) == \
        "the pictures part at frame 3837 (mGBA's frame 3836)"


def echo_files(tmp_path):
    rom = tmp_path / "echo.gba"
    rom.write_bytes(build_test_rom("input_echo").data)
    (tmp_path / "game.input").write_text(INPUT, encoding="utf-8")
    return rom, tmp_path / "game.input"


def test_verify_plays_a_game_both_ways_and_agrees(tmp_path, capsys):
    rom, input_file = echo_files(tmp_path)
    out = tmp_path / "verify"
    assert main(["verify", str(rom), "--frames", "40", "--input", str(input_file),
                 "--out", str(out)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == \
        "verified 40 frames: 4 pictures in the same order, at most 0 frames apart"
    assert len((out / "ours.hashes").read_text().split()) == 40


def test_verify_shows_where_the_pictures_part(tmp_path, capsys):
    rom, input_file = echo_files(tmp_path)
    out = tmp_path / "verify"
    main(["verify", str(rom), "--frames", "12", "--out", str(out)])
    program = next((out / "build").glob("*-verify*"))
    png = where_they_part(program, rom, (15, 25), input_file, out)  # A, then B and UP
    data = png.read_bytes()
    assert png.name == "frame-15.png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (484, 160)  # ours, a gap, mGBA's


def test_verify_says_when_the_native_build_stopped(tmp_path, capsys):
    rom = tmp_path / "missing.gba"
    rom.write_bytes(build_test_rom("err_missing").data)
    assert main(["verify", str(rom), "--frames", "30", "--out", str(tmp_path / "v")]) == 1
    assert "the native build stopped (exit status 3): error: no recompiled code at" in \
        capsys.readouterr().out


def test_a_long_replay_that_parts_early_is_compared_at_once():
    """An hour of frames, every one a new picture, apart from the second on."""
    ours = [f"ours-{frame}" for frame in range(216000)]
    mgba = [f"mgba-{frame}" for frame in range(216000)]
    start = time.perf_counter()
    assert compare(ours, mgba).parted == (2, 2)
    assert compare(ours, ours).parted is None
    assert time.perf_counter() - start < 2


def test_verify_says_when_the_game_stopped_itself(tmp_path, capsys):
    """hello executes Stop before its first VBlank: no frame to compare, so no agreement."""
    rom = tmp_path / "hello.gba"
    rom.write_bytes(build_test_rom("hello").data)
    assert main(["verify", str(rom), "--frames", "30", "--out", str(tmp_path / "v")]) == 1
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "the native build stopped at frame 0: the game executed Stop and nothing woke it",
        "verified 0 frames: 0 pictures in the same order, at most 0 frames apart",
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_verify.py`
Expected: FAIL — 1 error: `ModuleNotFoundError: No module named 'gbaport.verify'`.

- [ ] **Step 3: The comparison and the command**

In `src/gbaport/cli.py`, replace:
```python
from gbaport.disasm import disassemble, format_line
from gbaport.isa.model import Mode
```
with:
```python
from gbaport.disasm import disassemble, format_line
from gbaport.inputs import load_input
from gbaport.isa.model import Mode
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, GdbError, SocketTransport
from gbaport.tracing.session import TraceSession, check_loaded_rom


def build_parser() -> argparse.ArgumentParser:
```
with:
```python
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, GdbError, SocketTransport
from gbaport.tracing.session import TraceSession, check_loaded_rom
from gbaport.verify import verify


def build_parser() -> argparse.ArgumentParser:
```

In `src/gbaport/cli.py`, replace:
```python
    _add_build_command(commands)
    return parser
```
with:
```python
    _add_build_command(commands)
    _add_verify_command(commands)
    return parser
```

In `src/gbaport/cli.py`, replace:
```python

def main(argv: list[str] | None = None) -> int:
```
with:
```python

def _add_verify_command(commands) -> None:
    verify_command = commands.add_parser(
        "verify", help="play a game natively and in mGBA, and compare their pictures"
    )
    verify_command.add_argument("rom", help="path to a .gba file")
    verify_command.add_argument(
        "--frames", type=int, default=600, help="frames to play (default 600: ten seconds)"
    )
    verify_command.add_argument(
        "--input", help="input file both play (see gbaport/inputs.py; default: no keys)"
    )
    verify_command.add_argument(
        "--slack",
        type=int,
        default=1,
        help="frames a picture may come early or late (default 1)",
    )
    verify_command.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    verify_command.add_argument(
        "--trace",
        action="append",
        default=[],
        help="trace file to import (repeatable; games/<game_code>/traces/*.trace are read too)",
    )
    verify_command.add_argument(
        "--out",
        help="folder for the build, the hashes and pictures (default: build/<game_code>-verify)",
    )
    verify_command.set_defaults(handler=_run_verify)


def _run_verify(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    if args.input:
        load_input(args.input)  # a bad input file stops here, with its line
    game_code = parse_header(rom).game_code or "game"
    root = Path(args.out) if args.out else Path("build") / f"{game_code}-verify"
    _recompile(args, rom, root / "generated")
    program = compile_native(root / "generated", root / "build", f"{game_code}-verify", "headless")
    return verify(program, Path(args.rom), args.frames, Path(args.input) if args.input else None,
                  root, args.slack)


def main(argv: list[str] | None = None) -> int:
```

In `src/gbaport/native/mgba.py`, replace:
```python
SOURCE_FILES = ("CMakeLists.txt", "mgba.c")


class MgbaError(RuntimeError):
    """mGBA could not run the ROM as asked."""


def _source_release() -> Path:
```
with:
```python
SOURCE_FILES = ("CMakeLists.txt", "mgba.c")


class MgbaError(OSError):
    """mGBA could not run the ROM as asked (the command line reports it as an error)."""


def _source_release() -> Path:
```

Create `src/gbaport/verify.py`:
```python
"""``gbaport verify``: a game's native build against mGBA, picture by picture.

Both play the same input file from power-on with a blank save and write a hash of each
frame's picture (``--hashes``). The comparison takes runs of equal frames as pictures and
walks the two sequences of pictures side by side. The native build counts cycles as mGBA
does, but not everything happens at exactly the same moment (an interrupt comes at a loop
or a return), so a picture may come a frame early or late. ``slack`` frames are allowed:
each picture both show must come
within that many frames of mGBA's, and a picture only one of them shows may last at most
that long. The first picture that breaks this is where they part; the pictures there go
side by side into a PNG file. The first frame is left out: the game starts in line 126, so
its top lines show nothing yet.
"""

import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

from gbaport.native.mgba import run_mgba


@dataclass(frozen=True)
class Comparison:
    frames: int  # frames both played
    pictures: int  # pictures mGBA showed in them
    apart: int  # the most frames a picture came early or late
    parted: tuple[int, int] | None  # (our frame, mGBA's frame) where the pictures part


def _pictures(hashes: list[str]) -> list[tuple[str, int, int]]:
    """Runs of equal frames as (hash, first frame, frames), frames counted from 1 (the
    picture complete at the first VBlank); the first frame is left out."""
    runs: list[tuple[str, int, int]] = []
    for frame, value in enumerate(hashes[1:], start=2):
        if runs and runs[-1][0] == value:
            runs[-1] = (value, runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((value, frame, 1))
    return runs


def _past_extras(a: list[tuple[str, int, int]], b: list[tuple[str, int, int]], i: int, j: int,
                 slack: int) -> tuple[int, int] | None:
    """Where the two show the same picture again (or end) after pictures only one of them
    shows, at most ``slack`` frames of them on each side, the fewest first; None when
    there is no such place."""
    def reach(runs: list[tuple[str, int, int]], start: int) -> list[int]:
        ends, frames = [start], 0
        while ends[-1] < len(runs) and frames + runs[ends[-1]][2] <= slack:
            frames += runs[ends[-1]][2]
            ends.append(ends[-1] + 1)
        return ends

    places = [(x, y) for x in reach(a, i) for y in reach(b, j) if (x, y) != (i, j)]
    for x, y in sorted(places, key=lambda place: place[0] - i + place[1] - j):
        if x == len(a) or y == len(b) or a[x][0] == b[y][0]:
            return x, y
    return None


def compare(ours: list[str], theirs: list[str], slack: int = 1) -> Comparison:
    """Our frames' hashes against mGBA's, over the frames both have. One pass, so a long
    replay that parts early takes no longer than one that does not."""
    frames = min(len(ours), len(theirs))
    a, b = _pictures(ours[:frames]), _pictures(theirs[:frames])
    i = j = apart = 0
    while i < len(a) and j < len(b):
        if a[i][0] == b[j][0]:
            if abs(a[i][1] - b[j][1]) > slack:
                return Comparison(frames, len(b), apart, (a[i][1], b[j][1]))
            apart = max(apart, abs(a[i][1] - b[j][1]))
            i, j = i + 1, j + 1
            continue
        place = _past_extras(a, b, i, j, slack)
        if place is None:
            return Comparison(frames, len(b), apart, (a[i][1], b[j][1]))
        i, j = place
    return Comparison(frames, len(b), apart, None)


def report(comparison: Comparison) -> str:
    c = comparison
    if c.parted is None:
        frame_word = "frame" if c.apart == 1 else "frames"
        return (f"verified {c.frames} frames: {c.pictures} pictures in the same order, "
                f"at most {c.apart} {frame_word} apart")
    return f"the pictures part at frame {c.parted[0]} (mGBA's frame {c.parted[1]})"


def read_hashes(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def play(program: Path, rom: Path, frames: int, input: Path | None, folder: Path,
         extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Runs the native build with a blank save; its hashes go to folder/ours.hashes."""
    save = folder / "verify.sav"
    save.unlink(missing_ok=True)
    command = [str(program), str(rom), "--frames", str(frames), "--save", str(save),
               "--hashes", str(folder / "ours.hashes"), *extra]
    if input is not None:
        command += ["--input", str(input)]
    return subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)


def _bmp_colours(data: bytes) -> list[int]:
    """The hosts' 24-bit, bottom-up 240x160 BMP as GBA colours."""
    offset = struct.unpack_from("<I", data, 10)[0]
    colours = []
    for y in range(160):
        row = offset + (159 - y) * 720
        for x in range(240):
            b, g, r = data[row + 3 * x: row + 3 * x + 3]
            colours.append(r >> 3 | (g >> 3) << 5 | (b >> 3) << 10)
    return colours


def write_png(path: Path, pictures: list[list[int]]) -> None:
    """240x160 GBA-colour pictures side by side, a grey gap between them."""
    rows = []
    for y in range(160):
        row = bytearray([0])
        for i, picture in enumerate(pictures):
            if i:
                row += b"\x80\x80\x80" * 4
            for c in picture[y * 240:(y + 1) * 240]:
                row += bytes(((c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3))
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    width = 240 * len(pictures) + 4 * (len(pictures) - 1)
    header = struct.pack(">IIBBBBB", width, 160, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def where_they_part(program: Path, rom: Path, parted: tuple[int, int], input: Path | None,
                    folder: Path) -> Path:
    """Our picture at our frame and mGBA's at its own, side by side: folder/frame-N.png."""
    ours, theirs = parted
    shot = folder / "ours.bmp"
    play(program, rom, ours, input, folder, ("--screenshot", str(shot)))
    run_mgba(rom, theirs, input=input, picture=folder / "mgba.raw", log=lambda line: None)
    mgba = list(struct.unpack("<38400H", (folder / "mgba.raw").read_bytes()))
    png = folder / f"frame-{ours}.png"
    write_png(png, [_bmp_colours(shot.read_bytes()), mgba])
    return png


def verify(program: Path, rom: Path, frames: int, input: Path | None, folder: Path,
           slack: int = 1) -> int:
    """Plays ``rom`` natively and in mGBA, prints how their pictures compare, and returns 0
    when they agree within ``slack`` frames for all of them, 1 when they part or the native
    build stopped first."""
    folder.mkdir(parents=True, exist_ok=True)
    run = play(program, rom, frames, input, folder)
    if run.returncode not in (0, 4):
        last = (run.stderr.strip().splitlines() or ["(no message)"])[-1]
        print(f"the native build stopped (exit status {run.returncode}): {last}")
    ours = read_hashes(folder / "ours.hashes")
    if run.returncode == 0 and len(ours) < frames:
        print(f"the native build stopped at frame {len(ours)}: the game executed Stop and "
              "nothing woke it")
    run_mgba(rom, frames, input=input, hashes=folder / "mgba.hashes")
    comparison = compare(ours, read_hashes(folder / "mgba.hashes"), slack)
    print(report(comparison))
    if comparison.parted is not None:
        print(f"wrote {where_they_part(program, rom, comparison.parted, input, folder)} "
              "(ours, then mGBA's)")
        return 1
    return 0 if run.returncode == 4 else 1  # all the frames, compared
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 772 passed (760 + 12).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/verify.py src/gbaport/cli.py src/gbaport/native/mgba.py tests/test_verify.py
git commit -m "feat: gbaport verify plays a game natively and in mGBA and compares the pictures"
```

---

### Task 4: Instruction timing as mGBA counts it

Each instruction costs what mGBA's ARM core charges for it:
- **The fetch.** The next instruction is fetched at the wait states of the memory the code is in: sequential (S) normally, nonsequential (N) after a data access or a multiply. That is 1 + S or 1 + N cycles.
- **Internal cycles.** One more for a register-specified shift, and a multiply's from its operand's significant bytes (mGBA's `ARM_WAIT_SMUL`/`ARM_WAIT_UMUL`).
- **Data accesses.**
  - A load costs its memory's N wait states plus 2; a store, plus 1. A load or store multiple costs N once, then S for each word.
  - Code in the cartridge with the prefetch buffer on goes through mGBA's `GBAMemoryStall`: the buffer fetches ahead during the wait, so those fetches later cost nothing.
- **Jumps** refill the pipeline: 2 + N + S of the code at the target. The prefetch buffer starts again after a jump.

The wait states live in `GbaCtx` as mGBA's tables (`n16`, `s16`, `n32`, `s32`, by region), rebuilt whenever WAITCNT is written. The lifter writes each block's costs as these table entries, so a WAITCNT write takes effect at once. It adds them to `ctx->cycles` in pieces, just before each memory access and before control leaves the block, so a timer or VCOUNT read sees the cycles of the instructions before it, as in mGBA. The waits of data accesses come after the access.

An interrupt's entry and exit cost what mGBA's BIOS stand-in takes, counted instruction by instruction in `scheduler.c`. Clearing the CPSR's I bit with an interrupt pending lets it in at the next check, at once as in mGBA. `interrupts.c` checked the old behaviour, a delay until the next scheduler event, by waiting for a later line; it now checks with a short spin, like its IME and IE checks.

**Files:**
- Modify: `src/gbaport/lift/gba_cpu.h` (the tables, `gba_stall`, `gba_load_wait`, `gba_store_wait`, `gba_multiple_wait`, `gba_mul_wait`, `gba_jumped`, `gba_refill`; the I bit)
- Modify: `src/gbaport/lift/semantics.py` (`cycles`, `stall_pc`, the waits), `src/gbaport/lift/function.py` (costs in pieces, refills)
- Modify: `src/gbaport/runtime/memory.c` (`gba_waitcnt`), `io.c`, `runtime.c`, `gba_runtime.h`, `scheduler.c` (an interrupt's cost)
- Modify: `tests/gbaroms/interrupts.c`
- Create: `tests/gbaroms/cycles.c`, `tests/gbaroms/hblank_irq.c`
- Test: `tests/runtime/test_timing.py`

**Interfaces:**
- Consumes: `mgba_picture` (Task 1), `rendertest.our_picture`, `romtest.build_test_rom`; testlib's `irq_init`, `irq_count`, `wait_vcount`.
- **Produces:**
  - **`GbaCtx`:** `uint8_t n16[16], s16[16], n32[16], s32[16]; uint32_t prefetch, prefetched;`.
  - **`gba_cpu.h`:**
    - `gba_region(addr)`, `gba_stall(ctx, wait, pc)`.
    - `gba_load_wait(ctx, addr, wide, pc)`, `gba_store_wait(ctx, addr, wide, pc)`, `gba_multiple_wait(ctx, addr, count, load, pc)`.
    - `gba_mul_wait(ctx, value, is_signed, base, pc)`, `gba_jumped(ctx, cycles)`, `gba_refill(ctx, t)`.
    - pc is the instruction's address + 4 (Thumb) or + 8 (ARM) in the cartridge, else 0.
  - **`gba_runtime.h`:** `void gba_waitcnt(GbaRuntime *rt, uint16_t value)`.
  - **`semantics.py`:** `cycles(ins) -> (cycles, S fetches, N fetches)`, `in_cartridge(addr)`, `stall_pc(ins)`.
  - **`cycles.c`** draws each count as two pixels of a mode 3 picture (bits 0-14, then 15-29), 15 scenes for each of 4 WAITCNT settings. **`test_timing.py`:** `SETTINGS`, `SCENES`, `drawn(picture, count)`.

- [ ] **Step 1: Write the failing tests and the test ROMs**

Create `tests/gbaroms/cycles.c`:
```c
/* How many cycles kinds of code take, measured with timer 0: Thumb and ARM code in the
 * cartridge and ARM code in IWRAM, loads and stores to each memory, load and store
 * multiple, multiplies and branches, each under four WAITCNT settings. Each count is drawn
 * as two pixels of a mode 3 picture (bits 0-14, then 15-29), so a test reads mGBA's counts
 * from its picture and the runtime's from its own. */
#include "testlib.h"

#define TM0 REG_TM_CNT_L(0)
#define VRAM16 ((volatile uint16_t *)0x06000000)
#define EWRAM_WORDS ((volatile uint32_t *)0x02000000)

static uint32_t iwram_words[64] __attribute__((section(".iwram.data")));
static const uint32_t rom_words[64] = {1, 2, 3, 4, 5, 6, 7, 8};
static int slot;

static void record(uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
    slot++;
}

/* Thumb, in the cartridge. */
static uint32_t thumb_alu(void)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: adds r1, #1\nadds r1, #1\nadds r1, #1\nadds r1, #1\n"
                     "adds r1, #1\nadds r1, #1\nadds r1, #1\nsubs r0, #1\nbne 1b"
                     ::: "r0", "r1", "cc");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_loads(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: ldr r1, [%0]\nldr r1, [%0, #4]\nldrh r1, [%0]\n"
                     "ldrb r1, [%0, #1]\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_stores(volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: str r0, [%0]\nstrh r0, [%0, #4]\nstrb r0, [%0, #6]\n"
                     "adds r1, #1\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_multiple(volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #32\n1: adds r2, %0, #0\nstmia r2!, {r3-r6}\nadds r2, %0, #0\n"
                     "ldmia r2!, {r3-r6}\npush {r4-r7}\npop {r4-r7}\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r2", "r3", "r4", "r5", "r6", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_multiply(uint32_t value)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: adds r1, %0, #0\nmuls r1, r1\nadds r1, %0, #0\n"
                     "muls r1, r0\nsubs r0, #1\nbne 1b"
                     :: "l"(value) : "r0", "r1", "cc");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_branches(void)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: b 2f\nnop\n2: cmp r0, #100\nbeq 3f\n3: subs r0, #1\nbne 1b"
                     ::: "r0", "cc");
    return (uint16_t)(TM0 - t);
}

/* ARM, in the cartridge and in IWRAM. */
__attribute__((target("arm"), noinline)) static uint32_t arm_rom(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("mov r0, #64\n1: add r1, r1, #1\nadd r1, r1, r1, lsl #2\nldr r1, [%0]\n"
                     "str r1, [%0, #4]\nsubs r0, r0, #1\nbne 1b"
                     :: "r"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

__attribute__((target("arm"), noinline, section(".iwram")))
static uint32_t arm_iwram(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("mov r0, #64\n1: add r1, r1, #1\nadd r1, r1, r1, lsl r0\nldr r1, [%0]\n"
                     "str r1, [%0, #4]\nmul r1, r0, r1\nsubs r0, r0, #1\nbne 1b"
                     :: "r"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static const uint16_t SETTINGS[4] = {0x0000, 0x4317, 0x0317, 0x4314};

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    REG_TM_CNT_H(0) = 0x0080;  /* timer 0 counts cycles */
    for (int i = 0; i < 4; i++) {
        REG_WAITCNT = SETTINGS[i];
        record(thumb_alu());
        record(thumb_loads(iwram_words));
        record(thumb_loads(EWRAM_WORDS));
        record(thumb_loads(rom_words));
        record(thumb_loads(VRAM16 + 0x8000));
        record(thumb_stores(iwram_words));
        record(thumb_stores(EWRAM_WORDS));
        record(thumb_stores(VRAM16 + 0x8000));
        record(thumb_multiple(EWRAM_WORDS));
        record(thumb_multiple(iwram_words));
        record(thumb_multiply(5));
        record(thumb_multiply(0x12345678));
        record(thumb_branches());
        record(arm_rom(EWRAM_WORDS));
        record(arm_iwram(EWRAM_WORDS));
    }
    REG_TM_CNT_H(0) = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with every count */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
```

Create `tests/gbaroms/hblank_irq.c`:
```c
/* How much an HBlank interrupt slows the CPU: the iterations of a busy loop from line 20 to
 * line 60, without and with the counting IRQ handler running at every HBlank, and how many
 * interrupts it took, drawn like the cycles test's counts. */
#include "testlib.h"

#define VRAM16 ((volatile uint16_t *)0x06000000)

static void draw(int slot, uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
}

static uint32_t loops_from_20_to_60(void)
{
    uint32_t loops = 0;
    wait_vcount(20);
    while (REG_VCOUNT != 60)
        loops++;
    return loops;
}

int main(void)
{
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    irq_init();
    draw(0, loops_from_20_to_60());
    wait_vcount(0);
    REG_DISPSTAT = 0x0010;  /* HBlank interrupts */
    REG_IE = IRQ_HBLANK;
    wait_vcount(19);
    uint32_t before = irq_count[1];
    draw(1, loops_from_20_to_60());
    draw(2, irq_count[1] - before);
    REG_IE = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with every count */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
```

In `tests/gbaroms/interrupts.c`, replace:
```c

    /* The CPSR's I bit masks interrupts; clearing it with MSR lets them in again (taken at
     * the next scheduler event, so within a scanline). */
    set_cpsr_control(0x9F);
```
with:
```c

    /* The CPSR's I bit masks interrupts; clearing it with MSR lets a pending one in at once. */
    set_cpsr_control(0x9F);
```

In `tests/gbaroms/interrupts.c`, replace:
```c
    set_cpsr_control(0x1F);
    wait_vcount(163);
    expect("cpsr I clear: pending interrupt delivered", irq_count[0], before + 1);
```
with:
```c
    set_cpsr_control(0x1F);
    spin(10);
    expect("cpsr I clear: pending interrupt delivered", irq_count[0], before + 1);
```

Create `tests/runtime/test_timing.py`:
```python
"""Code takes as many cycles as in mGBA: the cycles test ROM times kinds of code with
timer 0 under four WAITCNT settings, natively and in mGBA, and draws the counts. An
interrupt takes about as long too."""

import pytest
from mgbaref import mgba_picture
from rendertest import our_picture
from romtest import build_test_rom

SETTINGS = ["0x0000", "0x4317", "0x0317", "0x4314"]  # default; fast, prefetch; no prefetch; BT4E's
SCENES = ["thumb alu", "thumb ldr iwram", "thumb ldr ewram", "thumb ldr rom", "thumb ldr vram",
          "thumb str iwram", "thumb str ewram", "thumb str vram", "thumb ldm/stm ewram",
          "thumb ldm/stm iwram", "thumb mul small", "thumb mul large", "thumb branches",
          "arm in rom", "arm in iwram"]


def drawn(picture: list[int], count: int) -> list[int]:
    """The counts a test ROM drew: two pixels each, bits 0-14 then 15-29."""
    return [picture[2 * k] | picture[2 * k + 1] << 15 for k in range(count)]


@pytest.fixture(scope="module")
def measured() -> tuple[list[int], list[int]]:
    rom, count = build_test_rom("cycles"), len(SETTINGS) * len(SCENES)
    return drawn(our_picture(rom, 10), count), drawn(mgba_picture(rom.data, 10), count)


@pytest.mark.parametrize("setting", range(len(SETTINGS)), ids=SETTINGS)
@pytest.mark.parametrize("scene", range(len(SCENES)), ids=SCENES)
def test_code_takes_as_many_cycles_as_in_mgba(measured, setting, scene):
    ours, mgba = measured
    k = setting * len(SCENES) + scene
    assert ours[k] == mgba[k]


def test_an_hblank_interrupt_slows_the_cpu_about_as_much_as_in_mgba():
    """Iterations of a busy loop over 40 lines, without and with an interrupt at every
    HBlank. Each interrupt costs here within 4 cycles of mGBA (README, Known limitations)."""
    rom = build_test_rom("hblank_irq")
    ours, mgba = drawn(our_picture(rom, 20), 3), drawn(mgba_picture(rom.data, 20), 3)
    assert ours[0] == mgba[0]  # no interrupts: the same loop
    assert ours[2] == mgba[2] == 41  # line 19's HBlank and the 40 after it
    cycles_a_loop = 40 * 1232 / mgba[0]
    assert abs(ours[1] - mgba[1]) * cycles_a_loop <= 4 * mgba[2]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_timing.py tests/runtime/test_interrupts.py`
Expected: FAIL — 62 failed, 3 passed.
- All 60 scenes of `test_code_takes_as_many_cycles_as_in_mgba` fail with `assert X == Y`: the old estimates.
- `test_an_hblank_interrupt_slows_the_cpu_about_as_much_as_in_mgba` fails.
- `test_scanlines_interrupts_and_waits` fails with `FAIL cpsr I clear: pending interrupt delivered` (`DONE 30 passed, 1 failed`).
- The other three interrupt tests pass.

- [ ] **Step 3: mGBA's instruction timing**

In `src/gbaport/lift/function.py`, replace:
```python
scheduler run.
"""
```
with:
```python
scheduler run.

Time is counted as mGBA counts it (gba_cpu.h): each instruction costs the fetch of
the next one at the wait states of the memory the code is in (set by WAITCNT),
plus its internal cycles. Those costs are added to ``ctx->cycles`` in pieces, just
before each memory access and before control leaves the block, so an access sees
the time the instructions before it took, as in mGBA. Data accesses, multiplies
and jumps add their own waits where they happen.
"""
```

In `src/gbaport/lift/function.py`, replace:
```python
        lines = [f"{label(start)}:"]
        lines.append(f"    ctx->cycles += {sum(cycles(ins) for ins in block.instructions)};")
        if loop_head:
```
with:
```python
        lines = [f"{label(start)}:"]
        if loop_head:
```

In `src/gbaport/lift/function.py`, replace:
```python
        ended = False
        for ins in block.instructions:
            lines.append(f"    /* {ins.addr:08x} */")
            body, ended = self._instruction(ins, prev)
            if ins.cond is not Cond.AL:
```
with:
```python
        ended = False
        pending = (0, 0, 0)  # the cost of instructions run but not yet added to ctx->cycles
        for ins in block.instructions:
            lines.append(f"    /* {ins.addr:08x} */")
            own = self._static(ins)
            if _leaves(ins):  # its own cost too, before control goes elsewhere
                pending, own = _plus(pending, own), (0, 0, 0)
            if _leaves(ins) or _accesses(ins):
                lines += self._charge(pending, ins)
                pending = (0, 0, 0)
            pending = _plus(pending, own)
            body, ended = self._instruction(ins, prev)
            body = self._extra(ins) + body
            if ins.cond is not Cond.AL:
```

In `src/gbaport/lift/function.py`, replace:
```python
        if not ended:
            last = block.instructions[-1]
```
with:
```python
        if not ended:
            lines += self._charge(pending, block.instructions[-1])
            last = block.instructions[-1]
```

In `src/gbaport/lift/function.py`, replace:
```python
                lines.append("    " + self._go(nxt, block.mode))
        return lines

    def _predecessor(self, start: int, mode: Mode) -> Instruction | None:
```
with:
```python
                lines.append("    " + self._go(nxt, block.mode))
        return lines

    def _static(self, ins: Instruction) -> tuple[int, int, int]:
        """The cost of ``ins`` known before it runs (see ``semantics.cycles``)."""
        if ins.cond is not Cond.AL and ins.mode is Mode.ARM:
            return 1, 1, 0  # the rest is added if the condition holds
        return cycles(ins)

    def _charge(self, cost: tuple[int, int, int], ins: Instruction) -> list[str]:
        if cost == (0, 0, 0):
            return []
        return [f"    ctx->cycles += {_cost_expr(*cost, ins.addr, ins.mode)};"]

    def _extra(self, ins: Instruction) -> list[str]:
        """What a conditional ARM instruction costs beyond its fetch, when it runs."""
        if ins.cond is Cond.AL or ins.mode is not Mode.ARM:
            return []
        k, s, n = cycles(ins)
        if (k, s, n) == (1, 1, 0):
            return []
        return [f"ctx->cycles += {_cost_expr(k - 1, s - 1, n, ins.addr, ins.mode)};"]

    def _predecessor(self, start: int, mode: Mode) -> Instruction | None:
```

In `src/gbaport/lift/function.py`, replace:
```python
        if op is Op.B:
            if ins.target == after:  # a branch to the next instruction does nothing
                return [], False
            return [self._go(ins.target, ins.mode)], True
        if op is Op.BL:
            ret = self._return_address(ins)
            set_lr = f"ctx->r[14] = {hexu(ret)};"
            if ins.target == after:  # only sets LR (a weak call, or reading the pc)
                return [set_lr], False
            return [set_lr, self._call(ins.target, ret, ins.mode)], False
        if op is Op.BL_LO:
```
with:
```python
        if op is Op.B:
            refill = f"gba_jumped(ctx, {_refill_expr(ins.target, ins.mode)});"
            if ins.target == after:  # a branch to the next instruction only refills
                return [refill], False
            return [refill, self._go(ins.target, ins.mode)], True
        if op is Op.BL:
            ret = self._return_address(ins)
            set_lr = f"ctx->r[14] = {hexu(ret)};"
            refill = f"gba_jumped(ctx, {_refill_expr(ins.target, ins.mode)});"
            if ins.target == after:  # only sets LR (a weak call, or reading the pc)
                return [set_lr, refill], False
            return [set_lr, refill, self._call(ins.target, ret, ins.mode)], False
        if op is Op.BL_LO:
```

In `src/gbaport/lift/function.py`, replace:
```python
                f"ctx->r[14] = {hexu(ret)};",
                f"gba_call(ctx, t, {hexu(ret)});",
```
with:
```python
                f"ctx->r[14] = {hexu(ret)};",
                "gba_jumped(ctx, gba_refill(ctx, t));",
                f"gba_call(ctx, t, {hexu(ret)});",
```

In `src/gbaport/lift/function.py`, replace:
```python
            return effects, False
        body = effects + self._mask(ins)
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
```
with:
```python
            return effects, False
        body = effects + self._mask(ins) + ["gba_jumped(ctx, gba_refill(ctx, t));"]
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
```

In `src/gbaport/lift/function.py`, replace:
```python

def _in_state(target: int, mode: Mode) -> int:
```
with:
```python

def _plus(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[int, int, int]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _leaves(ins: Instruction) -> bool:
    """Control may go elsewhere after ``ins``: a branch, call or write to pc."""
    return ins.op in (Op.B, Op.BL, Op.BL_LO) or writes_pc(ins)


def _accesses(ins: Instruction) -> bool:
    """``ins`` reads or writes memory, or calls the BIOS: it may see the time."""
    return ins.op in (Op.LDR, Op.LDRB, Op.LDRH, Op.LDRSB, Op.LDRSH, Op.STR, Op.STRB, Op.STRH,
                      Op.LDM, Op.STM, Op.SWP, Op.SWPB, Op.SWI)


def _cost_expr(k: int, s: int, n: int, addr: int, mode: Mode) -> str:
    """C for k cycles plus s sequential and n nonsequential fetches of code at ``addr``."""
    width = "16" if mode is Mode.THUMB else "32"
    region = addr >> 24 if addr >> 24 < 16 else 0  # as gba_region()
    terms = [f"{k}u"]
    if s:
        terms.append(f"{s} * ctx->s{width}[{region}]")
    if n:
        terms.append(f"{n} * ctx->n{width}[{region}]")
    return " + ".join(terms)


def _refill_expr(target: int, mode: Mode) -> str:
    """Refilling the pipeline at a constant target: 2 + N + S of its code."""
    return _cost_expr(2, 1, 1, target, mode)


def _in_state(target: int, mode: Mode) -> int:
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c
    uint32_t call_depth;        /* gba_call chains currently running */
    GbaFn (*lookup)(struct GbaCtx *ctx, uint32_t addr); /* recompiled function at addr */
```
with:
```c
    uint32_t call_depth;        /* gba_call chains currently running */
    /* Timing as mGBA counts it: the wait states of a 16- or 32-bit access to each memory
     * region (addr >> 24; N: nonsequential, S: sequential), set from WAITCNT for the
     * cartridge, and mGBA's model of the cartridge's prefetch buffer. */
    uint8_t n16[16], s16[16], n32[16], s32[16];
    uint32_t prefetch;          /* WAITCNT bit 14 */
    uint32_t prefetched;        /* how far the buffer has fetched (mGBA's lastPrefetchedPc) */
    GbaFn (*lookup)(struct GbaCtx *ctx, uint32_t addr); /* recompiled function at addr */
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c

#define GBA_CHECK_EVENTS() do { if (ctx->cycles >= ctx->next_event) gba_events(ctx); } while (0)

/* ---- shifter: value, and the carry-out written through *c ------------------- */
```
with:
```c

#define GBA_CHECK_EVENTS() do { if (ctx->cycles >= ctx->next_event) gba_events(ctx); } while (0)

/* ---- timing ------------------------------------------------------------------ */

static inline uint32_t gba_region(uint32_t addr) { return addr >> 24 < 16 ? addr >> 24 : 0; }

/* mGBA's GBAMemoryStall. Code running from the cartridge (pc: the instruction's address
 * + 4, as the CPU sees it) with the prefetch buffer on: while a data access or an
 * internal cycle waits, the buffer fetches the next halfwords, whose waits disappear. */
static inline int32_t gba_stall(GbaCtx *ctx, int32_t wait, uint32_t pc)
{
    if (!pc || !ctx->prefetch)
        return wait;
    int32_t previous = 0, most = 8;
    uint32_t dist = ctx->prefetched - pc;
    if (dist < 16) {
        previous = (int32_t)(dist >> 1);
        most -= previous;
    }
    uint32_t r = pc >> 24;
    int32_t s = ctx->s16[r], n2s = ctx->n16[r] - s + 1;
    int32_t stall = s + 1, loads = 1;
    while (stall < wait && loads < most) {
        stall += s;
        loads++;
    }
    ctx->prefetched = pc + 2u * (uint32_t)(loads + previous - 1);
    if (stall > wait)
        wait = stall;
    return wait - n2s - (stall - 1);
}

/* A load (store) of 8/16 or 32 bits: the region's N wait states, the access, and for a
 * load an internal cycle. pc is 0 for code outside the cartridge. */
static inline void gba_load_wait(GbaCtx *ctx, uint32_t addr, int wide, uint32_t pc)
{
    uint32_t r = gba_region(addr);
    int32_t wait = (wide ? ctx->n32[r] : ctx->n16[r]) + 2;
    if (addr < 0x08000000u)
        wait = gba_stall(ctx, wait, pc);
    ctx->cycles += (uint64_t)(int64_t)wait;
}

static inline void gba_store_wait(GbaCtx *ctx, uint32_t addr, int wide, uint32_t pc)
{
    uint32_t r = gba_region(addr);
    int32_t wait = (wide ? ctx->n32[r] : ctx->n16[r]) + 1;
    if (addr < 0x08000000u)
        wait = gba_stall(ctx, wait, pc);
    ctx->cycles += (uint64_t)(int64_t)wait;
}

/* LDM/STM of count words from addr: the first nonsequential, the rest sequential. */
static inline void gba_multiple_wait(GbaCtx *ctx, uint32_t addr, uint32_t count, int load,
                                     uint32_t pc)
{
    uint32_t r = gba_region(addr);
    int32_t wait = ctx->s32[r] - ctx->n32[r] + (int32_t)count * (1 + ctx->s32[r]) + load;
    if (addr < 0x08000000u)
        wait = gba_stall(ctx, wait, pc);
    ctx->cycles += (uint64_t)(int64_t)wait;
}

/* A multiply's internal cycles, from the operand's significant bytes (mGBA's
 * ARM_WAIT_SMUL / ARM_WAIT_UMUL), plus base (1 for MLA and the long ones, 2 when they
 * accumulate). */
static inline void gba_mul_wait(GbaCtx *ctx, uint32_t v, int is_signed, int32_t base, uint32_t pc)
{
    int32_t wait = base;
    if (is_signed) {
        if ((v & 0xFFFFFF00u) == 0xFFFFFF00u || !(v & 0xFFFFFF00u)) wait += 1;
        else if ((v & 0xFFFF0000u) == 0xFFFF0000u || !(v & 0xFFFF0000u)) wait += 2;
        else if ((v & 0xFF000000u) == 0xFF000000u || !(v & 0xFF000000u)) wait += 3;
        else wait += 4;
    } else {
        if (!(v & 0xFFFFFF00u)) wait += 1;
        else if (!(v & 0xFFFF0000u)) wait += 2;
        else if (!(v & 0xFF000000u)) wait += 3;
        else wait += 4;
    }
    ctx->cycles += (uint64_t)(int64_t)gba_stall(ctx, wait, pc);
}

/* A jump: refilling the pipeline costs 2 + N + S of the code at the target, and the
 * prefetch buffer starts again. */
static inline void gba_jumped(GbaCtx *ctx, uint32_t cycles)
{
    ctx->cycles += cycles;
    ctx->prefetched = 0;
}

/* The refill cost of a jump to t (bit 0: Thumb). */
static inline uint32_t gba_refill(GbaCtx *ctx, uint32_t t)
{
    uint32_t r = gba_region(t);
    return t & 1u ? 2u + ctx->n16[r] + ctx->s16[r] : 2u + ctx->n32[r] + ctx->s32[r];
}

/* ---- shifter: value, and the carry-out written through *c ------------------- */
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c
        ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0xDFu) | (value & 0xDF);
    }
```
with:
```c
        ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0xDFu) | (value & 0xDF);
        if (!(value & 0x80))
            ctx->next_event = 0;  /* a pending interrupt is taken at the next check */
    }
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c
    ctx->v = (saved >> 28) & 1;
}
```
with:
```c
    ctx->v = (saved >> 28) & 1;
    if (!(saved & 0x80))
        ctx->next_event = 0;  /* a pending interrupt is taken at the next check */
}
```

In `src/gbaport/lift/semantics.py`, replace:
```python
    return ins.op is Op.LDM and ins.user and PC in ins.reglist


def cycles(ins: Instruction) -> int:
    """A rough cycle estimate; the scheduler only needs the right order of magnitude."""
    op = ins.op
    if op in _LOADS or op in (Op.SWP, Op.SWPB):
        return 3
    if op in _STORES:
        return 2
    if op in (Op.LDM, Op.STM):
        return 2 + len(ins.reglist)
    if op in (Op.MUL, Op.MLA):
        return 4
    if op in _LONG_MULTIPLY:
        return 5
    if op in (Op.B, Op.BL, Op.BX, Op.BL_LO):
        return 3
    return 1


def _operand2(ins: Instruction, carry: bool, extra: int) -> str:
```
with:
```python
    return ins.op is Op.LDM and ins.user and PC in ins.reglist


def in_cartridge(addr: int) -> bool:
    """Code at ``addr`` is fetched from the cartridge (through the prefetch buffer)."""
    return 0x08 <= addr >> 24 <= 0x0D


def stall_pc(ins: Instruction) -> str:
    """The pc mGBA's prefetch model sees for ``ins``, or 0 outside the cartridge."""
    if not in_cartridge(ins.addr):
        return "0u"
    return hexu(ins.addr + (4 if ins.mode is Mode.THUMB else 8))


def cycles(ins: Instruction) -> tuple[int, int, int]:
    """mGBA's static cost of ``ins`` as (cycles, S waits, N waits) of its code's region,
    when its condition holds; data waits, multiplies and jumps are added where they run."""
    op = ins.op
    k, s, n = 1, 1, 0  # the next instruction's sequential fetch
    if ins.mode is Mode.THUMB and op is Op.BL and ins.size == 4:
        k, s = 2, 2  # both halves
    if op in _LOADS or op in _STORES or op in (Op.LDM, Op.STM, Op.SWP, Op.SWPB, Op.MUL, Op.MLA) \
            or op in _LONG_MULTIPLY:
        s, n = s - 1, n + 1  # the fetch after a data access or a multiply is nonsequential
    if ins.shift is not None and ins.shift.reg is not None:
        k += 1  # a register-specified shift takes an internal cycle
    return k, s, n


def _operand2(ins: Instruction, carry: bool, extra: int) -> str:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
def _multiply(ins: Instruction) -> list[str]:
    value = f"{read(ins, ins.rm)} * {read(ins, ins.rs)}"
```
with:
```python
def _multiply(ins: Instruction) -> list[str]:
    wait = f"gba_mul_wait(ctx, {read(ins, ins.rs)}, 1, {int(ins.op is Op.MLA)}, {stall_pc(ins)});"
    value = f"{read(ins, ins.rm)} * {read(ins, ins.rs)}"
```

In `src/gbaport/lift/semantics.py`, replace:
```python
        value += f" + {read(ins, ins.rn)}"
    if ins.s:  # C is left alone (the ARM7TDMI leaves it meaningless), V unchanged
        value = f"gba_nz(ctx, {value})"
    return [f"ctx->r[{ins.rd}] = {value};"]


def _long_multiply(ins: Instruction) -> list[str]:
```
with:
```python
        value += f" + {read(ins, ins.rn)}"
    if ins.s:  # C is left alone (the ARM7TDMI leaves it meaningless), V unchanged
        value = f"gba_nz(ctx, {value})"
    return [wait, f"ctx->r[{ins.rd}] = {value};"]


def _long_multiply(ins: Instruction) -> list[str]:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
        product = f"(uint64_t){rm} * {rs}"
    body = [f"uint64_t p = {product};"]
    if accumulate:
```
with:
```python
        product = f"(uint64_t){rm} * {rs}"
    body = [f"gba_mul_wait(ctx, {rs}, {int(signed)}, {1 + int(accumulate)}, {stall_pc(ins)});",
            f"uint64_t p = {product};"]
    if accumulate:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
        body.append(f"{_STORES[ins.op]}(ctx, addr, v);")
    else:
```
with:
```python
        body.append(f"{_STORES[ins.op]}(ctx, addr, v);")
        body.append(f"gba_store_wait(ctx, addr, {int(ins.op is Op.STR)}, {stall_pc(ins)});")
    else:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
        body.append(f"uint32_t v = {_LOADS[ins.op]}(ctx, addr);")
        if written_back is not None:
```
with:
```python
        body.append(f"uint32_t v = {_LOADS[ins.op]}(ctx, addr);")
        body.append(f"gba_load_wait(ctx, addr, {int(ins.op is Op.LDR)}, {stall_pc(ins)});")
        if written_back is not None:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
            body.append(f"{target} = gba_read32(ctx, {slot});")
    if ins.writeback:
```
with:
```python
            body.append(f"{target} = gba_read32(ctx, {slot});")
    body.append(f"gba_multiple_wait(ctx, addr, {count}u, {int(ins.op is Op.LDM)}, {stall_pc(ins)});")
    if ins.writeback:
```

In `src/gbaport/lift/semantics.py`, replace:
```python
        f"uint32_t old = {load}(ctx, addr);",
        f"{store}(ctx, addr, {read(ins, ins.rm)});",
        f"ctx->r[{ins.rd}] = old;",
```
with:
```python
        f"uint32_t old = {load}(ctx, addr);",
        f"gba_load_wait(ctx, addr, {int(ins.op is Op.SWP)}, {stall_pc(ins)});",
        f"{store}(ctx, addr, {read(ins, ins.rm)});",
        f"gba_store_wait(ctx, addr, {int(ins.op is Op.SWP)}, {stall_pc(ins)});",
        f"ctx->r[{ins.rd}] = old;",
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);  /* GBA key bits, 1 = pressed */
void gba_screen(const GbaRuntime *rt, uint32_t *pixels);  /* 240x160, 0x00RRGGBB */
```
with:
```c
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);  /* GBA key bits, 1 = pressed */
void gba_waitcnt(GbaRuntime *rt, uint16_t value);  /* the wait states WAITCNT sets */
void gba_screen(const GbaRuntime *rt, uint32_t *pixels);  /* 240x160, 0x00RRGGBB */
```

In `src/gbaport/runtime/io.c`, replace:
```c
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        return;
```
with:
```c
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        gba_waitcnt(rt, IO(rt, offset));
        return;
```

In `src/gbaport/runtime/memory.c`, replace:
```c
    } else if (addr == DEBUG_ENABLE) {
        rt->debug_enabled = value == 0xC0DE;
    }
}

/* ---- reads ------------------------------------------------------------------------ */
```
with:
```c
    } else if (addr == DEBUG_ENABLE) {
        rt->debug_enabled = value == 0xC0DE;
    }
}

/* ---- wait states ------------------------------------------------------------------ */

/* The wait states of a 16- and 32-bit access to each region, nonsequential (N) and
 * sequential (S), as mGBA keeps them: fixed for the BIOS, RAM, I/O and video memory (EWRAM
 * 2 a halfword, palette and VRAM 1 more for a word), and set by WAITCNT for the
 * cartridge's three windows (N 4, 3, 2 or 8; S 2 or 1, 4 or 1, 8 or 1) and SRAM; a word
 * from the cartridge is two halfwords. Bit 14 turns the prefetch buffer on. */
void gba_waitcnt(GbaRuntime *rt, uint16_t value)
{
    static const uint8_t N16[16] = {0, 0, 2, 0, 0, 0, 0, 0, 4, 4, 4, 4, 4, 4, 4, 0};
    static const uint8_t N32[16] = {0, 0, 5, 0, 0, 1, 1, 0, 7, 7, 9, 9, 13, 13, 9, 0};
    static const uint8_t S16[16] = {0, 0, 2, 0, 0, 0, 0, 0, 2, 2, 4, 4, 8, 8, 4, 0};
    static const uint8_t S32[16] = {0, 0, 5, 0, 0, 1, 1, 0, 5, 5, 9, 9, 17, 17, 9, 0};
    static const uint8_t ROM_N[4] = {4, 3, 2, 8};
    static const uint8_t ROM_S[6] = {2, 1, 4, 1, 8, 1};
    GbaCtx *ctx = &rt->cpu;
    for (int r = 0; r < 16; r++) {
        ctx->n16[r] = N16[r], ctx->n32[r] = N32[r], ctx->s16[r] = S16[r], ctx->s32[r] = S32[r];
    }
    uint8_t sram = ROM_N[value & 3];
    for (int r = 14; r < 16; r++) {
        ctx->n16[r] = ctx->s16[r] = sram;
        ctx->n32[r] = ctx->s32[r] = (uint8_t)(2 * sram + 1);
    }
    for (int ws = 0; ws < 3; ws++) {
        uint8_t n = ROM_N[(value >> (2 + 3 * ws)) & 3];
        uint8_t s = ROM_S[2 * ws + ((value >> (4 + 3 * ws)) & 1)];
        for (int r = 8 + 2 * ws; r < 10 + 2 * ws; r++) {
            ctx->n16[r] = n, ctx->s16[r] = s;
            ctx->n32[r] = (uint8_t)(n + 1 + s), ctx->s32[r] = (uint8_t)(2 * s + 1);
        }
    }
    ctx->prefetch = (value >> 14) & 1;
}

/* ---- reads ------------------------------------------------------------------------ */
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
    ctx->bank_r13_14[gba_bank(GBA_MODE_SVC)][0] = 0x03007FE0u;
}
```
with:
```c
    ctx->bank_r13_14[gba_bank(GBA_MODE_SVC)][0] = 0x03007FE0u;
    gba_waitcnt(rt, rt->io[GBA_REG_WAITCNT >> 1]);
}
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
    gba_reset_io(rt);
    gba_audio_reset(rt);
```
with:
```c
    gba_reset_io(rt);
    gba_waitcnt(rt, rt->io[GBA_REG_WAITCNT >> 1]);
    gba_audio_reset(rt);
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
    ctx->r[14] = BIOS_IRQ_RETURN;
    ctx->cycles += 40;  /* the BIOS's IRQ entry and exit */
    rt->bios_bus = 0xE25EF004u;  /* the opcode at 0x13C, fetched while the handler runs */
```
with:
```c
    ctx->r[14] = BIOS_IRQ_RETURN;
    /* The BIOS's IRQ entry and exit as mGBA counts them (its stand-in BIOS's code): the
     * jump to 0x18 (2), stmfd of 6 registers (7), mov and add (2), ldr pc (5), ldmfd (8) and
     * subs pc (1), whose jump back is taken to be to Thumb code in the cartridge (2 + N + S);
     * the handler's own return to the BIOS is the recompiled code's. */
    ctx->cycles += 25 + 2 + ctx->n16[8] + ctx->s16[8];
    ctx->prefetched = 0;
    rt->bios_bus = 0xE25EF004u;  /* the opcode at 0x13C, fetched while the handler runs */
```

- [ ] **Step 4: Run the whole suite**

Every test program is built again (the runtime and the lifter changed), which can take several minutes.

Run: `uv run pytest`
Expected: 833 passed (772 + 61).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/lift src/gbaport/runtime tests/gbaroms/cycles.c tests/gbaroms/hblank_irq.c tests/gbaroms/interrupts.c tests/runtime/test_timing.py
git commit -m "feat: code takes as many cycles as in mGBA: wait states, the prefetch buffer, jumps, interrupts"
```

---

### Task 5: DMA and the EEPROM take as long as in mGBA

- **DMA.** A transfer costs 3 cycles to start. Each unit then costs 2 cycles plus the wait states of its source and destination: nonsequential for the first unit, sequential after. The cost is added unit by unit, so the EEPROM sees each bit arrive when it does in mGBA. A sound FIFO's 4 words stay free of charge (Plan 6).
- **The EEPROM** is busy for 115000 cycles from the last data bit of a block it writes, as in mGBA (GBATEK gives about 6.6 ms); until then it reads 0.
- **Flash** stays instant. mGBA makes it slow, but then fails jsmolka's Flash tests, which this runtime passes (Known limitations).

**Files:**
- Modify: `src/gbaport/runtime/dma.c`, `src/gbaport/runtime/save.c`, `src/gbaport/runtime/gba_runtime.h`
- Modify: `tests/gbaroms/cycles.c` (two DMA scenes)
- Create: `tests/gbaroms/hblank_dma.c`, `tests/gbaroms/eeprom_busy.c`
- Test: `tests/runtime/test_timing.py`

**Interfaces:**
- Consumes: the wait-state tables and `gba_region` (Task 4); `drawn`, `SETTINGS`, `SCENES` (Task 4).
- **Produces:** `GbaSave.eeprom_ready`; `SCENES` gains `dma rom to ewram` and `dma ewram to vram`; `DMA_SLACK` (2 cycles).

- [ ] **Step 1: Write the failing tests and the test ROMs**

In `tests/gbaroms/cycles.c`, replace:
```c

static const uint16_t SETTINGS[4] = {0x0000, 0x4317, 0x0317, 0x4314};
```
with:
```c

/* DMA 3, while the CPU waits. The timer is read a few instructions later: mGBA starts a
 * transfer 3 cycles after it is asked for, and the CPU runs on until then. */
static uint32_t dma(const volatile void *from, volatile void *to, uint32_t control)
{
    uint16_t t = TM0;
    REG_DMA_SAD(3) = (uint32_t)from;
    REG_DMA_DAD(3) = (uint32_t)to;
    REG_DMA_CNT(3) = control;
    __asm__ volatile("nop\nnop\nnop\nnop\nnop\nnop\nnop\nnop" ::: "memory");
    return (uint16_t)(TM0 - t);
}

static const uint16_t SETTINGS[4] = {0x0000, 0x4317, 0x0317, 0x4314};
```

In `tests/gbaroms/cycles.c`, replace:
```c
        record(arm_iwram(EWRAM_WORDS));
    }
```
with:
```c
        record(arm_iwram(EWRAM_WORDS));
        record(dma(rom_words, EWRAM_WORDS, 0x84000040));  /* 64 words */
        record(dma(EWRAM_WORDS, VRAM16 + 0x8000, 0x80000040));  /* 64 halfwords */
    }
```

Create `tests/gbaroms/eeprom_busy.c`:
```c
/* How long the EEPROM is busy after a block is written: cycles from the write's DMA until
 * the chip reads ready, timed with timers 0 and 1 counting cycles together, and the reads
 * it took. Both are drawn like the cycles test's counts. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "EEPROM_V124";

#define EEPROM 0x0D000000u
#define VRAM16 ((volatile uint16_t *)0x06000000)

static uint16_t bits[96];

static uint32_t now(void)
{
    for (;;) {
        uint16_t high = REG_TM_CNT_L(1), low = REG_TM_CNT_L(0);
        if (REG_TM_CNT_L(1) == high)
            return (uint32_t)high << 16 | low;
    }
}

static void draw(int slot, uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
}

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    REG_TM_CNT_H(1) = 0x0084;  /* counts timer 0's overflows */
    REG_TM_CNT_H(0) = 0x0080;
    unsigned n = 0;
    bits[n++] = 1;
    bits[n++] = 0;  /* write */
    for (int b = 0; b < 14; b++)
        bits[n++] = 0;  /* block 0 of the 8 KiB chip */
    for (int b = 0; b < 64; b++)
        bits[n++] = b & 1;
    bits[n++] = 0;
    __asm__ volatile("" ::: "memory");
    uint32_t start = now();
    REG_DMA_SAD(3) = (uint32_t)bits;
    REG_DMA_DAD(3) = EEPROM;
    REG_DMA_CNT(3) = n | 0x80000000u;  /* 16-bit units, immediately */
    uint32_t reads = 1;
    while (!(MEM16(EEPROM) & 1))
        reads++;
    draw(0, now() - start);
    draw(1, reads);
    for (int i = 0; i < 2; i++) {  /* two whole pictures with both counts */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
```

Create `tests/gbaroms/hblank_dma.c`:
```c
/* How much an HBlank DMA slows the CPU: the iterations of a busy loop from line 20 to line
 * 60, without and with DMA 0 copying 4 words at every HBlank, drawn like the cycles test's
 * counts. */
#include "testlib.h"

#define VRAM16 ((volatile uint16_t *)0x06000000)
#define EWRAM_WORDS ((volatile uint32_t *)0x02000000)

static uint32_t iwram_words[8] __attribute__((section(".iwram.data")));

static void draw(int slot, uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
}

static uint32_t loops_from_20_to_60(void)
{
    uint32_t loops = 0;
    wait_vcount(20);
    while (REG_VCOUNT != 60)
        loops++;
    return loops;
}

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    draw(0, loops_from_20_to_60());
    wait_vcount(0);
    REG_DMA_SAD(0) = (uint32_t)EWRAM_WORDS;
    REG_DMA_DAD(0) = (uint32_t)iwram_words;
    REG_DMA_CNT(0) = 4 | 0x80000000u | 0x26000000u | 0x00600000u;  /* HBlank, repeat, 32-bit, reload */
    draw(1, loops_from_20_to_60());
    REG_DMA_CNT_H(0) = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with both counts */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
```

Create `tests/runtime/test_timing.py` (replacing the current version):
```python
"""Code takes as many cycles as in mGBA: the cycles test ROM times kinds of code with
timer 0 under four WAITCNT settings, natively and in mGBA, and draws the counts. An
interrupt takes about as long, and DMA and the EEPROM take as long too.

mGBA starts a DMA 3 cycles after it is asked for and lets the CPU run on until then; here
the CPU waits those 3 cycles at once, so a transfer may end a cycle or two later than in
mGBA."""

import pytest
from mgbaref import mgba_picture
from rendertest import our_picture
from romtest import build_test_rom

SETTINGS = ["0x0000", "0x4317", "0x0317", "0x4314"]  # default; fast, prefetch; no prefetch; BT4E's
SCENES = ["thumb alu", "thumb ldr iwram", "thumb ldr ewram", "thumb ldr rom", "thumb ldr vram",
          "thumb str iwram", "thumb str ewram", "thumb str vram", "thumb ldm/stm ewram",
          "thumb ldm/stm iwram", "thumb mul small", "thumb mul large", "thumb branches",
          "arm in rom", "arm in iwram", "dma rom to ewram", "dma ewram to vram"]
DMA_SLACK = 2  # cycles (see above)


def drawn(picture: list[int], count: int) -> list[int]:
    """The counts a test ROM drew: two pixels each, bits 0-14 then 15-29."""
    return [picture[2 * k] | picture[2 * k + 1] << 15 for k in range(count)]


@pytest.fixture(scope="module")
def measured() -> tuple[list[int], list[int]]:
    rom, count = build_test_rom("cycles"), len(SETTINGS) * len(SCENES)
    return drawn(our_picture(rom, 10), count), drawn(mgba_picture(rom.data, 10), count)


@pytest.mark.parametrize("setting", range(len(SETTINGS)), ids=SETTINGS)
@pytest.mark.parametrize("scene", range(len(SCENES)), ids=SCENES)
def test_code_takes_as_many_cycles_as_in_mgba(measured, setting, scene):
    ours, mgba = measured
    k = setting * len(SCENES) + scene
    if SCENES[scene].startswith("dma"):
        assert abs(ours[k] - mgba[k]) <= DMA_SLACK, (ours[k], mgba[k])
    else:
        assert ours[k] == mgba[k]


def test_an_hblank_interrupt_slows_the_cpu_about_as_much_as_in_mgba():
    """Iterations of a busy loop over 40 lines, without and with an interrupt at every
    HBlank. Each interrupt costs here within 4 cycles of mGBA (README, Known limitations)."""
    rom = build_test_rom("hblank_irq")
    ours, mgba = drawn(our_picture(rom, 20), 3), drawn(mgba_picture(rom.data, 20), 3)
    assert ours[0] == mgba[0]  # no interrupts: the same loop
    assert ours[2] == mgba[2] == 41  # line 19's HBlank and the 40 after it
    cycles_a_loop = 40 * 1232 / mgba[0]
    assert abs(ours[1] - mgba[1]) * cycles_a_loop <= 4 * mgba[2]


def test_an_hblank_dma_slows_the_cpu_as_much_as_in_mgba():
    """Iterations of a busy loop over 40 lines, without and with 4 words at every HBlank."""
    rom = build_test_rom("hblank_dma")
    ours, mgba = drawn(our_picture(rom, 20), 2), drawn(mgba_picture(rom.data, 20), 2)
    assert ours[0] == mgba[0]
    assert abs(ours[1] - mgba[1]) <= 1  # a loop takes many more cycles than DMA_SLACK


def test_the_eeprom_is_busy_as_long_as_in_mgba():
    """Cycles from writing a block (by DMA) until the EEPROM is ready, and the reads that
    took."""
    rom = build_test_rom("eeprom_busy")
    ours, mgba = drawn(our_picture(rom, 30), 2), drawn(mgba_picture(rom.data, 30), 2)
    assert abs(ours[0] - mgba[0]) <= DMA_SLACK
    assert ours[1] == mgba[1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_timing.py`
Expected: FAIL — 10 failed, 61 passed.
- The 8 DMA scenes fail with `AssertionError: (ours, mGBA)`, for example `(237, 877)`.
- `test_an_hblank_dma_slows_the_cpu_as_much_as_in_mgba` fails.
- `test_the_eeprom_is_busy_as_long_as_in_mgba` fails: the EEPROM is ready at once.

- [ ] **Step 3: DMA's and the EEPROM's timing**

In `src/gbaport/runtime/dma.c`, replace:
```c
 *
 * A transfer's time is added to the CPU's cycles, except a FIFO's 4 words: those run from
 * a timer's overflow inside the scheduler, and two FIFOs on a timer that overflows every
 * cycle would then ask for more time than passes, so the game would never run again and
 * the sound would run ahead of the frames. At the rates games play (two FIFOs at 13379 to
 * 32768 bytes a second), the time left out is 0.1% to 0.3% of the CPU's. */
#include "gba_runtime.h"
```
with:
```c
 *
 * The CPU waits while a transfer runs, as long as in mGBA: 3 cycles to start, then for
 * each unit 2 cycles and the wait states of its source and destination (nonsequential for
 * the first, sequential after it), unit by unit, so a unit sees the time it is copied at
 * (the EEPROM's busy time counts from its last data bit). A FIFO's 4 words are not added:
 * they run from a timer's overflow inside the scheduler, and two FIFOs on a timer that
 * overflows every cycle would then ask for more time than passes, so the game would never
 * run again and the sound would run ahead of the frames. At the rates games play (two
 * FIFOs at 13379 to 32768 bytes a second), the time left out is 0.1% to 0.3% of the CPU's. */
#include "gba_runtime.h"
```

In `src/gbaport/runtime/dma.c`, replace:
```c
        gba_eeprom_dma(rt, d->count);  /* the length tells the EEPROM's size */
    for (uint32_t i = 0; i < count; i++) {
        if (size == 4)
```
with:
```c
        gba_eeprom_dma(rt, d->count);  /* the length tells the EEPROM's size */
    if (!fifo)  /* see the top of the file */
        ctx->cycles += 3;
    for (uint32_t i = 0; i < count; i++) {
        uint32_t sr = gba_region(d->src), dr = gba_region(d->dst);
        if (size == 4)
```

In `src/gbaport/runtime/dma.c`, replace:
```c
        d->dst += (uint32_t)dst_step;
    }
    if (!fifo)  /* see the top of the file */
        ctx->cycles += 4 + 2 * (uint64_t)count;
    int timing = (control >> 12) & 3;
```
with:
```c
        d->dst += (uint32_t)dst_step;
        if (fifo)
            continue;
        if (size == 4)
            ctx->cycles += 2u + (i ? ctx->s32[sr] + ctx->s32[dr] : ctx->n32[sr] + ctx->n32[dr]);
        else
            ctx->cycles += 2u + (i ? ctx->s16[sr] + ctx->s16[dr] : ctx->n16[sr] + ctx->n16[dr]);
    }
    int timing = (control >> 12) & 3;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    uint32_t eeprom_out_left; /* bits still to come: 4 ignored, then 64 */
} GbaSave;
```
with:
```c
    uint32_t eeprom_out_left; /* bits still to come: 4 ignored, then 64 */
    uint64_t eeprom_ready;     /* busy writing a block until this cycle */
} GbaSave;
```

In `src/gbaport/runtime/save.c`, replace:
```c
 *   KiB) bank switching. It identifies as a Panasonic (64 KiB) or Sanyo (128 KiB) chip.
 *   Writes can only clear bits, as on the real chip; erasing sets them again.
 * - EEPROM: 512 bytes (6-bit block addresses) or 8 KiB (14-bit) behind 0x0D000000, one bit
 *   per halfword, normally by DMA. Requests: "11" + address + "0" reads a 64-bit block,
 *   which then comes out as 4 ignored bits and 64 data bits; "10" + address + 64 bits +
 *   "0" writes one. Reads report ready (1) when no block is coming out. The chip's size is
 *   not in the ROM: it follows from the first DMA's length (9 or 73 halfwords: 512 bytes;
```
with:
```c
 *   KiB) bank switching. It identifies as a Panasonic (64 KiB) or Sanyo (128 KiB) chip.
 *   Writes can only clear bits, as on the real chip; erasing sets them again, and both
 *   take no time. (mGBA makes a byte take 650 cycles and a sector 30000, with the last
 *   sector erased reading 0x5F meanwhile; it then fails jsmolka's Flash tests, which the
 *   real chip and this model pass.)
 * - EEPROM: 512 bytes (6-bit block addresses) or 8 KiB (14-bit) behind 0x0D000000, one bit
 *   per halfword, normally by DMA. Requests: "11" + address + "0" reads a 64-bit block,
 *   which then comes out as 4 ignored bits and 64 data bits; "10" + address + 64 bits +
 *   "0" writes one, after which the chip is busy for 115000 cycles from the last data bit
 *   (about 6.9 ms, as in mGBA; GBATEK gives about 6.6). Reads report ready (1) when it is
 *   not, and no block is coming out. The chip's size is
 *   not in the ROM: it follows from the first DMA's length (9 or 73 halfwords: 512 bytes;
```

In `src/gbaport/runtime/save.c`, replace:
```c
        block = eeprom_bits(s, 2, bits) & ((s->size / 8) - 1);
    if (command == 3 && s->eeprom_count == 2 + bits + 1) {  /* read request */
```
with:
```c
        block = eeprom_bits(s, 2, bits) & ((s->size / 8) - 1);
    if (command == 2 && s->eeprom_count == 2 + bits + 64)  /* the last data bit */
        s->eeprom_ready = rt->cpu.cycles + 115000;
    if (command == 3 && s->eeprom_count == 2 + bits + 1) {  /* read request */
```

In `src/gbaport/runtime/save.c`, replace:
```c
    if (!s->eeprom_out_left)
        return 1;  /* ready */
    s->eeprom_out_left--;
```
with:
```c
    if (!s->eeprom_out_left)
        return rt->cpu.cycles >= s->eeprom_ready;  /* 1: ready */
    s->eeprom_out_left--;
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 843 passed (833 + 10).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime tests/gbaroms/cycles.c tests/gbaroms/hblank_dma.c tests/gbaroms/eeprom_busy.c tests/runtime/test_timing.py
git commit -m "feat: DMA and the EEPROM take as long as in mGBA"
```

---

### Task 6: README, spec, and the user's game against mGBA

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: no code.

- [ ] **Step 1: Write the documentation**

In `README.md`, replace:
```markdown
dummy video and sound drivers, so no window opens and nothing plays.

The renderer and sound tests compare every picture, pixel for pixel, and every sound,
sample by sample, with mGBA's: they build mGBA 0.10.5's GBA core (MPL-2.0, a development
tool only; nothing ships it) from source the first time, with the same CMake, Ninja and
clang as SDL3, into the same cache folder. Because the recompiled code's timing is an
estimate, a change in a sound may come up to two samples (61 microseconds) earlier or
later than in mGBA. A picture that differs is written next to mGBA's in
`gbaport-romcache/pictures`, a sound that differs next to mGBA's in
`gbaport-romcache/sounds` (WAV files), and the test's message names the files.

## Commands
```
with:
```markdown
dummy video and sound drivers, so no window opens and nothing plays.

The renderer, sound and timing tests compare every picture, pixel for pixel, every
sound, sample by sample, and the cycles kinds of code take with mGBA's: gbaport builds
mGBA 0.10.5's GBA core (MPL-2.0, a development tool only; no game ships it) from source
the first time, with the same CMake, Ninja and clang as SDL3, into the same cache folder.
Because interrupts reach recompiled code only at loops and returns, a change in a sound
may come up to two samples (61 microseconds) earlier or later than in mGBA. A picture
that differs is written next to mGBA's in `gbaport-romcache/pictures`, a sound that
differs next to mGBA's in `gbaport-romcache/sounds` (WAV files), and the test's message
names the files.

## Commands
```

In `README.md`, replace:
```markdown
    uv run gbaport recompile roms/mygame.gba [--out games/XXXX/generated]
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]

If Windows Application Control blocks the `gbaport.exe` launcher, run the same commands
```
with:
```markdown
    uv run gbaport recompile roms/mygame.gba [--out games/XXXX/generated]
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]

If Windows Application Control blocks the `gbaport.exe` launcher, run the same commands
```

In `README.md`, replace:
```markdown
- `--press FRAME:KEYS`: hold KEYS from that frame on (repeatable). KEYS are A, B, SELECT,
  START, RIGHT, LEFT, UP, DOWN, R and L joined with `+`, or `none`;
- `--registers`: print the CPU registers when the run ends;
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second).

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
```
with:
```markdown
- `--press FRAME:KEYS`: hold KEYS from that frame on (repeatable). KEYS are A, B, SELECT,
  START, RIGHT, LEFT, UP, DOWN, R and L joined with `+`, or `none`;
- `--input FILE`: hold the keys an input file names (below), any number of changes;
- `--registers`: print the CPU registers when the run ends;
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second);
- `--hashes PATH`: write a hash of each frame's picture, a line a frame (`gbaport verify`
  compares them with mGBA's).

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
```

In `README.md`, replace:
```markdown

## Recording traces with mGBA
```
with:
```markdown

The game's time is counted as mGBA counts it: each instruction costs its fetches at the
wait states WAITCNT sets for the memory it runs from, data accesses cost their memory's
wait states (through mGBA's model of the cartridge's prefetch buffer), and DMA and the
EEPROM take as long as in mGBA. So the game reaches each picture when it does in mGBA,
give or take a frame where an interrupt comes in at a loop or a return instead of at once.

## Checking a game against mGBA

`gbaport verify` builds a headless program for the game (into `build/<game_code>-verify`)
and plays it, and the game in mGBA, from power-on with a blank save, for `--frames`
frames (600 by default), holding the keys an input file names (`--input`). It compares
the pictures frame by frame:

    verified 900 frames: 472 pictures in the same order, at most 1 frame apart

A picture may come up to `--slack` frames (1 by default) earlier or later than in mGBA,
and a picture only one of them shows may last that long. Otherwise the report names the
frame where the two part, writes both pictures there side by side into a PNG file in the
same folder, and the exit status is 1. The first frame is left out: the game starts
halfway down it.

An input file holds the keys, a line each time they change, held from that frame on:

    # the title menu
    900 A
    906 none
    3900 RIGHT+A

The headless and window programs play one with `--input FILE`.

## Recording traces with mGBA
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
  palette and ROM; I/O-register writes call handlers (DMA start, timer reload, IRQ ack).
- **Timing.** Not cycle-accurate. Each generated basic block adds a compile-time cycle
  estimate to `ctx->cycles`; loop back-edges and function returns check
  `ctx->cycles >= ctx->next_event` and run the scheduler, which advances scanlines and
```
with:
```markdown
  palette and ROM; I/O-register writes call handlers (DMA start, timer reload, IRQ ack).
- **Timing.** Counted as mGBA counts it (Plan 7a): each instruction adds its fetches at
  the wait states WAITCNT sets, data accesses add their memory's waits (through mGBA's
  model of the prefetch buffer) and DMA its transfer time, each before the next memory
  access sees the time; loop back-edges and function returns check
  `ctx->cycles >= ctx->next_event` and run the scheduler, which advances scanlines and
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
- mGBA 0.10.5's GBA core, built from source by the tests (16-bit colour, no dependencies)
  as the renderer's reference (Plan 5) and the sound's (Plan 6).

## Risks
```
with:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
- mGBA 0.10.5's GBA core, built from source by gbaport (16-bit colour, no dependencies)
  as the renderer's reference (Plan 5), the sound's (Plan 6), and the timing's and
  `gbaport verify`'s (Plan 7a).

## Risks
```

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest`
Expected: 843 passed.

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 3: Verify the user's game against mGBA**

Run, from the repo root:

```bash
uv run python -m gbaport.cli verify roms/mygame.gba --frames 900; echo "exit $?"
uv run python -m gbaport.cli verify roms/mygame.gba --frames 900 --slack 0; echo "exit $?"
```

Expected (validated before this plan was approved):
- `verified 900 frames: 472 pictures in the same order, at most 1 frame apart`, exit 0.
- `the pictures part at frame 863 (mGBA's frame 863)` and `wrote build\BT4E-verify\frame-863.png (ours, then mGBA's)`, exit 1: from frame 45 to frame 862 every picture comes on the same frame as in mGBA.
- `build/` is ignored by git; the program, the hash files and the PNG stay on this machine.

Record the lines in the ledger.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: gbaport verify, input files, and the timing mGBA counts"
```

---

## Done criteria for Plan 7a

- `uv run pytest` passes 843 tests and `uv run ruff check src tests` is clean.
- **mGBA is a gbaport tool.** It plays input files, hashes every frame's picture, and keeps serving the renderer and sound tests.
- **The hosts** play input files with any number of key changes, and write the same picture hashes.
- **`gbaport verify`** compares a game's pictures with mGBA's, names the frame where they part (with a PNG), and handles a game that stops itself, a native build that fails, and long replays.
- **Code takes as many cycles as in mGBA:**
  - every Thumb and ARM scene of the cycles test, under four WAITCNT settings;
  - DMA within 2 cycles, the EEPROM's busy time within 2 cycles, with the same number of reads;
  - an interrupt within 4 cycles.
- **The user's game** verifies for 900 frames from power-on, every picture at most 1 frame from mGBA's.
