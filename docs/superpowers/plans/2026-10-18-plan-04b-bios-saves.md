# Plan 4b: BIOS Functions and Saves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompiled games get the rest of the BIOS and their save chip. The BIOS part covers arithmetic, memory copies and fills, affine set-ups and decompression. The save chip can be SRAM, Flash or EEPROM, and the headless program stores it in a save file. With this plan, the user's game (BT4E) boots and runs.

**Architecture:**
- **BIOS** (`src/gbaport/runtime/bios_*.c`). `bios.c` keeps the dispatcher and the small calls.
  - `bios_math.c`: Div, DivArm, Sqrt, ArcTan, ArcTan2 and MidiKey2Freq.
  - `bios_memory.c`: CpuSet, CpuFastSet, BitUnPack, BgAffineSet and ObjAffineSet.
  - `bios_decompress.c`: LZ77, Huffman, run-length and the difference filters.
  - The sound driver calls are ignored with a warning until sound arrives (P6).
  - Results follow GBATEK. mGBA's HLE BIOS settles the corners GBATEK leaves open, such as division by zero.
- **Save chip** (`save.c`).
  - SRAM and Flash sit on the 8-bit bus at 0x0E000000. Flash runs a command state machine: ID, erase, write, bank switch.
  - EEPROM sits behind 0x0D000000. It is driven one bit per halfword by DMA, and its size follows from the first DMA's length.
  - `gba_rom.c` records which chip the game has. The source is `game.toml`'s `[rom] save` if set, otherwise the ROM's library ID string.
  - The headless host loads and stores the chip's bytes in a save file (`--save`, default `<rom>.sav`). It writes once a second while they change and at the end, through a temporary file.
- **Reference values** (`tests/biosref.py`). Python implementations of the BIOS functions, plus compressors for every BIOS stream format, written from GBATEK independently of the C code. Test ROMs receive cases from them through a generated `testdata.h`.
- **Builds Windows refuses.** Smart App Control judges each new program by its content and refuses some for good, and identical sources give identical files. `compile_native` therefore checks that the program starts, and links it again with an unused random string (`gba_salt.c`) until Windows takes it.

**Tech Stack:** C11 (clang `-std=c11 -O2 -Wall -Werror`), Python 3.13 (stdlib at runtime), pytest. LLVM 23.1.3 builds the test ROMs.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`. This plan implements roadmap row P4b, the "Runtime model" Saves bullet, key decision 8 (BIOS reimplemented in C) and the Runtime row of "Verification strategy".

## Global Constraints

- Work on branch `feat/plan-04b-bios-saves`, cut from `main`.
- **Dependencies.** The Python runtime uses only the standard library; this plan adds no dependencies.
- **C code.**
  - Generated code and the runtime are C11 and compile warning-free with `clang -std=c11 -O2 -Wall -Werror -Wno-unused-label`.
  - The runtime uses only `<stdint.h>`, `<string.h>`, `<setjmp.h>`, `<stdarg.h>`, `<stdio.h>` and `<math.h>` (for `pow`).
- **Guest memory** is reached only through the `gba_read*`/`gba_write*` accessors, the BIOS functions included (spec, key decision 3).
- **No ROM-derived bytes in git.**
  - Test ROMs and their data are generated at test time.
  - `games/BT4E/game.toml` holds addresses and the ROM's SHA-1 only, which the spec allows.
  - Save files (`*.sav`) are git-ignored.
- **Commits** are plain, authored as `Ken <ahmadsoud63@gmail.com>`, with no trailer of any kind.
- **This machine.** Windows Smart App Control blocks the `gbaport.exe` launcher, so steps run the CLI as `uv run python -m gbaport.cli ...`.

## Review Focus

1. **A save written just before the game hits a runtime error.** Games save and then run into code discovery missed. The bytes written must still reach the save file. Pinned in Task 6 (`test_a_save_written_before_a_runtime_error_reaches_the_file`).
2. **A save file of another size from elsewhere.** Examples: a 64 KiB SRAM file from another emulator, or a truncated file. It must be refused before the run and left untouched, never overwritten. Pinned in Task 6 (`test_a_save_file_of_another_size_is_left_alone`).
3. **Division by zero, and INT_MIN / -1.** The real BIOS hangs on the first; games do it by accident. The run must get mGBA's answer with a warning, not a crash. Pinned in Task 3 (the `div_cases` include both).
4. **Decompressing into VRAM.** The "Vram" variants must write halfwords; byte writes to BG VRAM would duplicate each byte. Pinned in Task 5 (every Vram case decompresses into BG VRAM and is compared byte for byte).
5. **The EEPROM's size.** It must come from the first DMA's length (9/73 halfwords: 512 bytes; 17/81: 8 KiB) or from an existing save file's size, and the next run must read the same blocks back. Pinned in Task 7 (both sizes, twice each, with the save file of the first run).

## Known limitations (deliberate; later plans)

- **Sound.** The BIOS sound driver (SWI 0x1A-0x1E, 0x20-0x24, 0x28-0x2A) is ignored with a warning until sound arrives in P6.
- **The affine calls** use a computed sine table, round(16384 sin(2 pi i / 256)). The BIOS has its own table, so results may differ from it in the lowest bit; the lockstep comparison in P7 will show any difference.
- **EEPROM by CPU writes.** A game that drives its EEPROM with CPU writes instead of DMA gets the 512-byte chip unless a save file says otherwise.
- **Flash chip types.** Atmel Flash chips (128-byte page writes) are not modelled. Flash identifies as a Panasonic chip (64 KiB) or a Sanyo chip (128 KiB).
- **Cartridge extras.** The real-time clock and other cartridge GPIO devices (used by Pokémon) are not modelled.
- **MultiBoot** reports failure: there is no link cable.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/gbaport/runtime/bios.c` | SWI dispatch; resets, waits, Stop; GetBiosChecksum, SoundBias, MultiBoot, HardReset, CustomHalt; sound-driver warning |
| `src/gbaport/runtime/bios_math.c` (new) | Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq |
| `src/gbaport/runtime/bios_memory.c` (new) | CpuSet, CpuFastSet, BitUnPack, BgAffineSet, ObjAffineSet, the sine table |
| `src/gbaport/runtime/bios_decompress.c` (new) | LZ77, Huffman, run-length, difference filters (Wram/Vram variants) |
| `src/gbaport/runtime/save.c` (new) | SRAM, Flash, EEPROM; the host's save API |
| `src/gbaport/runtime/gba_runtime.h`, `runtime.c`, `memory.c`, `dma.c` | Warnings, HardReset, the save chip's place in the memory map, the EEPROM DMA length |
| `src/gbaport/runtime/host_headless.c` | `--save PATH`: load, store once a second and at the end |
| `src/gbaport/native/build.py` | The save type in `gba_rom.c`; rebuilds of programs Windows refuses |
| `src/gbaport/analysis/analyze.py`, `src/gbaport/cli.py` | `Analysis.save`: `game.toml`'s `[rom] save`, else the library ID |
| `tests/biosref.py` (new) | Reference BIOS functions and stream compressors |
| `tests/romtest.py` | `testdata.h` for test ROMs; `--save` for runs |
| `tests/gbaroms/*` | Test ROMs for each group of calls and each save chip |
| `tests/runtime/test_*.py`, `tests/test_native_build.py` | The tests |
| `games/BT4E/game.toml` (new) | The user's game: 70 entries the analysis cannot find by itself |

---

### Task 1: Builds that Windows refuses are linked again

**Files:**
- Modify: `src/gbaport/native/build.py` (`compile_native` checks that the program starts)
- Modify: `tests/romtest.py`. The kit's own rebuild loop (Plan 4a's workaround) goes, because `compile_native` now does it for every build.
- Test: `tests/test_native_build.py`

**Interfaces:**
- Consumes: `compile_native`, `generated_sources`, `write_sources` (Plan 4a).
- Produces:
  - `_starts(program) -> bool`: starts the program without arguments, so it prints its usage. It returns False only for Windows' WinError 4551, and True on other systems.
  - `SALTED_REBUILDS = 5`.
  - `compile_native` links again with `obj/gba_salt.c` (`const char gba_build_salt[] = "<random>";`) until the program starts, and raises `ToolchainError` after 5 refusals.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-04b-bios-saves
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_native_build.py`:
```python
from romtest import build_test_rom

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage


def test_a_build_windows_refuses_is_linked_again_with_a_salt(tmp_path, monkeypatch):
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    verdicts = iter([False, True])  # Smart App Control refuses the first file, takes the next
    builds = []

    def starts(program):
        builds.append(program.read_bytes())
        return next(verdicts)

    monkeypatch.setattr(native, "_starts", starts)
    program = native.compile_native(tmp_path / "generated", tmp_path / "build", "game")
    assert len(builds) == 2 and builds[0] != builds[1]  # the salt changed the program's bytes
    assert program.read_bytes() == builds[1]
    assert (tmp_path / "build" / "obj" / "gba_salt.c").exists()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_native_build.py -v`
Expected: FAIL — `AttributeError: <module 'gbaport.native.build' ...> has no attribute '_starts'`

- [ ] **Step 4: Check that a build starts, and link it again if Windows refuses it**

In `tests/romtest.py`, replace:
```python
import hashlib
import os
import struct
```
with:
```python
import hashlib
import struct
```

In `tests/romtest.py`, replace:
```python
def native_program(rom: TestRom) -> Path:
    """Recompile ``rom`` and build it with the headless host (cached by the C sources).

    Windows' Smart App Control refuses some freshly built programs for good, judging each
    file by its content. A build it refuses is made again with a different ``gba_salt.c``,
    which changes the program's bytes but not what it does.
    """
    image = RomImage(rom.data)
```
with:
```python
def native_program(rom: TestRom) -> Path:
    """Recompile ``rom`` and build it with the headless host (cached by the C sources)."""
    image = RomImage(rom.data)
```

In `tests/romtest.py`, replace:
```python
    built = folder / "program.txt"  # written last: the build finished
    if built.exists() and _starts(Path(built.read_text(encoding="utf-8"))):
        return Path(built.read_text(encoding="utf-8"))
    native.write_sources(files, folder / "generated")
    for _ in range(5):
        salt = os.urandom(8).hex()
        (folder / "generated" / "gba_salt.c").write_text(
            f'const char gba_build_salt[] = "{salt}";\n', encoding="utf-8"
        )
        program = native.compile_native(folder / "generated", folder / f"build-{salt}", "game")
        if _starts(program):
            break
    built.write_text(str(program), encoding="utf-8")
    return program


def _starts(program: Path) -> bool:
    """Whether Windows lets ``program`` start (without arguments it prints its usage)."""
    try:
        subprocess.run([str(program)], capture_output=True, timeout=30, check=False)
    except OSError as error:
        if getattr(error, "winerror", None) != 4551:
            raise
        return False
    return True
```
with:
```python
    built = folder / "program.txt"  # written last: the build finished
    if not built.exists():
        native.write_sources(files, folder / "generated")
        program = native.compile_native(folder / "generated", folder / "build", "game")
        built.write_text(str(program), encoding="utf-8")
    return Path(built.read_text(encoding="utf-8"))
```

In `src/gbaport/native/build.py`, replace:
```python
CFLAGS = ("-std=c11", "-O2", "-Wall", "-Werror", "-Wno-unused-label")
```
with:
```python
CFLAGS = ("-std=c11", "-O2", "-Wall", "-Werror", "-Wno-unused-label")
SALTED_REBUILDS = 5  # how often a build Windows refuses to start is made again
```

In `src/gbaport/native/build.py`, replace:
```python
    program = out / (name + (".exe" if os.name == "nt" else ""))
    result = subprocess.run(
        [clang, *(str(obj) for obj in compiled), "-o", str(program)],
        capture_output=True, text=True, check=False,
```
with:
```python
    program = out / (name + (".exe" if os.name == "nt" else ""))
    _link(clang, compiled, program)
    for _ in range(SALTED_REBUILDS):
        if _starts(program):
            return program
        salt = objects / "gba_salt.c"
        salt.write_text(f'const char gba_build_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _link(clang, [*compiled, compile_unit(salt)], program)
    if _starts(program):
        return program
    raise ToolchainError(
        f"Windows refused to start {program} after {SALTED_REBUILDS} rebuilds "
        "(Smart App Control): turn it off to run programs you build"
    )


def _link(clang: str, objects: list[Path], program: Path) -> None:
    result = subprocess.run(
        [clang, *(str(obj) for obj in objects), "-o", str(program)],
        capture_output=True, text=True, check=False,
```

In `src/gbaport/native/build.py`, replace:
```python
        raise ToolchainError(f"linking {program.name} failed:\n{result.stderr[-4000:]}")
    return program
```
with:
```python
        raise ToolchainError(f"linking {program.name} failed:\n{result.stderr[-4000:]}")


def _starts(program: Path) -> bool:
    """Whether Windows lets ``program`` start (without arguments it prints its usage).

    Smart App Control judges each new program by its content and refuses some for good
    (WinError 4551); building the same sources again gives the same file, so a refused
    build is linked again with ``gba_salt.c``, an unused string that changes the bytes.
    """
    if os.name != "nt":
        return True
    try:
        subprocess.run([str(program)], capture_output=True, timeout=30, check=False)
    except OSError as error:
        if getattr(error, "winerror", None) != 4551:
            raise
        return False
    return True
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 553 passed (552 + 1); ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/native/build.py tests/romtest.py tests/test_native_build.py
git commit -m "feat: builds Windows refuses to start are linked again with a salt"
```

---

### Task 2: BIOS reference implementations, and test data for test ROMs

**Files:**
- Create: `tests/biosref.py`, `tests/gbaroms/data_echo.c`
- Modify: `tests/romtest.py` (`build_test_rom(name, data)` writes `testdata.h`)
- Test: `tests/runtime/test_biosref.py`, `tests/runtime/test_romkit.py`

**Interfaces:**
- Consumes: `build_test_rom`, `run_test` (Plan 4a).
- Produces:
  - **`biosref`, values:** `u32`, `s32`, `s16`.
  - **`biosref`, arithmetic:**
    - `div(num, den) -> (r0, r1, r3)` and `sqrt(value)`;
    - `arctan(tan) -> (r0, r1, r3)` and `arctan2(x, y)`;
    - `midi_key_to_freq(freq, key, fine)`.
  - **`biosref`, memory calls:**
    - `bit_unpack(data, src_width, dst_width, offset, zero_too) -> [words]`;
    - `obj_affine(sx, sy, angle)` and `bg_affine(ox, oy, cx, cy, sx, sy, angle)`;
    - `SINE`, the 256-entry table in 1.14 fixed point.
  - **`biosref`, compression:**
    - `lz77_compress`/`lz77_decompress`, `rl_compress`/`rl_decompress`;
    - `huffman_compress(data, bits)`/`huffman_decompress`, `diff_filter(data, unit)`.
  - **`biosref`, test data:** `c_bytes(name, data)`, a C array for a data header.
  - In `tests/romtest.py`:
    - `build_test_rom(name, data="")` writes `data` to `testdata.h`, which the test file may `#include`;
    - `run_test(name, *, frames=600, data="")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/runtime/test_biosref.py`:
```python
"""The BIOS references against GBATEK's examples, and the compressors against their own
decompressors (so the streams the runtime tests feed it are valid)."""

import random

import biosref
import pytest


def test_div_follows_gbatek_and_c_truncation():
    assert biosref.div(-1234, 10) == (biosref.u32(-123), biosref.u32(-4), 123)  # GBATEK's example
    assert biosref.div(7, -2) == (biosref.u32(-3), 1, 3)
    assert biosref.div(0x80000000, -1) == (0x80000000, 0, 0x80000000)
    assert biosref.div(5, 0) == (1, 5, 1)  # mGBA's answer; the BIOS itself would hang


def test_sqrt_and_arctangents_at_known_points():
    assert [biosref.sqrt(v) for v in (0, 1, 15, 16, 0xFFFFFFFF)] == [0, 1, 3, 4, 0xFFFF]
    assert biosref.arctan(0)[0] == 0
    assert abs(biosref.arctan(0x4000)[0] - 0x2000) <= 8  # tan = 1: pi/4 is 0x2000
    axes = [biosref.arctan2(x, y) for x, y in ((5, 0), (0, 5), (-5, 0), (0, -5))]
    assert axes == [0x0000, 0x4000, 0x8000, 0xC000]
    for x, y, want in ((1, 1, 0x2000), (-1, 1, 0x6000), (-1, -1, 0xA000), (1, -1, 0xE000)):
        assert abs(biosref.arctan2(x * 0x1000, y * 0x1000) - want) <= 8


def test_affine_identity_and_quarter_turn():
    assert biosref.obj_affine(0x100, 0x100, 0) == (0x100, 0, 0, 0x100)
    assert biosref.obj_affine(0x100, 0x100, 0x4000) == (0, 0xFF00, 0x100, 0)  # 90 degrees
    assert biosref.bg_affine(0x1000, 0x2000, 0, 0, 0x100, 0x100, 0)[4:] == (0x1000, 0x2000)


def test_bit_unpack_adds_the_offset_to_non_zero_units():
    assert biosref.bit_unpack(bytes([0b11100100]), 2, 8, 0x10, False) == [0x13121100]
    assert biosref.bit_unpack(bytes([0b11100100]), 2, 8, 0x10, True) == [0x13121110]


@pytest.mark.parametrize("seed", range(6))
def test_compressors_round_trip(seed):
    rng = random.Random(seed)
    alphabet = rng.sample(range(256), 12)
    data = bytes(rng.choice(alphabet) if rng.random() < 0.7 else 0x55 for _ in range(rng.randrange(1, 900)))
    assert biosref.lz77_decompress(biosref.lz77_compress(data)) == data
    assert biosref.rl_decompress(biosref.rl_compress(data)) == data
    assert biosref.huffman_decompress(biosref.huffman_compress(data, 8)) == data
    assert biosref.huffman_decompress(biosref.huffman_compress(data, 4)) == data
```

Create `tests/gbaroms/data_echo.c`:
```c
/* Prints a value from testdata.h, which the Python test writes. */
#include "testlib.h"
#include "testdata.h"

int main(void)
{
    print("%s", ECHO);
    test_end();
    return 0;
}
```

In `tests/runtime/test_romkit.py`, replace:
```python
from romtest import build_test_rom
```
with:
```python
from romtest import build_test_rom, run_test
```

In `tests/runtime/test_romkit.py`, replace:
```python
    assert 0x08000000 < blob.rom < 0x08010000 and blob.size > 0
```
with:
```python
    assert 0x08000000 < blob.rom < 0x08010000 and blob.size > 0


def test_a_test_rom_can_include_data_from_python():
    run = run_test("data_echo", data='#define ECHO "made in Python"\n')
    assert run.lines[0] == "made in Python"
    run.assert_passed()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/runtime/test_biosref.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'biosref'`

Run: `uv run pytest tests/runtime/test_romkit.py`
Expected: FAIL — 1 failed: `TypeError: run_test() got an unexpected keyword argument 'data'`

- [ ] **Step 3: Write the references and the test-data header**

In `tests/romtest.py`, replace:
```python

def build_test_rom(name: str) -> TestRom:
    """Compile ``gbaroms/<name>.c`` with crt0 and testlib into a ROM and its game.toml."""
    sources = [ROMS / "crt0.s", ROMS / "testlib.c", ROMS / f"{name}.c"]
    inputs = [ROMS / "gba.ld", ROMS / "testlib.h", *sources]
    folder = CACHE / "roms" / _digest(*(path.read_bytes() for path in inputs), *CFLAGS)
    rom_path, config_path = folder / "game.gba", folder / "game.toml"
    if not rom_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        objects = []
```
with:
```python

def build_test_rom(name: str, data: str = "") -> TestRom:
    """Compile ``gbaroms/<name>.c`` with crt0 and testlib into a ROM and its game.toml.

    ``data`` becomes ``testdata.h``, which the test file may include: inputs and expected
    results that the Python tests compute (with ``biosref``, for example).
    """
    sources = [ROMS / "crt0.s", ROMS / "testlib.c", ROMS / f"{name}.c"]
    inputs = [ROMS / "gba.ld", ROMS / "testlib.h", *sources]
    folder = CACHE / "roms" / _digest(*(path.read_bytes() for path in inputs), *CFLAGS, data)
    rom_path, config_path = folder / "game.gba", folder / "game.toml"
    if not rom_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "testdata.h").write_text(data, encoding="utf-8")
        objects = []
```

In `tests/romtest.py`, replace:
```python
            flags = TARGET if source.suffix == ".s" else CFLAGS
            _run([find_clang(), *flags, f"-I{ROMS}", "-c", str(source), "-o", str(obj)])
            objects.append(str(obj))
```
with:
```python
            flags = TARGET if source.suffix == ".s" else CFLAGS
            includes = [f"-I{ROMS}", f"-I{folder}"]
            _run([find_clang(), *flags, *includes, "-c", str(source), "-o", str(obj)])
            objects.append(str(obj))
```

In `tests/romtest.py`, replace:
```python

def run_test(name: str, *, frames: int = 600) -> Run:
    return run_rom(build_test_rom(name), frames=frames)
```
with:
```python

def run_test(name: str, *, frames: int = 600, data: str = "") -> Run:
    return run_rom(build_test_rom(name, data), frames=frames)
```

Create `tests/biosref.py`:
```python
"""Reference implementations of the GBA BIOS functions, and the compressors that feed them.

Written from GBATEK's descriptions (and mGBA's HLE BIOS where GBATEK leaves a corner
open, such as division by zero), independently of the C runtime, so the runtime tests
can compare against them. Values are plain Python ints; ``u32``/``s32`` wrap them to the
ARM's 32-bit registers.

The compressors produce valid BIOS streams (not the smallest ones): LZ77 never refers to
the byte just written (the VRAM decompressor cannot), RL emits runs of 3-130 bytes, and
Huffman keeps trees small enough for the 6-bit child offsets.
"""

import heapq
import math
import struct


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def s32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - (1 << 16) if value & 0x8000 else value


def _trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


# ---- arithmetic ---------------------------------------------------------------------


def div(num: int, den: int) -> tuple[int, int, int]:
    """SWI 0x06: (r0, r1, r3) = (num / den, num % den, |num / den|), C-style truncation.
    Division by zero returns (sign, num, 1) as mGBA does (the BIOS would hang)."""
    num, den = s32(num), s32(den)
    if den == 0:
        return u32(-1 if num < 0 else 1), u32(num), 1
    if den == -1 and num == -(1 << 31):
        return 0x80000000, 0, 0x80000000
    quot = _trunc_div(num, den)
    return u32(quot), u32(num - quot * den), u32(abs(quot))


def sqrt(value: int) -> int:
    """SWI 0x08: the integer square root of an unsigned 32-bit value."""
    return math.isqrt(u32(value))


def arctan(tan: int) -> tuple[int, int, int]:
    """SWI 0x09: (r0, r1, r3) of the BIOS's polynomial, for a 1.14 fixed-point tangent."""
    i = s32(tan)
    a = s32(-(s32(i * i) >> 14))
    b = s32((s32(0xA9 * a) >> 14) + 0x390)
    for constant in (0x91C, 0xFB6, 0x16AA, 0x2081, 0x3651, 0xA2F9):
        b = s32((s32(b * a) >> 14) + constant)
    return u32(s32(i * b) >> 16), u32(a), u32(b)


def arctan2(x: int, y: int) -> int:
    """SWI 0x0A: the angle of (x, y), 0x0000-0xFFFF for 0 <= theta < 2 pi."""
    x, y = s32(x), s32(y)
    if y == 0:
        return 0 if x >= 0 else 0x8000
    if x == 0:
        return 0x4000 if y >= 0 else 0xC000

    def tan(n: int, d: int) -> int:
        return s32(arctan(_trunc_div(n << 14, d))[0])

    if y >= 0:
        if x >= 0:
            if x >= y:
                return tan(y, x) & 0xFFFF
        elif -x >= y:
            return (tan(y, x) + 0x8000) & 0xFFFF
        return (0x4000 - tan(x, y)) & 0xFFFF
    if x <= 0:
        if -x > -y:
            return (tan(y, x) + 0x8000) & 0xFFFF
    elif x >= -y:
        return (tan(y, x) + 0x10000) & 0xFFFF
    return (0xC000 - tan(x, y)) & 0xFFFF


def midi_key_to_freq(freq: int, key: int, fine: int) -> int:
    """SWI 0x1F: freq / 2^((180 - key - fine/256) / 12), truncated."""
    return u32(int(freq / 2 ** ((180 - (key & 0xFF) - (fine & 0xFF) / 256) / 12)))


# ---- memory -------------------------------------------------------------------------


def bit_unpack(data: bytes, src_width: int, dst_width: int, offset: int, zero_too: bool) -> list[int]:
    """SWI 0x10: the 32-bit words BitUnPack writes. Units come from each byte's low bits
    first; non-zero units (all units, with ``zero_too``) get ``offset`` added; results are
    not masked to the destination width."""
    words, out, used = [], 0, 0
    for byte in data:
        for shift in range(0, 8, src_width):
            unit = (byte >> shift) & ((1 << src_width) - 1)
            if unit or zero_too:
                unit += offset
            out |= unit << used
            used += dst_width
            if used == 32:
                words.append(u32(out))
                out, used = 0, 0
    return words


SINE = [round(16384 * math.sin(2 * math.pi * i / 256)) for i in range(256)]  # 1.14 fixed point


def _rotation(sx: int, sy: int, angle: int) -> tuple[int, int, int, int]:
    theta = (angle & 0xFFFF) >> 8
    sin, cos = SINE[theta], SINE[(theta + 64) & 0xFF]
    return (sx * cos) >> 14, (sx * -sin) >> 14, (sy * sin) >> 14, (sy * cos) >> 14


def obj_affine(sx: int, sy: int, angle: int) -> tuple[int, int, int, int]:
    """SWI 0x0F: (pa, pb, pc, pd) for 8.8 scales sx, sy and an angle (upper 8 bits used)."""
    return tuple(v & 0xFFFF for v in _rotation(s16(sx), s16(sy), angle))


def bg_affine(ox: int, oy: int, cx: int, cy: int, sx: int, sy: int, angle: int) -> tuple[int, ...]:
    """SWI 0x0E: (pa, pb, pc, pd, x, y): the matrix, and the start point that puts the
    texture point (ox, oy) (24.8 fixed point) at the screen point (cx, cy)."""
    pa, pb, pc, pd = _rotation(s16(sx), s16(sy), angle)
    x = s32(ox) - (pa * s16(cx) + pb * s16(cy))
    y = s32(oy) - (pc * s16(cx) + pd * s16(cy))
    return pa & 0xFFFF, pb & 0xFFFF, pc & 0xFFFF, pd & 0xFFFF, u32(x), u32(y)


# ---- compression --------------------------------------------------------------------


def _header(kind: int, size: int, low: int = 0) -> bytes:
    return struct.pack("<I", (size << 8) | (kind << 4) | low)


def _pad(data: bytes) -> bytes:
    return data + bytes(-len(data) % 4)


def lz77_compress(data: bytes) -> bytes:
    """A valid LZ77 stream (type 1) for both the WRAM and the VRAM decompressor."""
    out, i = bytearray(_header(1, len(data))), 0
    while i < len(data):
        flags_at, flags = len(out), 0
        out.append(0)
        for bit in range(8):
            if i >= len(data):
                break
            best_len, best_dist = 0, 0
            for dist in range(2, min(i, 0x1000) + 1):  # distance 1 would read an unwritten byte
                length = 0
                while length < 18 and i + length < len(data) and data[i + length - dist] == data[i + length]:
                    length += 1
                if length > best_len:
                    best_len, best_dist = length, dist
            if best_len >= 3:
                flags |= 0x80 >> bit
                out += bytes([((best_len - 3) << 4) | ((best_dist - 1) >> 8), (best_dist - 1) & 0xFF])
                i += best_len
            else:
                out.append(data[i])
                i += 1
        out[flags_at] = flags
    return _pad(bytes(out))


def lz77_decompress(stream: bytes) -> bytes:
    size = struct.unpack_from("<I", stream)[0] >> 8
    out, i = bytearray(), 4
    while len(out) < size:
        flags = stream[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                length = (stream[i] >> 4) + 3
                dist = (((stream[i] & 0xF) << 8) | stream[i + 1]) + 1
                i += 2
                for _ in range(length):
                    out.append(out[-dist])
            else:
                out.append(stream[i])
                i += 1
    return bytes(out[:size])


def rl_compress(data: bytes) -> bytes:
    """A run-length stream (type 3): runs of 3-130 equal bytes, literals of 1-128 bytes."""
    out, i, literal = bytearray(_header(3, len(data))), 0, bytearray()

    def flush() -> None:
        while literal:
            chunk = literal[:128]
            out.append(len(chunk) - 1)
            out.extend(chunk)
            del literal[:128]

    while i < len(data):
        run = 1
        while run < 130 and i + run < len(data) and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            flush()
            out += bytes([0x80 | (run - 3), data[i]])
            i += run
        else:
            literal.append(data[i])
            i += 1
    flush()
    return _pad(bytes(out))


def rl_decompress(stream: bytes) -> bytes:
    size = struct.unpack_from("<I", stream)[0] >> 8
    out, i = bytearray(), 4
    while len(out) < size:
        flag = stream[i]
        i += 1
        if flag & 0x80:
            out += bytes([stream[i]]) * ((flag & 0x7F) + 3)
            i += 1
        else:
            out += stream[i : i + flag + 1]
            i += flag + 1
    return bytes(out[:size])


def diff_filter(data: bytes, unit: int) -> bytes:
    """A differencing stream (type 8) of 1- or 2-byte units."""
    values = list(data) if unit == 1 else list(struct.unpack(f"<{len(data) // 2}H", data))
    mask = 0xFF if unit == 1 else 0xFFFF
    deltas = [values[0]] + [(values[k] - values[k - 1]) & mask for k in range(1, len(values))]
    body = bytes(deltas) if unit == 1 else struct.pack(f"<{len(deltas)}H", *deltas)
    return _pad(_header(8, len(data), unit) + body)


def _units(data: bytes, bits: int) -> list[int]:
    if bits == 8:
        return list(data)
    return [nibble for byte in data for nibble in (byte & 0xF, byte >> 4)]  # low nibble first


def huffman_compress(data: bytes, bits: int) -> bytes:
    """A Huffman stream (type 2) for 4- or 8-bit units. ``data`` should use few distinct
    units (at most about 40), so every child offset fits in 6 bits."""
    units = _units(data, bits)
    counts: dict[int, int] = {}
    for unit in units:
        counts[unit] = counts.get(unit, 0) + 1
    if len(counts) == 1:  # a tree needs two leaves
        counts[(units[0] + 1) % (1 << bits)] = 0
    heap = [(count, n, ("leaf", unit)) for n, (unit, count) in enumerate(sorted(counts.items()))]
    heapq.heapify(heap)
    n = len(heap)
    while len(heap) > 1:
        a, b = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (a[0] + b[0], n, ("node", a[2], b[2])))
        n += 1
    root = heap[0][2]

    table = [0, 0]  # [tree size byte, root node]
    codes: dict[int, str] = {}
    queue = [(root, 1, "")]  # (node, index in table, code so far): breadth first
    while queue:
        node, index, code = queue.pop(0)
        if node[0] == "leaf":
            table[index] = node[1]
            codes[node[1]] = code
            continue
        pair = len(table)
        table += [0, 0]
        offset = (pair - (index & ~1) - 2) // 2
        assert 0 <= offset <= 63, "tree too large for the 6-bit child offsets"
        table[index] = offset | (0x80 if node[1][0] == "leaf" else 0) | (0x40 if node[2][0] == "leaf" else 0)
        queue += [(node[1], pair, code + "0"), (node[2], pair + 1, code + "1")]
    table += [0] * (-len(table) % 4)
    table[0] = len(table) // 2 - 1
    bitstring = "".join(codes[unit] for unit in units)
    bitstring += "0" * (-len(bitstring) % 32)
    words = [int(bitstring[k : k + 32], 2) for k in range(0, len(bitstring), 32)]
    return _header(2, len(data), bits) + bytes(table) + struct.pack(f"<{len(words)}I", *words)


def huffman_decompress(stream: bytes) -> bytes:
    header = struct.unpack_from("<I", stream)[0]
    bits, size = header & 0xF, header >> 8
    tree = 4 + 1  # the root node
    stream_at = 4 + (stream[4] + 1) * 2
    units: list[int] = []
    node, word_at = tree, stream_at
    while len(units) * bits < size * 8:
        word = struct.unpack_from("<I", stream, word_at)[0]
        word_at += 4
        for k in range(31, -1, -1):
            bit = (word >> k) & 1
            value = stream[node]
            child = (node & ~1) + (value & 0x3F) * 2 + 2 + bit
            if value & (0x80 >> bit):
                units.append(stream[child])
                node = tree
                if len(units) * bits >= size * 8:
                    break
            else:
                node = child
    if bits == 8:
        return bytes(units[:size])
    return bytes(units[k] | (units[k + 1] << 4) for k in range(0, size * 2, 2))


def c_bytes(name: str, data: bytes) -> str:
    """A C array definition for test data headers, 4-byte aligned."""
    body = ", ".join(f"0x{b:02x}" for b in data)
    return f"static const uint8_t {name}[{max(len(data), 1)}] __attribute__((aligned(4))) = {{{body}}};\n"
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 564 passed (553 + 11); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tests/biosref.py tests/romtest.py tests/gbaroms/data_echo.c tests/runtime/test_biosref.py tests/runtime/test_romkit.py
git commit -m "test: BIOS reference implementations and data headers for test ROMs"
```

---

### Task 3: BIOS arithmetic and the small calls

**Files:**
- Create: `src/gbaport/runtime/bios_math.c`, `tests/gbaroms/bios_math.c`, `tests/gbaroms/bios_sound.c`
- Delete: `tests/gbaroms/err_swi.c`. Div exists now, so it is no example of a missing function; the sound driver test takes its place.
- Modify: `src/gbaport/runtime/bios.c`, `gba_runtime.h`, `runtime.c`, `src/gbaport/native/build.py`
- Modify: `tests/gbaroms/testlib.h`, `tests/gbaroms/testlib.c` (`BIOS_CALL`, `mismatch`), `tests/runtime/test_core.py`
- Test: `tests/runtime/test_bios_math.py`

**Interfaces:**
- Consumes: Task 2's `biosref` and `testdata.h`; the Plan 4a runtime.
- **Produces, warnings:** `GbaWarning` (`GBA_WARN_SWI`, `GBA_WARN_DIV_ZERO`, `GBA_WARN_BAD_ARGUMENT`, `GBA_WARN_SOUND`) and `gba_warn_once(rt, kind, fmt, ...)`. `GbaRuntime.warned` replaces `warned_swi`.
- **Produces, BIOS calls:**
  - `gba_bios_div(rt, num, den)`, `gba_bios_sqrt`, `gba_bios_arctan`, `gba_bios_arctan2`, `gba_bios_midi_key_to_freq`.
  - SWIs 0x06-0x0A, 0x0D (GetBiosChecksum), 0x19 (SoundBias), 0x1F, 0x25 (MultiBoot fails) and 0x27 (CustomHalt).
  - The sound driver SWIs are ignored with a warning.
  - BIOS functions not written yet still end the run with "not implemented yet".
- **Produces, test library:** `BIOS_CALL(number, in, out)`, `mismatch(...)`, `mismatches()`.

- [ ] **Step 1: Write the failing tests**

In `tests/gbaroms/testlib.h`, replace:
```c

static inline void bios_halt(void) { __asm__ volatile("svc #2" ::: "r0", "r1", "r2", "r3", "memory"); }
```
with:
```c

/* Any BIOS call: r0-r3 in from in[0..3], out to out[0..3]. */
#define BIOS_CALL(number, in, out) do { \
        register uint32_t r0_ __asm__("r0") = (in)[0]; \
        register uint32_t r1_ __asm__("r1") = (in)[1]; \
        register uint32_t r2_ __asm__("r2") = (in)[2]; \
        register uint32_t r3_ __asm__("r3") = (in)[3]; \
        __asm__ volatile("svc #" #number : "+r"(r0_), "+r"(r1_), "+r"(r2_), "+r"(r3_) :: "memory"); \
        (out)[0] = r0_, (out)[1] = r1_, (out)[2] = r2_, (out)[3] = r3_; \
    } while (0)

/* Counts a mismatch and prints the first few (for tests that run many cases). */
void mismatch(const char *what, uint32_t a, uint32_t b, uint32_t got, uint32_t want);
uint32_t mismatches(void);  /* how many since the last call, then starts again */

static inline void bios_halt(void) { __asm__ volatile("svc #2" ::: "r0", "r1", "r2", "r3", "memory"); }
```

In `tests/gbaroms/testlib.c`, replace:
```c

void test_end(void)
```
with:
```c

static uint32_t mismatch_count;

void mismatch(const char *what, uint32_t a, uint32_t b, uint32_t got, uint32_t want)
{
    if (mismatch_count++ < 3)
        print("  %s(0x%08x, 0x%08x): got 0x%08x, want 0x%08x", what, a, b, got, want);
}

uint32_t mismatches(void)
{
    uint32_t n = mismatch_count;
    mismatch_count = 0;
    return n;
}

void test_end(void)
```

Create `tests/gbaroms/bios_math.c`:
```c
/* The BIOS's arithmetic against biosref: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq,
 * plus GetBiosChecksum, SoundBias and MultiBoot. testdata.h holds the cases. */
#include "testlib.h"
#include "testdata.h"

int main(void)
{
    uint32_t in[4] = {0}, out[4];

    for (unsigned i = 0; i < DIV_COUNT; i++) {
        const uint32_t *c = div_cases[i];
        in[0] = c[0], in[1] = c[1];
        BIOS_CALL(0x06, in, out);
        if (out[0] != c[2] || out[1] != c[3] || out[3] != c[4])
            mismatch("Div", c[0], c[1], out[0], c[2]);
        in[0] = c[1], in[1] = c[0];
        BIOS_CALL(0x07, in, out);
        if (out[0] != c[2] || out[1] != c[3] || out[3] != c[4])
            mismatch("DivArm", c[1], c[0], out[0], c[2]);
    }
    check("Div and DivArm", mismatches() == 0);

    for (unsigned i = 0; i < SQRT_COUNT; i++) {
        in[0] = sqrt_cases[i][0];
        BIOS_CALL(0x08, in, out);
        if (out[0] != sqrt_cases[i][1])
            mismatch("Sqrt", in[0], 0, out[0], sqrt_cases[i][1]);
    }
    check("Sqrt", mismatches() == 0);

    for (unsigned i = 0; i < ARCTAN_COUNT; i++) {
        const uint32_t *c = arctan_cases[i];
        in[0] = c[0];
        BIOS_CALL(0x09, in, out);
        if (out[0] != c[1] || out[1] != c[2] || out[3] != c[3])
            mismatch("ArcTan", c[0], 0, out[0], c[1]);
    }
    check("ArcTan", mismatches() == 0);

    for (unsigned i = 0; i < ARCTAN2_COUNT; i++) {
        const uint32_t *c = arctan2_cases[i];
        in[0] = c[0], in[1] = c[1];
        BIOS_CALL(0x0A, in, out);
        if (out[0] != c[2])
            mismatch("ArcTan2", c[0], c[1], out[0], c[2]);
    }
    check("ArcTan2", mismatches() == 0);

    static uint32_t wave[2];
    for (unsigned i = 0; i < MIDI_COUNT; i++) {
        const uint32_t *c = midi_cases[i];
        wave[1] = c[0];
        in[0] = (uint32_t)wave, in[1] = c[1], in[2] = c[2];
        BIOS_CALL(0x1F, in, out);
        if (out[0] + 1 < c[3] || out[0] > c[3] + 1)  /* pow() may round the last bit either way */
            mismatch("MidiKey2Freq", c[0], c[1], out[0], c[3]);
    }
    check("MidiKey2Freq", mismatches() == 0);

    BIOS_CALL(0x0D, in, out);
    expect("GetBiosChecksum", out[0], 0xBAAE187F);
    in[0] = 1;
    BIOS_CALL(0x19, in, out);
    expect("SoundBias up", REG16(0x04000088) & 0x3FF, 0x200);
    in[0] = 0;
    BIOS_CALL(0x19, in, out);
    expect("SoundBias down", REG16(0x04000088) & 0x3FF, 0);
    BIOS_CALL(0x25, in, out);
    expect("MultiBoot fails without a cable", out[0], 1);

    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    wait_vcount(10);
    uint32_t before = irq_count[0];
    in[2] = 0;  /* CustomHalt with 0: Halt */
    BIOS_CALL(0x27, in, out);
    uint32_t line = REG_VCOUNT;
    expect("CustomHalt halts until an interrupt", irq_count[0], before + 1);
    expect("CustomHalt returns in line 160", line, 160);

    test_end();
    return 0;
}
```

Create `tests/gbaroms/bios_sound.c`:
```c
/* Calls the BIOS sound driver (SoundDriverMain), which the runtime ignores until sound
 * arrives: the game goes on. */
#include "testlib.h"

int main(void)
{
    print("before");
    __asm__ volatile("svc #0x1c" ::: "r0", "r1", "r2", "r3", "memory");
    print("after");
    test_end();
    return 0;
}
```

Delete `tests/gbaroms/err_swi.c`:
```bash
git rm tests/gbaroms/err_swi.c
```

Create `tests/runtime/test_bios_math.py`:
```python
import random

import biosref
from romtest import run_test

EDGES = [0, 1, -1, 2, -2, 7, -7, 10, -1234, 0x7FFFFFFF, -0x80000000, 0x10000, -0x10000]


def _table(name: str, rows: list[tuple[int, ...]]) -> str:
    width = len(rows[0])
    body = ",\n".join("    {" + ", ".join(f"0x{biosref.u32(v):08x}u" for v in row) + "}" for row in rows)
    return (
        f"#define {name.upper()}_COUNT {len(rows)}u\n"
        f"static const uint32_t {name}_cases[][{width}] = {{\n{body}\n}};\n"
    )


def math_data() -> str:
    rng = random.Random(41)
    pairs = [(n, d) for n in EDGES for d in EDGES if d]
    pairs += [(rng.getrandbits(32), rng.choice([rng.getrandbits(32), rng.randint(1, 100)])) for _ in range(300)]
    pairs += [(5, 0), (-5, 0)]  # division by zero: mGBA's answer, and a warning
    divs = [(n, d, *biosref.div(n, d)) for n, d in pairs]
    roots = [(v, biosref.sqrt(v)) for v in [0, 1, 2, 3, 4, 0xFFFFFFFF, 0xFFFE0001, *(rng.getrandbits(32) for _ in range(200))]]
    tans = [t for t in range(-0x4000, 0x4001, 0x100)] + [rng.randint(-0x4000, 0x4000) for _ in range(100)]
    arctans = [(t, *biosref.arctan(t)) for t in tans]
    points = [(5, 0), (-5, 0), (0, 5), (0, -5), (0x1000, 0x1000), (-0x1000, 0x1000), (-0x1000, -0x1000)]
    points += [(rng.randint(-0x7FFF, 0x7FFF), rng.randint(-0x7FFF, 0x7FFF)) for _ in range(300)]
    arctan2s = [(x, y, biosref.arctan2(x, y)) for x, y in points]
    midis = [(f, k, p, biosref.midi_key_to_freq(f, k, p)) for f, k, p in
             [(rng.randint(0x1000, 0xFFFFFF), rng.randint(0, 127), rng.randint(0, 255)) for _ in range(100)]]
    return "".join(_table(name, rows) for name, rows in [
        ("div", divs), ("sqrt", roots), ("arctan", arctans), ("arctan2", arctan2s), ("midi", midis),
    ])


def test_bios_arithmetic_matches_the_reference():
    run = run_test("bios_math", data=math_data())
    run.assert_passed()
    assert "Div of 5 by zero" in run.stderr
```

In `tests/runtime/test_core.py`, replace:
```python

def test_a_missing_bios_function_ends_the_run_with_its_number():
    run = run_test("err_swi")
    assert run.status == 3
    assert run.lines == ("before",)
    assert "BIOS function 0x06 is not implemented yet" in run.stderr
```
with:
```python

def test_the_bios_sound_driver_is_ignored_with_a_warning():
    run = run_test("bios_sound")
    run.assert_passed()
    assert run.lines[:2] == ("before", "after")
    assert "ignoring the BIOS sound driver (SWI 0x1c)" in run.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/runtime/test_bios_math.py tests/runtime/test_core.py`
Expected: FAIL — 2 failed: `bios_math` exits with 3 (`BIOS function 0x06 is not implemented yet`), `bios_sound` with 3 (`BIOS function 0x1c is not implemented yet`).

- [ ] **Step 3: Write the arithmetic and the small calls**

In `src/gbaport/native/build.py`, replace:
```python
RUNTIME = PACKAGE / "runtime"
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c", "bios.c")
HOSTS = {"headless": "host_headless.c"}
```
with:
```python
RUNTIME = PACKAGE / "runtime"
RUNTIME_SOURCES = (
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c",
)
HOSTS = {"headless": "host_headless.c"}
```

Create `src/gbaport/runtime/bios_math.c`:
```c
/* bios_math.c - the BIOS's arithmetic: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq.
 *
 * Results follow GBATEK. Where the BIOS has no defined result (division by zero hangs it)
 * the runtime answers as mGBA's HLE BIOS does and warns once. The arctangents use the
 * BIOS's own polynomial, in 32-bit wrapping arithmetic like the ARM code it replaces. */
#include <math.h>

#include "gba_runtime.h"

static int32_t mul32(int32_t a, int32_t b) { return (int32_t)((uint32_t)a * (uint32_t)b); }

/* SWI 0x06 (and 0x07 with the operands swapped). */
void gba_bios_div(GbaRuntime *rt, int32_t num, int32_t den)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t quot, rem;
    if (den == 0) {
        gba_warn_once(rt, GBA_WARN_DIV_ZERO, "Div of %d by zero (the BIOS would hang)", (int)num);
        quot = num < 0 ? -1 : 1;
        rem = num;
        ctx->r[3] = 1;
    } else if (den == -1 && num == INT32_MIN) {
        quot = INT32_MIN;
        rem = 0;
        ctx->r[3] = 0x80000000u;
    } else {
        quot = num / den;
        rem = num % den;
        ctx->r[3] = quot < 0 ? 0u - (uint32_t)quot : (uint32_t)quot;
    }
    ctx->r[0] = (uint32_t)quot;
    ctx->r[1] = (uint32_t)rem;
    ctx->cycles += 100;
}

/* SWI 0x08: the integer square root. */
void gba_bios_sqrt(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t value = ctx->r[0], root = 0;
    for (uint32_t bit = 1u << 15; bit; bit >>= 1) {
        uint32_t trial = root | bit;
        if ((uint64_t)trial * trial <= value)
            root = trial;
    }
    ctx->r[0] = root;
    ctx->cycles += 60;
}

/* The BIOS's arctangent polynomial for a 1.14 fixed-point tangent. */
static int32_t arctan(int32_t i, int32_t *r1, int32_t *r3)
{
    int32_t a = -(mul32(i, i) >> 14);
    int32_t b = (mul32(0xA9, a) >> 14) + 0x390;
    static const int32_t terms[] = {0x91C, 0xFB6, 0x16AA, 0x2081, 0x3651, 0xA2F9};
    for (int k = 0; k < 6; k++)
        b = (mul32(b, a) >> 14) + terms[k];
    if (r1)
        *r1 = a;
    if (r3)
        *r3 = b;
    return mul32(i, b) >> 16;
}

/* SWI 0x09. */
void gba_bios_arctan(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t a, b;
    ctx->r[0] = (uint32_t)arctan((int32_t)ctx->r[0], &a, &b);
    ctx->r[1] = (uint32_t)a;
    ctx->r[3] = (uint32_t)b;
    ctx->cycles += 40;
}

static int32_t tangent(int32_t n, int32_t d) { return (int32_t)(((int64_t)n << 14) / d); }

/* SWI 0x0A: the angle of (x, y) as 0x0000-0xFFFF for 0 <= theta < 2 pi. */
void gba_bios_arctan2(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    int32_t x = (int32_t)ctx->r[0], y = (int32_t)ctx->r[1], angle;
    if (y == 0)
        angle = x >= 0 ? 0 : 0x8000;
    else if (x == 0)
        angle = y >= 0 ? 0x4000 : 0xC000;
    else if (y >= 0) {
        if (x >= 0 && x >= y)
            angle = arctan(tangent(y, x), NULL, NULL);
        else if (x < 0 && -x >= y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x8000;
        else
            angle = 0x4000 - arctan(tangent(x, y), NULL, NULL);
    } else {
        if (x <= 0 && -x > -y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x8000;
        else if (x > 0 && x >= -y)
            angle = arctan(tangent(y, x), NULL, NULL) + 0x10000;
        else
            angle = 0xC000 - arctan(tangent(x, y), NULL, NULL);
    }
    ctx->r[0] = (uint32_t)angle & 0xFFFF;
    ctx->cycles += 60;
}

/* SWI 0x1F: r0 = WaveData.freq / 2^((180 - key - fine/256) / 12), the WaveData at r0. */
void gba_bios_midi_key_to_freq(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    double freq = gba_read32(ctx, ctx->r[0] + 4);
    double semitones = 180.0 - (ctx->r[1] & 0xFF) - (ctx->r[2] & 0xFF) / 256.0;
    ctx->r[0] = (uint32_t)(freq / pow(2.0, semitones / 12.0));
    ctx->cycles += 80;
}
```

In `src/gbaport/runtime/bios.c`, replace:
```c
 *
 * This file has the calls that control the CPU: resets, Halt, Stop and the interrupt
 * waits. The other BIOS functions (0x06-0x2A: arithmetic, copies, decompression, ...)
 * are not implemented yet and end the run with an error that names them. Numbers above
 * 0x2A do not exist in the BIOS; the first one is reported and they are ignored. */
#include <stdio.h>
#include <string.h>
```
with:
```c
 *
 * gba_swi dispatches every call. This file has the ones that control the CPU (resets,
 * Halt, Stop, the interrupt waits) and the small ones; the others are in
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq.
 * Any other BIOS function ends the run with an error that names it, for now.
 * The sound driver calls (0x1A-0x1E, 0x20-0x24, 0x28-0x2A) are ignored with a warning
 * until sound arrives. Numbers above 0x2A do not exist in the BIOS; they are ignored with
 * a warning too. */
#include <string.h>
```

In `src/gbaport/runtime/bios.c`, replace:
```c
        break;
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        if (!rt->warned_swi && rt->host.diag) {
            char text[96];
            snprintf(text, sizeof text, "ignoring SWI 0x%02x: the BIOS has no such function",
                     (unsigned)number);
            rt->host.diag(rt, text, rt->host.user);
        }
        rt->warned_swi = 1;
        break;
```
with:
```c
        break;
    case 0x06: gba_bios_div(rt, (int32_t)ctx->r[0], (int32_t)ctx->r[1]); break;
    case 0x07: gba_bios_div(rt, (int32_t)ctx->r[1], (int32_t)ctx->r[0]); break;  /* DivArm */
    case 0x08: gba_bios_sqrt(rt); break;
    case 0x09: gba_bios_arctan(rt); break;
    case 0x0A: gba_bios_arctan2(rt); break;
    case 0x0D: ctx->r[0] = 0xBAAE187Fu; break;  /* GetBiosChecksum */
    case 0x19:  /* SoundBias: straight to the target level */
        IO(rt, 0x088) = (uint16_t)((IO(rt, 0x088) & 0xC000) | (ctx->r[0] ? 0x200 : 0));
        break;
    case 0x1F: gba_bios_midi_key_to_freq(rt); break;
    case 0x25: ctx->r[0] = 1; break;  /* MultiBoot fails: there is no link cable */
    case 0x27:  /* CustomHalt: r2's low byte goes to HALTCNT */
        if (ctx->r[2] & 0x80)
            gba_end(rt, GBA_END_STOPPED);
        gba_halt(rt);
        break;
    case 0x1A: case 0x1B: case 0x1C: case 0x1D: case 0x1E:
    case 0x20: case 0x21: case 0x22: case 0x23: case 0x24:
    case 0x28: case 0x29: case 0x2A:
        gba_warn_once(rt, GBA_WARN_SOUND,
                      "ignoring the BIOS sound driver (SWI 0x%02x) until sound arrives",
                      (unsigned)number);
        break;
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        gba_warn_once(rt, GBA_WARN_SWI, "ignoring SWI 0x%02x: the BIOS has no such function",
                      (unsigned)number);
        break;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c

typedef struct GbaRuntime GbaRuntime;
```
with:
```c

typedef enum {  /* runtime warnings, each reported once a run */
    GBA_WARN_SWI = 1 << 0,           /* a SWI number the BIOS does not have */
    GBA_WARN_DIV_ZERO = 1 << 1,
    GBA_WARN_BAD_ARGUMENT = 1 << 2,  /* a BIOS call with arguments it rejects */
    GBA_WARN_SOUND = 1 << 3,         /* the BIOS sound driver, not implemented yet */
} GbaWarning;

typedef struct GbaRuntime GbaRuntime;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    int debug_enabled;
    int warned_swi;
```
with:
```c
    int debug_enabled;
    unsigned warned;  /* GbaWarning bits already reported */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_reset_io(GbaRuntime *rt);
```
with:
```c
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...);
void gba_reset_io(GbaRuntime *rt);
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```
with:
```c

void gba_bios_div(GbaRuntime *rt, int32_t num, int32_t den);
void gba_bios_sqrt(GbaRuntime *rt);
void gba_bios_arctan(GbaRuntime *rt);
void gba_bios_arctan2(GbaRuntime *rt);
void gba_bios_midi_key_to_freq(GbaRuntime *rt);

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```

In `src/gbaport/runtime/runtime.c`, replace:
```c

void gba_fail(GbaRuntime *rt, const char *fmt, ...)
```
with:
```c

void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...)
{
    if (rt->warned & kind)
        return;
    rt->warned |= kind;
    if (!rt->host.diag)
        return;
    char text[256];
    va_list args;
    va_start(args, fmt);
    vsnprintf(text, sizeof text, fmt, args);
    va_end(args);
    rt->host.diag(rt, text, rt->host.user);
}

void gba_fail(GbaRuntime *rt, const char *fmt, ...)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 565 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms tests/runtime/test_bios_math.py tests/runtime/test_core.py
git commit -m "feat: BIOS arithmetic, small calls and the sound-driver warning"
```

---

### Task 4: BIOS memory calls

**Files:**
- Create: `src/gbaport/runtime/bios_memory.c`, `tests/gbaroms/bios_copy.c`
- Modify: `src/gbaport/runtime/bios.c`, `gba_runtime.h`, `src/gbaport/native/build.py`
- Test: `tests/runtime/test_bios_copy.py`

**Interfaces:**
- Consumes: Task 3's dispatcher and `gba_warn_once`; `biosref.bit_unpack`, `obj_affine`, `bg_affine`.
- Produces: `gba_bios_cpu_set`, `gba_bios_cpu_fast_set`, `gba_bios_bit_unpack`, `gba_bios_bg_affine_set`, `gba_bios_obj_affine_set` (SWIs 0x0B, 0x0C, 0x10, 0x0E, 0x0F).
- **CpuSet and CpuFastSet:**
  - They do nothing when the source is in the BIOS area.
  - CpuFastSet rounds its count up to 8 words.
- **BitUnPack:**
  - BitUnPack writes 32-bit words, without masking units to the destination width.
  - Unit widths other than 1/2/4/8 (source) or 1/2/4/8/16/32 (destination) are ignored with a warning.

- [ ] **Step 1: Write the failing test**

Create `tests/gbaroms/bios_copy.c`:
```c
/* The BIOS's memory calls: CpuSet and CpuFastSet (checked here), BitUnPack, ObjAffineSet
 * and BgAffineSet (against biosref, through testdata.h). */
#include "testlib.h"
#include "testdata.h"

#define SRC ((volatile uint8_t *)0x02000000)
#define DST ((volatile uint8_t *)0x02010000)

static void fill_pattern(uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes; i++) {
        SRC[i] = (uint8_t)(i * 7 + 3);
        DST[i] = 0;
    }
}

static int same(uint32_t from, uint32_t bytes)
{
    for (uint32_t i = 0; i < bytes; i++)
        if (DST[i] != SRC[from + i])
            return 0;
    return 1;
}

static int all(uint32_t start, uint32_t bytes, uint8_t value)
{
    for (uint32_t i = start; i < start + bytes; i++)
        if (DST[i] != value)
            return 0;
    return 1;
}

int main(void)
{
    uint32_t in[4] = {0}, out[4];

    fill_pattern(64);
    in[0] = 0x02000000, in[1] = 0x02010000, in[2] = 10;  /* ten halfwords */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet copies halfwords", same(0, 20) && all(20, 4, 0));
    fill_pattern(64);
    in[2] = 5 | (1u << 26);  /* five words */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet copies words", same(0, 20) && all(20, 4, 0));
    fill_pattern(64);
    MEM16(0x02000000) = 0xBEEF;
    in[2] = 6 | (1u << 24);  /* fill six halfwords */
    BIOS_CALL(0x0B, in, out);
    check("CpuSet fills halfwords", MEM16(0x02010000) == 0xBEEF && MEM16(0x0201000A) == 0xBEEF &&
                                     MEM16(0x0201000C) == 0);
    fill_pattern(64);
    in[0] = 0x02000003, in[1] = 0x02010002, in[2] = 2 | (1u << 26);
    BIOS_CALL(0x0B, in, out);
    check("CpuSet aligns word addresses down", same(0, 8) && all(8, 4, 0));
    fill_pattern(64);
    in[0] = 0x00000100, in[1] = 0x02010000, in[2] = 4;
    BIOS_CALL(0x0B, in, out);
    check("CpuSet will not read the BIOS", all(0, 16, 0));

    fill_pattern(64);
    in[0] = 0x02000000, in[1] = 0x02010000, in[2] = 5;  /* rounded up to 8 words */
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet copies blocks of 8 words", same(0, 32) && all(32, 4, 0));
    fill_pattern(64);
    MEM32(0x02000000) = 0x12345678;
    in[2] = 8 | (1u << 24);
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet fills", MEM32(0x02010000) == 0x12345678 && MEM32(0x0201001C) == 0x12345678 &&
                              MEM32(0x02010020) == 0);
    fill_pattern(64);
    in[0] = 0x00000000, in[2] = 8;
    BIOS_CALL(0x0C, in, out);
    check("CpuFastSet will not read the BIOS", all(0, 32, 0));

    static uint32_t words[64] __attribute__((aligned(4)));
    for (unsigned i = 0; i < UNPACK_COUNT; i++) {
        const UnpackCase *c = &unpack_cases[i];
        for (unsigned k = 0; k < 64; k++)
            words[k] = 0;
        in[0] = (uint32_t)c->data, in[1] = (uint32_t)words, in[2] = (uint32_t)&c->info;
        BIOS_CALL(0x10, in, out);
        for (unsigned k = 0; k < c->count; k++)
            if (words[k] != c->words[k])
                mismatch("BitUnPack", i, k, words[k], c->words[k]);
    }
    check("BitUnPack", mismatches() == 0);

    static int16_t matrix[4 * 4];
    for (unsigned i = 0; i < OBJ_COUNT; i++) {
        const int16_t *c = obj_cases[i];
        int16_t source[4] = {c[0], c[1], c[2], 0};
        in[0] = (uint32_t)source, in[1] = (uint32_t)matrix, in[2] = 1, in[3] = 2;
        BIOS_CALL(0x0F, in, out);
        for (unsigned k = 0; k < 4; k++)
            if (matrix[k] != c[3 + k])
                mismatch("ObjAffineSet", i, k, (uint16_t)matrix[k], (uint16_t)c[3 + k]);
    }
    check("ObjAffineSet", mismatches() == 0);
    {
        int16_t source[8] = {0x100, 0x100, 0x4000, 0, 0x200, 0x80, 0, 0};
        in[0] = (uint32_t)source, in[1] = 0x07000006, in[2] = 2, in[3] = 8;  /* into OAM */
        BIOS_CALL(0x0F, in, out);
        check("ObjAffineSet writes OAM with a stride of 8",
              MEM16(0x07000006) == 0 && MEM16(0x0700000E) == 0xFF00 && MEM16(0x07000016) == 0x100 &&
              MEM16(0x0700001E) == 0 && MEM16(0x07000026) == 0x200 && MEM16(0x0700003E) == 0x80);
    }

    static int32_t bg[4];
    for (unsigned i = 0; i < BG_COUNT; i++) {
        const BgCase *c = &bg_cases[i];
        in[0] = (uint32_t)&c->source, in[1] = (uint32_t)bg, in[2] = 1;
        BIOS_CALL(0x0E, in, out);
        const int16_t *m = (const int16_t *)bg;
        for (unsigned k = 0; k < 4; k++)
            if (m[k] != c->want_matrix[k])
                mismatch("BgAffineSet", i, k, (uint16_t)m[k], (uint16_t)c->want_matrix[k]);
        if (bg[2] != c->want_x || bg[3] != c->want_y)
            mismatch("BgAffineSet start", i, 0, (uint32_t)bg[2], (uint32_t)c->want_x);
    }
    check("BgAffineSet", mismatches() == 0);

    test_end();
    return 0;
}
```

Create `tests/runtime/test_bios_copy.py`:
```python
import random

import biosref
from romtest import run_test

HEADER = """
typedef struct { uint16_t length; uint8_t src_width, dst_width; uint32_t offset; } UnpackInfo;
typedef struct { const uint8_t *data; UnpackInfo info; uint32_t count; uint32_t words[64]; } UnpackCase;
typedef struct {
    struct { int32_t ox, oy; int16_t cx, cy, sx, sy; uint16_t angle, pad; } source;
    int16_t want_matrix[4];
    int32_t want_x, want_y;
} BgCase;
"""


def copy_data() -> str:
    rng = random.Random(43)
    parts, unpacks = [HEADER], []
    for i in range(40):
        src_width = rng.choice([1, 2, 4, 8])
        dst_width = rng.choice([w for w in (1, 2, 4, 8, 16, 32) if w >= src_width])
        length = min(rng.choice([4, 8, 16, 32]), 256 * src_width // dst_width)  # <= 64 words out
        data = bytes(rng.randrange(256) for _ in range(length))
        offset = rng.choice([0, 1, rng.randrange(1 << 20)])
        zero_too = rng.random() < 0.5
        words = biosref.bit_unpack(data, src_width, dst_width, offset, zero_too)
        parts.append(biosref.c_bytes(f"unpack_data_{i}", data))
        info = f"{{{length}, {src_width}, {dst_width}, 0x{offset | (zero_too << 31):08x}u}}"
        body = ", ".join(f"0x{w:08x}u" for w in words) or "0"
        unpacks.append(f"    {{unpack_data_{i}, {info}, {len(words)}u, {{{body}}}}},")
    parts.append(f"#define UNPACK_COUNT {len(unpacks)}u\nstatic const UnpackCase unpack_cases[] = {{\n")
    parts.append("\n".join(unpacks) + "\n};\n")

    objs = [(0x100, 0x100, 0), (0x100, 0x100, 0x4000), (0x80, 0x200, 0x2000)]
    objs += [(biosref.s16(rng.randrange(0x10000)), biosref.s16(rng.randrange(0x10000)), rng.randrange(0x10000))
             for _ in range(60)]
    rows = []
    for sx, sy, angle in objs:
        want = [biosref.s16(v) for v in biosref.obj_affine(sx, sy, angle)]
        rows.append("    {" + ", ".join(str(v) for v in (sx, sy, biosref.s16(angle), *want)) + "},")
    parts.append(f"#define OBJ_COUNT {len(rows)}u\nstatic const int16_t obj_cases[][7] = {{\n")
    parts.append("\n".join(rows) + "\n};\n")

    bgs = []
    for _ in range(60):
        ox, oy = rng.randrange(-(1 << 20), 1 << 20), rng.randrange(-(1 << 20), 1 << 20)
        cx, cy = rng.randrange(-240, 240), rng.randrange(-160, 160)
        sx, sy = rng.randrange(-0x400, 0x400), rng.randrange(-0x400, 0x400)
        angle = rng.randrange(0x10000)
        pa, pb, pc, pd, x, y = biosref.bg_affine(ox, oy, cx, cy, sx, sy, angle)
        matrix = ", ".join(str(biosref.s16(v)) for v in (pa, pb, pc, pd))
        bgs.append(f"    {{{{{ox}, {oy}, {cx}, {cy}, {sx}, {sy}, 0x{angle:04x}, 0}}, {{{matrix}}}, "
                   f"{biosref.s32(x)}, {biosref.s32(y)}}},")
    parts.append(f"#define BG_COUNT {len(bgs)}u\nstatic const BgCase bg_cases[] = {{\n")
    parts.append("\n".join(bgs) + "\n};\n")
    return "".join(parts)


def test_bios_memory_calls():
    run_test("bios_copy", data=copy_data()).assert_passed()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_bios_copy.py -v`
Expected: FAIL — exit status 3: `BIOS function 0x0b is not implemented yet`

- [ ] **Step 3: Write the memory calls**

In `src/gbaport/native/build.py`, replace:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c",
)
```
with:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c",
)
```

In `src/gbaport/runtime/bios.c`, replace:
```c
 * Halt, Stop, the interrupt waits) and the small ones; the others are in
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq.
 * Any other BIOS function ends the run with an error that names it, for now.
```
with:
```c
 * Halt, Stop, the interrupt waits) and the small ones; the others are in
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq;
 * - bios_memory.c: CpuSet, CpuFastSet, BitUnPack, BgAffineSet, ObjAffineSet.
 * Any other BIOS function ends the run with an error that names it, for now.
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    case 0x0A: gba_bios_arctan2(rt); break;
    case 0x0D: ctx->r[0] = 0xBAAE187Fu; break;  /* GetBiosChecksum */
    case 0x19:  /* SoundBias: straight to the target level */
```
with:
```c
    case 0x0A: gba_bios_arctan2(rt); break;
    case 0x0B: gba_bios_cpu_set(rt); break;
    case 0x0C: gba_bios_cpu_fast_set(rt); break;
    case 0x0D: ctx->r[0] = 0xBAAE187Fu; break;  /* GetBiosChecksum */
    case 0x0E: gba_bios_bg_affine_set(rt); break;
    case 0x0F: gba_bios_obj_affine_set(rt); break;
    case 0x10: gba_bios_bit_unpack(rt); break;
    case 0x19:  /* SoundBias: straight to the target level */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_bios_midi_key_to_freq(GbaRuntime *rt);
```
with:
```c
void gba_bios_midi_key_to_freq(GbaRuntime *rt);
void gba_bios_cpu_set(GbaRuntime *rt);
void gba_bios_cpu_fast_set(GbaRuntime *rt);
void gba_bios_bit_unpack(GbaRuntime *rt);
void gba_bios_bg_affine_set(GbaRuntime *rt);
void gba_bios_obj_affine_set(GbaRuntime *rt);
```

Create `src/gbaport/runtime/bios_memory.c`:
```c
/* bios_memory.c - the BIOS's memory calls: CpuSet, CpuFastSet, BitUnPack, BgAffineSet and
 * ObjAffineSet.
 *
 * Like the BIOS, CpuSet and CpuFastSet do nothing when their source is in the BIOS area
 * (0x00000000-0x01FFFFFF). The affine calls use a 256-entry sine table in 1.14 fixed point,
 * round(16384 * sin(2 pi i / 256)); the BIOS keeps its own table of the same kind, so
 * results can differ from it in the lowest bit. */
#include "gba_runtime.h"

static const int16_t sine[256] = {
    0, 402, 804, 1205, 1606, 2006, 2404, 2801, 3196, 3590, 3981, 4370, 4756, 5139, 5520, 5897,
    6270, 6639, 7005, 7366, 7723, 8076, 8423, 8765, 9102, 9434, 9760, 10080, 10394, 10702, 11003, 11297,
    11585, 11866, 12140, 12406, 12665, 12916, 13160, 13395, 13623, 13842, 14053, 14256, 14449, 14635, 14811, 14978,
    15137, 15286, 15426, 15557, 15679, 15791, 15893, 15986, 16069, 16143, 16207, 16261, 16305, 16340, 16364, 16379,
    16384, 16379, 16364, 16340, 16305, 16261, 16207, 16143, 16069, 15986, 15893, 15791, 15679, 15557, 15426, 15286,
    15137, 14978, 14811, 14635, 14449, 14256, 14053, 13842, 13623, 13395, 13160, 12916, 12665, 12406, 12140, 11866,
    11585, 11297, 11003, 10702, 10394, 10080, 9760, 9434, 9102, 8765, 8423, 8076, 7723, 7366, 7005, 6639,
    6270, 5897, 5520, 5139, 4756, 4370, 3981, 3590, 3196, 2801, 2404, 2006, 1606, 1205, 804, 402,
    0, -402, -804, -1205, -1606, -2006, -2404, -2801, -3196, -3590, -3981, -4370, -4756, -5139, -5520, -5897,
    -6270, -6639, -7005, -7366, -7723, -8076, -8423, -8765, -9102, -9434, -9760, -10080, -10394, -10702, -11003, -11297,
    -11585, -11866, -12140, -12406, -12665, -12916, -13160, -13395, -13623, -13842, -14053, -14256, -14449, -14635, -14811, -14978,
    -15137, -15286, -15426, -15557, -15679, -15791, -15893, -15986, -16069, -16143, -16207, -16261, -16305, -16340, -16364, -16379,
    -16384, -16379, -16364, -16340, -16305, -16261, -16207, -16143, -16069, -15986, -15893, -15791, -15679, -15557, -15426, -15286,
    -15137, -14978, -14811, -14635, -14449, -14256, -14053, -13842, -13623, -13395, -13160, -12916, -12665, -12406, -12140, -11866,
    -11585, -11297, -11003, -10702, -10394, -10080, -9760, -9434, -9102, -8765, -8423, -8076, -7723, -7366, -7005, -6639,
    -6270, -5897, -5520, -5139, -4756, -4370, -3981, -3590, -3196, -2801, -2404, -2006, -1606, -1205, -804, -402
};

static int in_bios(uint32_t addr) { return (addr & 0x0E000000u) == 0; }

/* SWI 0x0B: copy or fill r2 & 0x1FFFFF units of 16 bits (32 with bit 26); bit 24 fills. */
void gba_bios_cpu_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t mode = ctx->r[2], count = mode & 0x1FFFFF;
    uint32_t size = mode & (1u << 26) ? 4 : 2;
    uint32_t src = ctx->r[0] & ~(size - 1), dst = ctx->r[1] & ~(size - 1);
    int fill = (mode >> 24) & 1;
    if (in_bios(src) || (!fill && count && in_bios(src + count * size - 1)))
        return;
    uint32_t value = size == 4 ? gba_read32(ctx, src) : gba_read16(ctx, src);
    for (uint32_t i = 0; i < count; i++) {
        if (!fill)
            value = size == 4 ? gba_read32(ctx, src + i * size) : gba_read16(ctx, src + i * size);
        if (size == 4)
            gba_write32(ctx, dst + i * size, value);
        else
            gba_write16(ctx, dst + i * size, value);
    }
    ctx->cycles += 20 + 4 * (uint64_t)count;
}

/* SWI 0x0C: copy or fill 32-bit words in blocks of 8 (the count is rounded up). */
void gba_bios_cpu_fast_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t mode = ctx->r[2], count = ((mode & 0x1FFFFF) + 7) & ~7u;
    uint32_t src = ctx->r[0] & ~3u, dst = ctx->r[1] & ~3u;
    int fill = (mode >> 24) & 1;
    if (in_bios(src) || (!fill && count && in_bios(src + count * 4 - 1)))
        return;
    uint32_t value = gba_read32(ctx, src);
    for (uint32_t i = 0; i < count; i++) {
        if (!fill)
            value = gba_read32(ctx, src + 4 * i);
        gba_write32(ctx, dst + 4 * i, value);
    }
    ctx->cycles += 20 + 2 * (uint64_t)count;
}

/* SWI 0x10: widen units. The info block at r2 holds the source length in bytes (16 bits),
 * the source and destination unit widths (8 bits each) and an offset (bits 0-30) added to
 * non-zero units, or to every unit when bit 31 is set. Words go out with 32-bit writes. */
void gba_bios_bit_unpack(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1] & ~3u, info = ctx->r[2];
    uint32_t length = gba_read16(ctx, info & ~1u);
    uint32_t src_width = gba_read8(ctx, info + 2), dst_width = gba_read8(ctx, info + 3);
    uint32_t offset = gba_read32(ctx, (info + 4) & ~3u);
    int widths_ok = (src_width == 1 || src_width == 2 || src_width == 4 || src_width == 8) &&
                    (dst_width == 1 || dst_width == 2 || dst_width == 4 || dst_width == 8 ||
                     dst_width == 16 || dst_width == 32);
    if (!widths_ok) {
        gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "BitUnPack with unit widths %u and %u ignored",
                      (unsigned)src_width, (unsigned)dst_width);
        return;
    }
    uint32_t out = 0, used = 0;
    for (uint32_t i = 0; i < length; i++) {
        uint32_t byte = gba_read8(ctx, src + i);
        for (uint32_t shift = 0; shift < 8; shift += src_width) {
            uint32_t unit = (byte >> shift) & ((1u << src_width) - 1);
            if (unit || (offset >> 31))
                unit += offset & 0x7FFFFFFF;
            out |= unit << used;
            used += dst_width;
            if (used == 32) {
                gba_write32(ctx, dst, out);
                dst += 4;
                out = used = 0;
            }
        }
    }
    ctx->cycles += 20 + 8 * (uint64_t)length;
}

static void rotation(int32_t sx, int32_t sy, uint32_t angle, int32_t m[4])
{
    uint32_t theta = (angle & 0xFFFF) >> 8;
    int32_t sin = sine[theta], cos = sine[(theta + 64) & 0xFF];
    m[0] = (sx * cos) >> 14;
    m[1] = (sx * -sin) >> 14;
    m[2] = (sy * sin) >> 14;
    m[3] = (sy * cos) >> 14;
}

/* SWI 0x0E: r2 entries of 20 bytes at r0 (s32 texture centre x, y in 24.8; s16 screen
 * centre x, y; s16 scale x, y in 8.8; u16 angle) become 16-byte BG affine parameters at r1
 * (pa, pb, pc, pd, then the start point x, y in 24.8). */
void gba_bios_bg_affine_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1];
    for (uint32_t n = ctx->r[2]; n; n--, src += 20, dst += 16) {
        int32_t ox = (int32_t)gba_read32(ctx, src), oy = (int32_t)gba_read32(ctx, src + 4);
        int32_t cx = (int16_t)gba_read16(ctx, src + 8), cy = (int16_t)gba_read16(ctx, src + 10);
        int32_t m[4];
        rotation((int16_t)gba_read16(ctx, src + 12), (int16_t)gba_read16(ctx, src + 14),
                 gba_read16(ctx, src + 16), m);
        for (int k = 0; k < 4; k++)
            gba_write16(ctx, dst + 2 * k, (uint32_t)m[k] & 0xFFFF);
        gba_write32(ctx, dst + 8, (uint32_t)(ox - (m[0] * cx + m[1] * cy)));
        gba_write32(ctx, dst + 12, (uint32_t)(oy - (m[2] * cx + m[3] * cy)));
        ctx->cycles += 60;
    }
}

/* SWI 0x0F: r2 entries of 8 bytes at r0 (s16 scale x, y in 8.8; u16 angle) become pa, pb,
 * pc, pd, written r3 bytes apart (2 for a plain array, 8 to go straight into OAM). */
void gba_bios_obj_affine_set(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], dst = ctx->r[1], stride = ctx->r[3];
    for (uint32_t n = ctx->r[2]; n; n--, src += 8, dst += 4 * stride) {
        int32_t m[4];
        rotation((int16_t)gba_read16(ctx, src), (int16_t)gba_read16(ctx, src + 2),
                 gba_read16(ctx, src + 4), m);
        for (int k = 0; k < 4; k++)
            gba_write16(ctx, dst + k * stride, (uint32_t)m[k] & 0xFFFF);
        ctx->cycles += 40;
    }
}
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 566 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms/bios_copy.c tests/runtime/test_bios_copy.py
git commit -m "feat: BIOS CpuSet, CpuFastSet, BitUnPack and the affine set-ups"
```

---

### Task 5: BIOS decompression

**Files:**
- Create: `src/gbaport/runtime/bios_decompress.c`, `tests/gbaroms/bios_decompress.c`
- Modify: `src/gbaport/runtime/bios.c`, `gba_runtime.h`, `src/gbaport/native/build.py`
- Test: `tests/runtime/test_bios_decompress.py`

**Interfaces:**
- Consumes: `biosref`'s compressors (Task 2).
- Produces: `gba_bios_lz77(rt, halfwords)`, `gba_bios_rl(rt, halfwords)`, `gba_bios_diff(rt, unit, halfwords)`, `gba_bios_huffman(rt)` (SWIs 0x11-0x18).
- **How they write:**
  - The Wram variants write bytes; the Vram variants write halfwords; Huffman writes 32-bit words.
  - LZ77 back-references read a 4 KiB window of what was written, not guest memory.
- **Bad streams:** a stream of the wrong type is ignored with a warning.

- [ ] **Step 1: Write the failing test**

Create `tests/gbaroms/bios_decompress.c`:
```c
/* The BIOS's decompressors on streams that biosref's compressors made (testdata.h): each
 * must give back the original bytes and write nothing past them. The Wram variants
 * decompress into EWRAM, the Vram ones (which must write halfwords) into BG VRAM. */
#include "testlib.h"
#include "testdata.h"

#define EWRAM_OUT 0x02020000u
#define VRAM_OUT 0x06000000u

typedef void (*Call)(const uint8_t *packed, uint32_t dst);

static void lz_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x11, in, o); }
static void lz_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x12, in, o); }
static void huffman(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x13, in, o); }
static void rl_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x14, in, o); }
static void rl_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x15, in, o); }
static void diff8_wram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x16, in, o); }
static void diff8_vram(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x17, in, o); }
static void diff16(const uint8_t *p, uint32_t d) { uint32_t in[4] = {(uint32_t)p, d}, o[4]; BIOS_CALL(0x18, in, o); }

static void run(const char *name, Call call, const Packed *cases, unsigned count, uint32_t dst)
{
    for (unsigned i = 0; i < count; i++) {
        const Packed *c = &cases[i];
        for (uint32_t k = 0; k < c->size + 4; k += 2)
            MEM16(dst + k) = 0xA5A5;
        call(c->packed, dst);
        for (uint32_t k = 0; k < c->size; k++)
            if (MEM8(dst + k) != c->plain[k]) {
                mismatch(name, i, k, MEM8(dst + k), c->plain[k]);
                break;
            }
        if (MEM16(dst + c->size + 2) != 0xA5A5)
            mismatch(name, i, c->size, MEM16(dst + c->size + 2), 0xA5A5);
    }
    check(name, mismatches() == 0);
}

int main(void)
{
    REG_DISPCNT = 0;  /* tile mode: 0x06000000 is BG VRAM */
    run("LZ77UnCompWram", lz_wram, lz_cases, LZ_COUNT, EWRAM_OUT);
    run("LZ77UnCompVram", lz_vram, lz_cases, LZ_COUNT, VRAM_OUT);
    run("HuffUnComp 8-bit", huffman, huff8_cases, HUFF8_COUNT, EWRAM_OUT);
    run("HuffUnComp 4-bit", huffman, huff4_cases, HUFF4_COUNT, EWRAM_OUT);
    run("RLUnCompWram", rl_wram, rl_cases, RL_COUNT, EWRAM_OUT);
    run("RLUnCompVram", rl_vram, rl_cases, RL_COUNT, VRAM_OUT);
    run("Diff8bitUnFilterWram", diff8_wram, diff8_cases, DIFF8_COUNT, EWRAM_OUT);
    run("Diff8bitUnFilterVram", diff8_vram, diff8_cases, DIFF8_COUNT, VRAM_OUT);
    run("Diff16bitUnFilter", diff16, diff16_cases, DIFF16_COUNT, VRAM_OUT);
    test_end();
    return 0;
}
```

Create `tests/runtime/test_bios_decompress.py`:
```python
import random

import biosref
from romtest import run_test


def _samples(rng: random.Random, count: int) -> list[bytes]:
    """Even-length data (multiples of 4) mixing runs, repeats and noise from few values."""
    samples = []
    for _ in range(count):
        alphabet = rng.sample(range(256), rng.randint(2, 20))
        data = bytearray()
        while len(data) < rng.randint(8, 1500):
            kind = rng.random()
            if kind < 0.3:
                data += bytes([rng.choice(alphabet)]) * rng.randint(3, 40)
            elif kind < 0.5 and len(data) > 8:
                start = rng.randrange(len(data) - 4)
                data += data[start : start + rng.randint(3, 18)]
            else:
                data.append(rng.choice(alphabet))
        samples.append(bytes(data[: len(data) - len(data) % 4]) or b"\x01\x02\x03\x04")
    return samples


def _cases(name: str, pairs: list[tuple[bytes, bytes]]) -> str:
    parts = []
    for i, (packed, plain) in enumerate(pairs):
        parts.append(biosref.c_bytes(f"{name}_packed_{i}", packed))
        parts.append(biosref.c_bytes(f"{name}_plain_{i}", plain))
    rows = ",\n".join(f"    {{{name}_packed_{i}, {name}_plain_{i}, {len(plain)}u}}" for i, (_, plain) in enumerate(pairs))
    parts.append(f"#define {name.upper()}_COUNT {len(pairs)}u\nstatic const Packed {name}_cases[] = {{\n{rows}\n}};\n")
    return "".join(parts)


def decompress_data() -> str:
    rng = random.Random(47)
    data = _samples(rng, 8)
    return "".join([
        "typedef struct { const uint8_t *packed; const uint8_t *plain; uint32_t size; } Packed;\n",
        _cases("lz", [(biosref.lz77_compress(d), d) for d in data]),
        _cases("rl", [(biosref.rl_compress(d), d) for d in data]),
        _cases("huff8", [(biosref.huffman_compress(d, 8), d) for d in data]),
        _cases("huff4", [(biosref.huffman_compress(d, 4), d) for d in data]),
        _cases("diff8", [(biosref.diff_filter(d, 1), d) for d in data]),
        _cases("diff16", [(biosref.diff_filter(d, 2), d) for d in data]),
    ])


def test_bios_decompressors_give_back_the_original():
    run_test("bios_decompress", data=decompress_data()).assert_passed()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_bios_decompress.py -v`
Expected: FAIL — exit status 3: `BIOS function 0x11 is not implemented yet`

- [ ] **Step 3: Write the decompressors**

In `src/gbaport/native/build.py`, replace:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c",
)
```
with:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c",
)
```

In `src/gbaport/runtime/bios.c`, replace:
```c
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq;
 * - bios_memory.c: CpuSet, CpuFastSet, BitUnPack, BgAffineSet, ObjAffineSet.
 * Any other BIOS function ends the run with an error that names it, for now.
```
with:
```c
 * - bios_math.c: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq;
 * - bios_memory.c: CpuSet, CpuFastSet, BitUnPack, BgAffineSet, ObjAffineSet;
 * - bios_decompress.c: the LZ77, Huffman, run-length and difference decompressors.
 * Any other BIOS function ends the run with an error that names it, for now.
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    case 0x10: gba_bios_bit_unpack(rt); break;
    case 0x19:  /* SoundBias: straight to the target level */
```
with:
```c
    case 0x10: gba_bios_bit_unpack(rt); break;
    case 0x11: gba_bios_lz77(rt, 0); break;
    case 0x12: gba_bios_lz77(rt, 1); break;
    case 0x13: gba_bios_huffman(rt); break;
    case 0x14: gba_bios_rl(rt, 0); break;
    case 0x15: gba_bios_rl(rt, 1); break;
    case 0x16: gba_bios_diff(rt, 1, 0); break;
    case 0x17: gba_bios_diff(rt, 1, 1); break;
    case 0x18: gba_bios_diff(rt, 2, 1); break;
    case 0x19:  /* SoundBias: straight to the target level */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_bios_obj_affine_set(GbaRuntime *rt);
```
with:
```c
void gba_bios_obj_affine_set(GbaRuntime *rt);
void gba_bios_lz77(GbaRuntime *rt, int halfwords);
void gba_bios_rl(GbaRuntime *rt, int halfwords);
void gba_bios_diff(GbaRuntime *rt, int unit, int halfwords);
void gba_bios_huffman(GbaRuntime *rt);
```

Create `src/gbaport/runtime/bios_decompress.c`:
```c
/* bios_decompress.c - the BIOS's decompressors: LZ77, Huffman, run-length and the
 * difference filters (GBATEK, "BIOS Decompression Functions").
 *
 * Every stream starts with a 32-bit header: the type in bits 4-7, a unit size in bits 0-3
 * (Huffman, filters) and the decompressed size in bytes in bits 8-31. The "Wram" variants
 * write bytes; the "Vram" variants collect two bytes and write halfwords, because VRAM
 * ignores byte writes. Huffman output goes out as 32-bit words. A stream of the wrong type
 * is ignored with a warning. */
#include "gba_runtime.h"

typedef struct {
    GbaCtx *ctx;
    uint32_t dst, size, written;
    int halfwords;
    uint32_t pending;           /* the low byte of a halfword not yet written */
    uint8_t window[0x1000];     /* the last 4 KiB written, for LZ77's back references */
} Output;

static void output_init(Output *out, GbaCtx *ctx, uint32_t dst, uint32_t size, int halfwords)
{
    out->ctx = ctx;
    out->dst = halfwords ? dst & ~1u : dst;
    out->size = size;
    out->written = 0;
    out->halfwords = halfwords;
    out->pending = 0;
}

static int output_full(const Output *out) { return out->written >= out->size; }

static void put(Output *out, uint32_t byte)
{
    if (output_full(out))
        return;
    byte &= 0xFF;
    out->window[out->written & 0xFFF] = (uint8_t)byte;
    if (!out->halfwords) {
        gba_write8(out->ctx, out->dst + out->written, byte);
    } else if (out->written & 1) {
        gba_write16(out->ctx, out->dst + out->written - 1, out->pending | byte << 8);
    } else {
        out->pending = byte;
    }
    out->written++;
}

static int check_type(GbaRuntime *rt, uint32_t header, uint32_t type, const char *name)
{
    if (((header >> 4) & 0xF) == type)
        return 1;
    gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "%s ignored a stream of type %u",
                  name, (unsigned)((header >> 4) & 0xF));
    return 0;
}

/* SWI 0x11 (Wram) and 0x12 (Vram). Flag bytes, MSB first: 0 = a literal byte, 1 = two
 * bytes giving a length of 3-18 and a distance of 1-4096 back into the output. */
void gba_bios_lz77(GbaRuntime *rt, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 1, "LZ77UnComp"))
        return;
    Output out;
    output_init(&out, ctx, ctx->r[1], header >> 8, halfwords);
    src += 4;
    while (!output_full(&out)) {
        uint32_t flags = gba_read8(ctx, src++);
        for (int bit = 7; bit >= 0 && !output_full(&out); bit--) {
            if (flags & (1u << bit)) {
                uint32_t a = gba_read8(ctx, src), b = gba_read8(ctx, src + 1);
                src += 2;
                uint32_t length = (a >> 4) + 3, distance = (((a & 0xF) << 8) | b) + 1;
                for (uint32_t k = 0; k < length; k++)
                    put(&out, out.window[(out.written - distance) & 0xFFF]);
            } else {
                put(&out, gba_read8(ctx, src++));
            }
        }
    }
    ctx->cycles += 30 + 6 * (uint64_t)out.size;
}

/* SWI 0x14 (Wram) and 0x15 (Vram). Flag byte: bit 7 set = the next byte repeated
 * (flag & 0x7F) + 3 times, clear = the next (flag & 0x7F) + 1 bytes as they are. */
void gba_bios_rl(GbaRuntime *rt, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 3, "RLUnComp"))
        return;
    Output out;
    output_init(&out, ctx, ctx->r[1], header >> 8, halfwords);
    src += 4;
    while (!output_full(&out)) {
        uint32_t flag = gba_read8(ctx, src++);
        if (flag & 0x80) {
            uint32_t byte = gba_read8(ctx, src++);
            for (uint32_t k = 0; k < (flag & 0x7F) + 3; k++)
                put(&out, byte);
        } else {
            for (uint32_t k = 0; k <= (flag & 0x7F); k++)
                put(&out, gba_read8(ctx, src++));
        }
    }
    ctx->cycles += 30 + 4 * (uint64_t)out.size;
}

/* SWI 0x16 (8-bit units, Wram), 0x17 (8-bit, Vram) and 0x18 (16-bit units): each unit is
 * the previous one plus the stored difference. */
void gba_bios_diff(GbaRuntime *rt, int unit, int halfwords)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0], header = gba_read32(ctx, src & ~3u);
    if (!check_type(rt, header, 8, "DiffUnFilter"))
        return;
    uint32_t size = header >> 8;
    src += 4;
    if (unit == 2) {
        uint32_t dst = ctx->r[1] & ~1u, value = 0;
        for (uint32_t i = 0; i + 1 < size; i += 2) {
            value = (value + gba_read16(ctx, (src + i) & ~1u)) & 0xFFFF;
            gba_write16(ctx, dst + i, value);
        }
    } else {
        Output out;
        output_init(&out, ctx, ctx->r[1], size, halfwords);
        uint32_t value = 0;
        for (uint32_t i = 0; i < size; i++) {
            value = (value + gba_read8(ctx, src + i)) & 0xFF;
            put(&out, value);
        }
    }
    ctx->cycles += 30 + 3 * (uint64_t)size;
}

/* SWI 0x13. After the header: the tree size byte (the bit stream starts (size + 1) * 2
 * bytes after it), then the tree, root first. A node's children are at
 * (node address & ~1) + (node & 0x3F) * 2 + 2 and one further; bit 7 (child 0) and bit 6
 * (child 1) mark children that are data. The bit stream is in 32-bit words, bit 31 first.
 * Units (4 or 8 bits) fill 32-bit output words from the low end. */
void gba_bios_huffman(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t src = ctx->r[0] & ~3u, dst = ctx->r[1] & ~3u, header = gba_read32(ctx, src);
    if (!check_type(rt, header, 2, "HuffUnComp"))
        return;
    uint32_t bits = header & 0xF, size = header >> 8;
    if (bits != 4 && bits != 8) {
        gba_warn_once(rt, GBA_WARN_BAD_ARGUMENT, "HuffUnComp ignored %u-bit units", (unsigned)bits);
        return;
    }
    uint32_t root = src + 5, stream = src + 4 + (gba_read8(ctx, src + 4) + 1) * 2;
    uint32_t node = root, word = 0, word_bits = 0, written = 0;
    while (written < size) {
        uint32_t code = gba_read32(ctx, stream);
        stream += 4;
        for (int k = 31; k >= 0 && written < size; k--) {
            uint32_t bit = (code >> k) & 1, value = gba_read8(ctx, node);
            uint32_t child = (node & ~1u) + (value & 0x3F) * 2 + 2 + bit;
            if (!(value & (0x80u >> bit))) {
                node = child;
                continue;
            }
            word |= gba_read8(ctx, child) << word_bits;
            word_bits += bits;
            node = root;
            if (word_bits == 32) {
                gba_write32(ctx, dst + written, word);
                written += 4;
                word = word_bits = 0;
            }
        }
    }
    ctx->cycles += 30 + 10 * (uint64_t)size;
}
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 567 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms/bios_decompress.c tests/runtime/test_bios_decompress.py
git commit -m "feat: BIOS LZ77, Huffman, run-length and difference decompression"
```

---

### Task 6: SRAM, Flash, save files and HardReset

**Files:**
- Create: `src/gbaport/runtime/save.c`
- Create test ROMs: `tests/gbaroms/save_sram.c`, `save_flash.c`, `hard_reset.c`, `save_then_fail.c`
- Modify: `src/gbaport/runtime/gba_runtime.h`, `runtime.c`, `memory.c`, `bios.c`, `host_headless.c` (replaced: `--save`)
- Modify: `src/gbaport/native/build.py` (the save type in `gba_rom.c`), `src/gbaport/analysis/analyze.py` (`Analysis.save`), `src/gbaport/cli.py`
- Modify: `tests/romtest.py` (`run_rom(..., save=PATH)`; every run gets a save file, blank by default)
- Test: `tests/runtime/test_saves.py`

**Interfaces:**
- Consumes: the Plan 4a memory map, run loop and host; `SaveType` (`gbaport.rom.savetype`); `GameConfig.save`.
- **Produces, C:**
  - Types: `GbaSaveType` (`GBA_SAVE_NONE`, `_SRAM`, `_FLASH64K`, `_FLASH128K`, `_EEPROM`) and `GbaSave`.
  - Generated: `gba_save_type` (in `gba_rom.c`).
  - For hosts:
    - `gba_save_data(rt, &size)` (size 0: nothing to store), `gba_save_dirty`, `gba_save_stored`;
    - `gba_save_load(rt, data, size)`, which returns -1 with `rt->error` set for a file of the wrong size and ignores a file for a game without a save chip.
  - Inside the runtime: `gba_save_init`, `gba_save_read8`, `gba_save_write8`, `gba_hard_reset` (SWI 0x26).
- **Produces, Python:** `Analysis.save`, `rom_identity(data, save)`, `generated_sources(lifted, rom_data, save)`, `SAVE_TYPES`.
- **The headless program:**
  - Command line: `<program> ROM [--frames N] [--save PATH]`, where PATH defaults to the ROM's path with `.sav`.
  - It writes the save once a second while it changes, and at the end of every run. It writes through `PATH.new` and a rename.
  - It exits with 2 for a save file of the wrong size, which it leaves untouched.

- [ ] **Step 1: Write the failing tests**

In `tests/romtest.py`, replace:
```python
    analysis = analyze_rom(image, parse_config(rom.config), ())
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    runtime = [path.read_bytes() for path in sorted(native.RUNTIME.glob("*.[ch]"))]
```
with:
```python
    analysis = analyze_rom(image, parse_config(rom.config), ())
    lifted = lift_program(analysis.program, analysis.exploration)
    files = native.generated_sources(lifted, rom.data, analysis.save)
    runtime = [path.read_bytes() for path in sorted(native.RUNTIME.glob("*.[ch]"))]
```

In `tests/romtest.py`, replace:
```python

def run_rom(rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set)."""
    program = native_program(rom)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    result = run_program([str(program), str(path), "--frames", str(frames)])
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)


def run_test(name: str, *, frames: int = 600, data: str = "") -> Run:
    return run_rom(build_test_rom(name, data), frames=frames)
```
with:
```python

def run_rom(
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None
) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set).

    The game's save file is ``save``; without one, every run starts with a blank save.
    """
    program = native_program(rom)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    with tempfile.TemporaryDirectory() as scratch:
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path)]
        result = run_program(command)
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)


def run_test(name: str, *, frames: int = 600, data: str = "", save: Path | None = None) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save)
```

Create `tests/gbaroms/save_sram.c`:
```c
/* SRAM: the 8-bit bus, its mirrors, and a signature that must survive into the next run.
 * The library ID string is how gbaport tells the game has SRAM. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";
static const char signature[8] = "GBAPORT";

#define SRAM ((volatile uint8_t *)0x0E000000)

int main(void)
{
    if (SRAM[0x100] == 0xFF) {
        for (int i = 0; i < 8; i++)
            SRAM[0x100 + i] = (uint8_t)signature[i];
        print("WROTE save");
    } else {
        int same = 1;
        for (int i = 0; i < 8; i++)
            same &= SRAM[0x100 + i] == (uint8_t)signature[i];
        check("the save survived", same);
    }

    expect("a blank byte reads 0xFF", SRAM[0x7FFF], 0xFF);
    SRAM[0x10] = 0x5A;
    expect("sram keeps a byte", SRAM[0x10], 0x5A);
    expect("16-bit reads repeat the byte", MEM16(0x0E000010), 0x5A5A);
    expect("32-bit reads repeat the byte", MEM32(0x0E000010), 0x5A5A5A5A);
    expect("sram mirror (32 KiB)", MEM8(0x0E008010), 0x5A);
    expect("sram mirror (0x0F000000)", MEM8(0x0F000010), 0x5A);
    MEM16(0x0E000020) = 0x1234;
    expect("16-bit writes store the low byte", SRAM[0x20], 0x34);
    test_end();
    return 0;
}
```

Create `tests/gbaroms/save_flash.c`:
```c
/* Flash: the chip ID, sector and chip erase, byte writes (which only clear bits), bank
 * switching on 128 KiB chips, and a signature that must survive into the next run.
 * testdata.h defines FLASH_ID (the library ID string), FLASH_CHIP and FLASH_BANKS. */
#include "testlib.h"
#include "testdata.h"

__attribute__((used)) static const char save_id[] = FLASH_ID;
static const char signature[8] = "GBAPORT";

#define FLASH ((volatile uint8_t *)0x0E000000)

static void command(uint8_t value)
{
    FLASH[0x5555] = 0xAA;
    FLASH[0x2AAA] = 0x55;
    FLASH[0x5555] = value;
}

static void write_byte(uint32_t offset, uint8_t value)
{
    command(0xA0);
    FLASH[offset] = value;
}

static void erase_sector(uint32_t offset)
{
    command(0x80);
    FLASH[0x5555] = 0xAA;
    FLASH[0x2AAA] = 0x55;
    FLASH[offset] = 0x30;
}

static void erase_chip(void)
{
    command(0x80);
    command(0x10);
}

static void select_bank(uint8_t bank)
{
    command(0xB0);
    FLASH[0] = bank;
}

static void write_signature(void)
{
    for (int i = 0; i < 8; i++)
        write_byte(0x100 + i, (uint8_t)signature[i]);
}

static int range_is(uint32_t from, uint32_t to, uint8_t value)
{
    for (uint32_t i = from; i < to; i++)
        if (FLASH[i] != value)
            return 0;
    return 1;
}

int main(void)
{
    command(0x90);
    uint32_t id = FLASH[0] | FLASH[1] << 8;
    command(0xF0);
    expect("flash chip id", id, FLASH_CHIP);
    check("ID mode ends", FLASH[0] != (FLASH_CHIP & 0xFF) || FLASH[1] != (FLASH_CHIP >> 8));

    if (FLASH[0x100] == 0xFF) {
        write_signature();
        print("WROTE save");
    } else {
        int same = 1;
        for (int i = 0; i < 8; i++)
            same &= FLASH[0x100 + i] == (uint8_t)signature[i];
        check("the save survived", same);
    }

    erase_sector(0x3000);
    check("a sector erase leaves 0xFF", range_is(0x3000, 0x4000, 0xFF));
    write_byte(0x3010, 0x5A);
    expect("a byte write", FLASH[0x3010], 0x5A);
    write_byte(0x3010, 0xF0);
    expect("a byte write only clears bits", FLASH[0x3010], 0x50);
    erase_sector(0x3000);
    expect("erasing again", FLASH[0x3010], 0xFF);
    expect("another sector is untouched", FLASH[0x100], (uint8_t)signature[0]);

    if (FLASH_BANKS == 2) {
        select_bank(1);
        erase_sector(0x3000);
        write_byte(0x3010, 0x77);
        expect("bank 1 keeps its byte", FLASH[0x3010], 0x77);
        select_bank(0);
        expect("bank 0 is separate", FLASH[0x3010], 0xFF);
    }

    erase_chip();
    check("a chip erase leaves 0xFF", range_is(0, 0x200, 0xFF) && range_is(0xFE00, 0x10000, 0xFF));
    write_signature();
    test_end();
    return 0;
}
```

Create `tests/gbaroms/hard_reset.c`:
```c
/* HardReset starts the game as if switched off and on: RAM and I/O registers are cleared,
 * only the save chip keeps its contents (here SRAM holds the progress across the reset). */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

#define SRAM ((volatile uint8_t *)0x0E000000)
#define MARKER MEM32(0x02000100)

int main(void)
{
    if (SRAM[0] != 1) {
        SRAM[0] = 1;
        MARKER = 0x48524553;
        REG_IE = IRQ_VBLANK;
        __asm__ volatile("svc #0x26" ::: "memory");
        print("FAIL HardReset returned");
    }
    SRAM[0] = 0xFF;
    expect("hard reset clears ewram", MARKER, 0);
    expect("hard reset clears the i/o registers", REG_IE, 0);
    expect("hard reset starts in system mode", get_cpsr() & 0xFF, 0x1F);
    test_end();
    return 0;
}
```

Create `tests/gbaroms/save_then_fail.c`:
```c
/* Writes the save, then runs into code the recompiler did not find: the save written
 * before the error must still reach the save file. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

int main(void)
{
    MEM8(0x0E000040) = 0x42;
    ((void (*)(void))0x08100001)();
    return 0;
}
```

Create `tests/runtime/test_saves.py`:
```python
import pytest
from romtest import build_test_rom, run_rom, run_test

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.native.build import rom_identity
from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveType

SIGNATURE = b"GBAPORT\0"


def _twice(name: str, save, data: str = ""):
    first = run_test(name, data=data, save=save)
    first.assert_passed()
    assert "WROTE save" in first.lines
    second = run_test(name, data=data, save=save)
    second.assert_passed()
    assert "PASS the save survived" in second.lines
    return save.read_bytes()


def test_sram_works_and_its_save_file_persists(tmp_path):
    data = _twice("save_sram", tmp_path / "game.sav")
    assert len(data) == 0x8000
    assert data[0x100:0x108] == SIGNATURE


@pytest.mark.parametrize("flash_id,chip,banks,size", [
    ("FLASH_V126", 0x1B32, 1, 0x10000),     # 64 KiB, Panasonic
    ("FLASH1M_V103", 0x1362, 2, 0x20000),   # 128 KiB, Sanyo
])
def test_flash_works_and_its_save_file_persists(tmp_path, flash_id, chip, banks, size):
    header = f'#define FLASH_ID "{flash_id}"\n#define FLASH_CHIP 0x{chip:04x}u\n#define FLASH_BANKS {banks}\n'
    data = _twice("save_flash", tmp_path / "game.sav", header)
    assert len(data) == size
    assert data[0x100:0x108] == SIGNATURE


def test_a_save_file_of_another_size_is_left_alone(tmp_path):
    save = tmp_path / "game.sav"
    save.write_bytes(bytes(100))
    run = run_rom(build_test_rom("save_sram"), save=save)
    assert run.status == 2
    assert "the save file has 100 bytes, but this game's save chip holds 32768" in run.stderr
    assert save.read_bytes() == bytes(100)


def test_a_save_written_before_a_runtime_error_reaches_the_file(tmp_path):
    save = tmp_path / "game.sav"
    run = run_test("save_then_fail", save=save)
    assert run.status == 3
    assert save.read_bytes()[0x40] == 0x42


def test_hard_reset_keeps_only_the_save(tmp_path):
    run_test("hard_reset", save=tmp_path / "game.sav").assert_passed()


def test_a_save_file_for_a_game_without_a_save_chip_is_ignored(tmp_path):
    save = tmp_path / "game.sav"
    save.write_bytes(b"old")
    run_test("hello", save=save).assert_passed()
    assert save.read_bytes() == b"old"


def test_the_save_type_comes_from_game_toml_or_the_library_id():
    rom = build_test_rom("save_sram")
    image = RomImage(rom.data)
    assert analyze_rom(image, parse_config(rom.config)).save is SaveType.SRAM
    configured = parse_config('[rom]\nsave = "flash128k"\n' + rom.config)
    assert analyze_rom(image, configured).save is SaveType.FLASH128K
    assert "gba_save_type = 3u;  /* flash128k */" in rom_identity(rom.data, SaveType.FLASH128K)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_saves.py`
Expected: FAIL — 8 failed with `AttributeError: 'Analysis' object has no attribute 'save'`.
- The kit now asks the analysis for the save chip, and passes `--save` to every run, which the host does not take yet.
- So until Step 3, every runtime test that builds a ROM fails the same way.

- [ ] **Step 3: Write the save chip, the save file and HardReset**

In `src/gbaport/native/build.py`, replace:
```python
``gba_rom.c``, which records where the game starts (the target of the cartridge's entry
branch, which the analysis starts from) and the size and CRC32 of the ROM the code came
from (the runtime refuses any other ROM). ``compile_native`` compiles those sources together with
the runtime in ``gbaport/runtime`` and one host (``host_headless.c`` so far).
"""
```
with:
```python
``gba_rom.c``, which records where the game starts (the target of the cartridge's entry
branch, which the analysis starts from), the size and CRC32 of the ROM the code came from
(the runtime refuses any other ROM) and which save chip the game has. ``compile_native``
compiles those sources together with the runtime in ``gbaport/runtime`` and one host
(``host_headless.c`` so far).
"""
```

In `src/gbaport/native/build.py`, replace:
```python
from gbaport.rom.image import ROM_BASE, RomImage
```
with:
```python
from gbaport.rom.image import ROM_BASE, RomImage
from gbaport.rom.savetype import SaveType
```

In `src/gbaport/native/build.py`, replace:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c",
)
```
with:
```python
    "runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c",
    "bios.c", "bios_math.c", "bios_memory.c", "bios_decompress.c", "save.c",
)
```

In `src/gbaport/native/build.py`, replace:
```python

def rom_identity(data: bytes) -> str:
    entry = parse_header(RomImage(data)).entry_point or ROM_BASE  # the analysis seeds this
```
with:
```python

SAVE_TYPES = {  # GbaSaveType in gba_runtime.h
    SaveType.NONE: 0, SaveType.SRAM: 1, SaveType.FLASH64K: 2, SaveType.FLASH128K: 3,
    SaveType.EEPROM: 4,
}


def rom_identity(data: bytes, save: SaveType = SaveType.NONE) -> str:
    entry = parse_header(RomImage(data)).entry_point or ROM_BASE  # the analysis seeds this
```

In `src/gbaport/native/build.py`, replace:
```python
        f"const uint32_t gba_rom_crc32 = 0x{zlib.crc32(data):08x}u;\n"
    )


def generated_sources(lifted: LiftedProgram, rom_data: bytes) -> dict[str, str]:
    """Every file `gbaport recompile` writes, by name."""
    files = program_files(lifted)
    files["gba_rom.c"] = rom_identity(rom_data)
    files[HEADER] = (PACKAGE / "lift" / HEADER).read_text(encoding="utf-8")
```
with:
```python
        f"const uint32_t gba_rom_crc32 = 0x{zlib.crc32(data):08x}u;\n"
        f"const uint32_t gba_save_type = {SAVE_TYPES[save]}u;  /* {save.value} */\n"
    )


def generated_sources(
    lifted: LiftedProgram, rom_data: bytes, save: SaveType = SaveType.NONE
) -> dict[str, str]:
    """Every file `gbaport recompile` writes, by name."""
    files = program_files(lifted)
    files["gba_rom.c"] = rom_identity(rom_data, save)
    files[HEADER] = (PACKAGE / "lift" / HEADER).read_text(encoding="utf-8")
```

In `src/gbaport/runtime/bios.c`, replace:
```c
 * - bios_decompress.c: the LZ77, Huffman, run-length and difference decompressors.
 * Any other BIOS function ends the run with an error that names it, for now.
 * The sound driver calls (0x1A-0x1E, 0x20-0x24, 0x28-0x2A) are ignored with a warning
```
with:
```c
 * - bios_decompress.c: the LZ77, Huffman, run-length and difference decompressors.
 * The sound driver calls (0x1A-0x1E, 0x20-0x24, 0x28-0x2A) are ignored with a warning
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    case 0x25: ctx->r[0] = 1; break;  /* MultiBoot fails: there is no link cable */
    case 0x27:  /* CustomHalt: r2's low byte goes to HALTCNT */
```
with:
```c
    case 0x25: ctx->r[0] = 1; break;  /* MultiBoot fails: there is no link cable */
    case 0x26: gba_hard_reset(rt); break;
    case 0x27:  /* CustomHalt: r2's low byte goes to HALTCNT */
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        gba_warn_once(rt, GBA_WARN_SWI, "ignoring SWI 0x%02x: the BIOS has no such function",
```
with:
```c
    default:
        gba_warn_once(rt, GBA_WARN_SWI, "ignoring SWI 0x%02x: the BIOS has no such function",
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c

typedef struct GbaRuntime GbaRuntime;
```
with:
```c

typedef enum {  /* the cartridge's save chip; gba_rom.c gives the game's */
    GBA_SAVE_NONE, GBA_SAVE_SRAM, GBA_SAVE_FLASH64K, GBA_SAVE_FLASH128K, GBA_SAVE_EEPROM,
} GbaSaveType;

typedef struct {
    GbaSaveType type;
    uint8_t data[0x20000];  /* the chip's contents (0xFF when blank) */
    uint32_t size;          /* bytes in use; for EEPROM 0 until its size is known */
    int dirty;              /* written since the host last stored it */
    int flash_step, flash_id_mode, flash_erase, flash_write, flash_bank_select;
    uint32_t flash_bank;
} GbaSave;

typedef struct GbaRuntime GbaRuntime;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    uint16_t keys_pressed;               /* GBA key bits, 1 = pressed */
```
with:
```c
    uint16_t keys_pressed;               /* GBA key bits, 1 = pressed */
    GbaSave save;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    jmp_buf end_jump;
    int resetting;
    GbaEnd end;
```
with:
```c
    jmp_buf end_jump;
    int resetting;    /* 1 = SoftReset, 2 = HardReset */
    GbaEnd end;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
extern const uint32_t gba_rom_crc32;
GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);
```
with:
```c
extern const uint32_t gba_rom_crc32;
extern const uint32_t gba_save_type;  /* a GbaSaveType */
GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
uint32_t gba_crc32(const uint8_t *data, uint32_t size);
```
with:
```c
uint32_t gba_crc32(const uint8_t *data, uint32_t size);
uint8_t *gba_save_data(GbaRuntime *rt, uint32_t *size);  /* size 0: nothing to store */
int gba_save_dirty(const GbaRuntime *rt);
void gba_save_stored(GbaRuntime *rt);
int gba_save_load(GbaRuntime *rt, const uint8_t *data, uint32_t size);  /* before gba_run */
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...);
```
with:
```c
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_hard_reset(GbaRuntime *rt);                  /* HardReset: power on again */
void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...);
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```
with:
```c

void gba_save_init(GbaRuntime *rt);
uint32_t gba_save_read8(GbaRuntime *rt, uint32_t addr);   /* 0x0E000000-0x0FFFFFFF */
void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value);

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
    rt->rom_size = size;
    if (size != gba_rom_size || gba_crc32(rom, size) != gba_rom_crc32) {
```
with:
```c
    rt->rom_size = size;
    gba_save_init(rt);
    if (size != gba_rom_size || gba_crc32(rom, size) != gba_rom_crc32) {
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
            return rt->end;
        rt->resetting = 0;
        entry = soft_reset(rt);
    }
```
with:
```c
            return rt->end;
        if (rt->resetting == 2) {  /* HardReset: as if switched off and on (saves stay) */
            power_on(rt);
            entry = gba_rom_entry;
        } else {
            entry = soft_reset(rt);
        }
        rt->resetting = 0;
    }
```

In `src/gbaport/runtime/runtime.c`, replace:
```c
    rt->resetting = 1;
    longjmp(rt->end_jump, 1);
```
with:
```c
    rt->resetting = 1;
    longjmp(rt->end_jump, 1);
}

void gba_hard_reset(GbaRuntime *rt)
{
    rt->resetting = 2;
    longjmp(rt->end_jump, 1);
```

Create `src/gbaport/runtime/save.c`:
```c
/* save.c - the cartridge's save chip: SRAM or Flash (GBATEK, "GBA Cart Backup").
 *
 * - SRAM: 32 KiB on an 8-bit bus at 0x0E000000 (mirrored up to 0x0FFFFFFF).
 * - Flash: 64 or 128 KiB, also on the 8-bit bus, driven by command sequences written to
 *   0x0E005555 and 0x0E002AAA: chip ID, chip and 4 KiB sector erase, byte write, and (128
 *   KiB) bank switching. It identifies as a Panasonic (64 KiB) or Sanyo (128 KiB) chip.
 *   Writes can only clear bits, as on the real chip; erasing sets them again.
 * Blank chips read 0xFF. The host stores and loads `data` through gba_save_*. */
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"

enum { FLASH_IDLE, FLASH_GOT_AA, FLASH_GOT_55 };

void gba_save_init(GbaRuntime *rt)
{
    GbaSave *s = &rt->save;
    memset(s, 0, sizeof *s);
    memset(s->data, 0xFF, sizeof s->data);
    s->type = (GbaSaveType)gba_save_type;
    switch (s->type) {
    case GBA_SAVE_SRAM: s->size = 0x8000; break;
    case GBA_SAVE_FLASH64K: s->size = 0x10000; break;
    case GBA_SAVE_FLASH128K: s->size = 0x20000; break;
    default: s->size = 0; break;  /* no save chip, or one not handled yet */
    }
}

/* ---- SRAM and Flash (0x0E000000-0x0FFFFFFF, 8-bit bus) -------------------------------- */

uint32_t gba_save_read8(GbaRuntime *rt, uint32_t addr)
{
    GbaSave *s = &rt->save;
    uint32_t offset = addr & 0xFFFF;
    switch (s->type) {
    case GBA_SAVE_SRAM:
        return s->data[offset & 0x7FFF];
    case GBA_SAVE_FLASH64K:
    case GBA_SAVE_FLASH128K:
        if (s->flash_id_mode && offset < 2) {
            static const uint8_t id[2][2] = {{0x32, 0x1B}, {0x62, 0x13}};  /* Panasonic, Sanyo */
            return id[s->type == GBA_SAVE_FLASH128K][offset];
        }
        return s->data[s->flash_bank * 0x10000 + offset];
    default:
        return 0xFF;
    }
}

static void flash_command(GbaSave *s, uint32_t offset, uint32_t value)
{
    if (s->flash_erase) {  /* AA 55 80 AA 55, then 10 at 5555 (chip) or 30 at a sector */
        s->flash_erase = 0;
        if (offset == 0x5555 && value == 0x10)
            memset(s->data, 0xFF, s->size);
        else if (value == 0x30)
            memset(s->data + s->flash_bank * 0x10000 + (offset & 0xF000), 0xFF, 0x1000);
        s->dirty = 1;
        return;
    }
    if (offset != 0x5555)
        return;
    switch (value) {
    case 0x90: s->flash_id_mode = 1; break;
    case 0xF0: s->flash_id_mode = 0; break;
    case 0x80: s->flash_erase = 1; break;
    case 0xA0: s->flash_write = 1; break;
    case 0xB0: s->flash_bank_select = s->type == GBA_SAVE_FLASH128K; break;
    default: break;
    }
}

static void flash_write8(GbaSave *s, uint32_t offset, uint32_t value)
{
    if (s->flash_write) {  /* the byte after AA 55 A0 is programmed */
        s->flash_write = 0;
        s->data[s->flash_bank * 0x10000 + offset] &= (uint8_t)value;
        s->dirty = 1;
        return;
    }
    if (s->flash_bank_select && offset == 0) {
        s->flash_bank_select = 0;
        s->flash_bank = value & 1;
        return;
    }
    switch (s->flash_step) {
    case FLASH_IDLE:
        if (offset == 0x5555 && value == 0xAA)
            s->flash_step = FLASH_GOT_AA;
        else if (value == 0xF0)
            s->flash_id_mode = 0;  /* a lone F0 ends ID mode on some chips */
        break;
    case FLASH_GOT_AA:
        s->flash_step = offset == 0x2AAA && value == 0x55 ? FLASH_GOT_55 : FLASH_IDLE;
        break;
    default:
        s->flash_step = FLASH_IDLE;
        flash_command(s, offset, value);
        break;
    }
}

void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value)
{
    GbaSave *s = &rt->save;
    value &= 0xFF;
    switch (s->type) {
    case GBA_SAVE_SRAM:
        s->data[addr & 0x7FFF] = (uint8_t)value;
        s->dirty = 1;
        break;
    case GBA_SAVE_FLASH64K:
    case GBA_SAVE_FLASH128K:
        flash_write8(s, addr & 0xFFFF, value);
        break;
    default:
        break;
    }
}

/* ---- for the host ------------------------------------------------------------------- */

uint8_t *gba_save_data(GbaRuntime *rt, uint32_t *size)
{
    *size = rt->save.size;
    return rt->save.data;
}

int gba_save_dirty(const GbaRuntime *rt) { return rt->save.dirty; }

void gba_save_stored(GbaRuntime *rt) { rt->save.dirty = 0; }

int gba_save_load(GbaRuntime *rt, const uint8_t *data, uint32_t size)
{
    GbaSave *s = &rt->save;
    if (s->type == GBA_SAVE_NONE)
        return 0;  /* nothing to load into, and nothing will be written back */
    if (size != s->size) {
        snprintf(rt->error, sizeof rt->error,
                 "the save file has %u bytes, but this game's save chip holds %s",
                 (unsigned)size, s->type == GBA_SAVE_SRAM ? "32768" :
                 s->type == GBA_SAVE_FLASH64K ? "65536" : "131072");
        return -1;
    }
    memcpy(s->data, data, size);
    return 0;
}
```

In `src/gbaport/runtime/memory.c`, replace:
```c
 * cartridge bus's open-bus pattern (each halfword reads as its address / 2); other
 * unmapped reads return 0. */
#include <string.h>
```
with:
```c
 * cartridge bus's open-bus pattern (each halfword reads as its address / 2); other
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus (wider reads repeat the byte). */
#include <string.h>
```

In `src/gbaport/runtime/memory.c`, replace:
```c
static int is_rom(uint32_t addr) { return addr >= 0x08000000u && addr < 0x0E000000u; }
```
with:
```c
static int is_rom(uint32_t addr) { return addr >= 0x08000000u && addr < 0x0E000000u; }
static int is_save(uint32_t addr) { return addr >= 0x0E000000u && addr < 0x10000000u; }
```

In `src/gbaport/runtime/memory.c`, replace:
```c
        return get16(mem + offset);
    const uint8_t *rom = rom_at(rt, addr, 2);
```
with:
```c
        return get16(mem + offset);
    if (is_save(addr))
        return gba_save_read8(rt, addr) * 0x0101u;
    const uint8_t *rom = rom_at(rt, addr, 2);
```

In `src/gbaport/runtime/memory.c`, replace:
```c
        return mem[offset];
    const uint8_t *rom = rom_at(rt, addr, 1);
```
with:
```c
        return mem[offset];
    if (is_save(addr))
        return gba_save_read8(rt, addr);
    const uint8_t *rom = rom_at(rt, addr, 1);
```

In `src/gbaport/runtime/memory.c`, replace:
```c
        return get32(mem + offset);
    const uint8_t *rom = rom_at(rt, addr, 4);  /* literal pools: the most common case */
```
with:
```c
        return get32(mem + offset);
    if (is_save(addr))
        return gba_save_read8(rt, addr) * 0x01010101u;
    const uint8_t *rom = rom_at(rt, addr, 4);  /* literal pools: the most common case */
```

In `src/gbaport/runtime/memory.c`, replace:
```c
            debug_write16(rt, addr, value);
        break;
```
with:
```c
            debug_write16(rt, addr, value);
        break;
    case 0x0E:
    case 0x0F:
        gba_save_write8(rt, addr, value);  /* the 8-bit bus takes the low byte */
        break;
```

In `src/gbaport/runtime/memory.c`, replace:
```c
    case 0x07: return;  /* OAM ignores byte writes */
    default: {
```
with:
```c
    case 0x07: return;  /* OAM ignores byte writes */
    case 0x0E:
    case 0x0F:
        gba_save_write8(rt, addr, value);
        return;
    default: {
```

Create `src/gbaport/runtime/host_headless.c` (replacing the current version):
```c
/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N] [--save PATH]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * The save chip's contents live in PATH (default: the ROM's path with .sav): loaded at the
 * start, stored once a second while they change and again at the end.
 * Exit status: 0 the game executed Stop, 2 bad arguments, the wrong ROM or an unusable save
 * file, 3 a runtime error (for example code the recompiler did not find), 4 the frame
 * limit was reached. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gba_runtime.h"

static unsigned long frame_limit;
static char save_path[1024];

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
    }
    fclose(f);
    *size = length > 0 ? (uint32_t)length : 0;
    return data;
}

/* Writes the save next to its file, then puts it in place, so a crash cannot leave half. */
static void store_save(GbaRuntime *rt)
{
    uint32_t size;
    uint8_t *data = gba_save_data(rt, &size);
    if (!gba_save_dirty(rt) || size == 0)
        return;
    char temp[sizeof save_path + 4];
    snprintf(temp, sizeof temp, "%s.new", save_path);
    FILE *f = fopen(temp, "wb");
    int ok = f && fwrite(data, 1, size, f) == size;
    if (f)
        ok = fclose(f) == 0 && ok;
    remove(save_path);
    if (ok && rename(temp, save_path) == 0)
        gba_save_stored(rt);
    else
        fprintf(stderr, "warning: cannot write the save file %s\n", save_path);
}

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    if (rt->frames % 60 == 0)
        store_save(rt);
    if (frame_limit && rt->frames >= frame_limit)
        gba_end(rt, GBA_END_HOST);
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

static void default_save_path(const char *rom_path)
{
    snprintf(save_path, sizeof save_path, "%s", rom_path);
    char *dot = strrchr(save_path, '.');
    char *slash = strrchr(save_path, '/'), *backslash = strrchr(save_path, '\\');
    if (dot && dot > slash && dot > backslash && strlen(save_path) + 4 < sizeof save_path)
        strcpy(dot, ".sav");
    else
        snprintf(save_path, sizeof save_path, "%s.sav", rom_path);
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    int bad = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc)
            frame_limit = strtoul(argv[++i], NULL, 10);
        else if (strcmp(argv[i], "--save") == 0 && i + 1 < argc)
            snprintf(save_path, sizeof save_path, "%s", argv[++i]);
        else if (!rom_path && argv[i][0] != '-')
            rom_path = argv[i];
        else
            bad = 1;
    }
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N] [--save PATH]\n", argv[0]);
        return 2;
    }
    if (!save_path[0])
        default_save_path(rom_path);
    uint32_t size;
    uint8_t *rom = read_file(rom_path, &size);
    if (!rom) {
        fprintf(stderr, "error: cannot read %s\n", rom_path);
        return 2;
    }
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, NULL};
    if (gba_init(&rt, rom, size, &host) != 0) {
        fprintf(stderr, "error: %s\n", rt.error);
        return 2;
    }
    uint32_t save_size;
    uint8_t *save = read_file(save_path, &save_size);
    if (save && gba_save_load(&rt, save, save_size) != 0) {
        fprintf(stderr, "error: %s: %s (the file was left as it is)\n", save_path, rt.error);
        return 2;
    }
    free(save);
    GbaEnd end = gba_run(&rt);
    store_save(&rt);
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt.error);
    else if (end == GBA_END_HOST)
        fprintf(stderr, "stopped after %lu frames\n", frame_limit);
    return (int)end;
}
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
from gbaport.rom.info import RomInfo, inspect_rom
```
with:
```python
from gbaport.rom.info import RomInfo, inspect_rom
from gbaport.rom.savetype import SaveType
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    detected: tuple[RamCode, ...] = ()  # copies the analysis found and adopted itself
```
with:
```python
    detected: tuple[RamCode, ...] = ()  # copies the analysis found and adopted itself
    save: SaveType = SaveType.NONE  # game.toml's [rom] save, else the ROM's library ID
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    program = build_program(exploration)
    return Analysis(info, exploration, program, coverage, config.ram_code + detected, detected)
```
with:
```python
    program = build_program(exploration)
    save = config.save or info.save.save_type
    ram_code = config.ram_code + detected
    return Analysis(info, exploration, program, coverage, ram_code, detected, save)
```

In `src/gbaport/cli.py`, replace:
```python
    lifted = lift_program(analysis.program, analysis.exploration)
    files = generated_sources(lifted, rom.data)
    write_sources(files, out)
```
with:
```python
    lifted = lift_program(analysis.program, analysis.exploration)
    files = generated_sources(lifted, rom.data, analysis.save)
    write_sources(files, out)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 575 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport tests/romtest.py tests/gbaroms tests/runtime/test_saves.py
git commit -m "feat: SRAM and Flash saves in save files, and HardReset"
```

---

### Task 7: EEPROM

**Files:**
- Create: `tests/gbaroms/save_eeprom.c`
- Modify: `src/gbaport/runtime/save.c`, `gba_runtime.h`, `memory.c`, `dma.c` (tells the EEPROM each DMA's length)
- Test: `tests/runtime/test_saves.py`

**Interfaces:**
- Consumes: Task 6's save chip and save files; the Plan 4a DMA.
- Produces: `gba_save_is_eeprom(rt, addr)` (0x0D000000-0x0DFFFFFF; for 32 MiB ROMs only 0x0DFFFF00 up), `gba_eeprom_dma(rt, count)`, `gba_eeprom_read(rt)`, `gba_eeprom_write(rt, value)`.
- **Size:**
  - The first DMA's length sets the chip's size: 9 or 73 halfwords for 512 bytes, 17 or 81 for 8 KiB. A 512- or 8192-byte save file sets it too.
  - Without either, the chip is the 512-byte one.

- [ ] **Step 1: Write the failing test**

In `tests/runtime/test_saves.py`, replace:
```python

def test_a_save_file_of_another_size_is_left_alone(tmp_path):
```
with:
```python

@pytest.mark.parametrize("bits,size", [(6, 0x200), (14, 0x2000)])
def test_eeprom_works_and_its_size_follows_the_dma_length(tmp_path, bits, size):
    data = _twice("save_eeprom", tmp_path / "game.sav", f"#define EEPROM_BITS {bits}\n")
    assert len(data) == size
    assert data[5 * 8 : 6 * 8] == SIGNATURE


def test_a_save_file_of_another_size_is_left_alone(tmp_path):
```

Create `tests/gbaroms/save_eeprom.c`:
```c
/* EEPROM through DMA 3, the way Nintendo's library drives it: read and write requests of
 * 64-bit blocks, the ready bit, and a signature that must survive into the next run.
 * testdata.h defines EEPROM_BITS: 6 for the 512-byte chip, 14 for the 8 KiB one. */
#include "testlib.h"
#include "testdata.h"

__attribute__((used)) static const char save_id[] = "EEPROM_V124";
static const uint8_t signature[8] = {'G', 'B', 'A', 'P', 'O', 'R', 'T', 0};

#define EEPROM 0x0D000000u

static uint16_t bits[96];

static void dma3(uint32_t src, uint32_t dst, uint32_t count)
{
    /* The compiler may move plain stores to `bits` past volatile register writes; the
     * barriers keep the buffer and the transfer in order. */
    __asm__ volatile("" ::: "memory");
    REG_DMA_SAD(3) = src;
    REG_DMA_DAD(3) = dst;
    REG_DMA_CNT(3) = count | 0x80000000u;  /* 16-bit units, immediately */
    __asm__ volatile("" ::: "memory");
}

static unsigned request(unsigned n, uint32_t kind, uint32_t block)
{
    bits[n++] = 1;
    bits[n++] = (uint16_t)kind;  /* 1: read, 0: write */
    for (int b = EEPROM_BITS - 1; b >= 0; b--)
        bits[n++] = (block >> b) & 1;
    return n;
}

static void read_block(uint32_t block, uint8_t out[8])
{
    unsigned n = request(0, 1, block);
    bits[n++] = 0;
    dma3((uint32_t)bits, EEPROM, n);
    dma3(EEPROM, (uint32_t)bits, 68);
    for (int i = 0; i < 8; i++) {
        uint8_t value = 0;
        for (int b = 0; b < 8; b++)
            value = (uint8_t)(value << 1 | (bits[4 + 8 * i + b] & 1));
        out[i] = value;
    }
}

static int write_block(uint32_t block, const uint8_t data[8])
{
    unsigned n = request(0, 0, block);
    for (int i = 0; i < 8; i++)
        for (int b = 7; b >= 0; b--)
            bits[n++] = (data[i] >> b) & 1;
    bits[n++] = 0;
    dma3((uint32_t)bits, EEPROM, n);
    for (int tries = 0; tries < 10000; tries++)
        if (MEM16(EEPROM) & 1)
            return 1;  /* ready */
    return 0;
}

static int same(const uint8_t *a, const uint8_t *b)
{
    for (int i = 0; i < 8; i++)
        if (a[i] != b[i])
            return 0;
    return 1;
}

int main(void)
{
    uint8_t block[8], blank[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    read_block(5, block);
    if (same(block, blank)) {
        check("writing the signature", write_block(5, signature));
        print("WROTE save");
    } else {
        check("the save survived", same(block, signature));
    }

    static const uint8_t first[8] = {1, 2, 3, 4, 5, 6, 7, 8}, second[8] = {0x80, 0, 0, 0, 0, 0, 0, 0x01};
    check("a write ends with the ready bit", write_block(2, first));
    read_block(2, block);
    check("a block reads back", same(block, first));
    write_block(2, second);
    read_block(2, block);
    check("a block is overwritten", same(block, second));
    read_block(7, block);
    check("a blank block reads 0xFF", same(block, blank));
    read_block(5, block);
    check("other blocks are untouched", same(block, signature));
    test_end();
    return 0;
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_saves.py -k eeprom -v`
Expected: FAIL, 2 failed: `DONE 0 passed, 6 failed`, starting with `FAIL the save survived`. Without the EEPROM, 0x0D000000 reads the cartridge's open-bus pattern (not a blank chip) and ignores writes.

- [ ] **Step 3: Write the EEPROM**

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
    uint32_t flash_bank;
} GbaSave;
```
with:
```c
    uint32_t flash_bank;
    int eeprom_address_bits;  /* 6 (512 bytes) or 14 (8 KiB) */
    uint8_t eeprom_in[96];    /* request bits received so far */
    uint32_t eeprom_count;
    uint64_t eeprom_out;      /* the block being read out */
    uint32_t eeprom_out_left; /* bits still to come: 4 ignored, then 64 */
} GbaSave;
```

In `src/gbaport/runtime/gba_runtime.h`, replace:
```c
void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value);
```
with:
```c
void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value);
int gba_save_is_eeprom(const GbaRuntime *rt, uint32_t addr);
void gba_eeprom_dma(GbaRuntime *rt, uint32_t count);      /* a DMA of count halfwords starts */
uint32_t gba_eeprom_read(GbaRuntime *rt);
void gba_eeprom_write(GbaRuntime *rt, uint32_t value);
```

In `src/gbaport/runtime/save.c`, replace:
```c
/* save.c - the cartridge's save chip: SRAM or Flash (GBATEK, "GBA Cart Backup").
 *
```
with:
```c
/* save.c - the cartridge's save chip: SRAM, Flash or EEPROM (GBATEK, "GBA Cart Backup").
 *
```

In `src/gbaport/runtime/save.c`, replace:
```c
 *   Writes can only clear bits, as on the real chip; erasing sets them again.
 * Blank chips read 0xFF. The host stores and loads `data` through gba_save_*. */
```
with:
```c
 *   Writes can only clear bits, as on the real chip; erasing sets them again.
 * - EEPROM: 512 bytes (6-bit block addresses) or 8 KiB (14-bit) behind 0x0D000000, one bit
 *   per halfword, normally by DMA. Requests: "11" + address + "0" reads a 64-bit block,
 *   which then comes out as 4 ignored bits and 64 data bits; "10" + address + 64 bits +
 *   "0" writes one. Reads report ready (1) when no block is coming out. The chip's size is
 *   not in the ROM: it follows from the first DMA's length (9 or 73 halfwords: 512 bytes;
 *   17 or 81: 8 KiB) or from a save file's size.
 * Blank chips read 0xFF. The host stores and loads `data` through gba_save_*. */
```

In `src/gbaport/runtime/save.c`, replace:
```c
    case GBA_SAVE_FLASH128K: s->size = 0x20000; break;
    default: s->size = 0; break;  /* no save chip, or one not handled yet */
    }
```
with:
```c
    case GBA_SAVE_FLASH128K: s->size = 0x20000; break;
    default: s->size = 0; break;  /* EEPROM: known after the first access */
    }
```

In `src/gbaport/runtime/save.c`, replace:
```c

/* ---- for the host ------------------------------------------------------------------- */
```
with:
```c

/* ---- EEPROM ------------------------------------------------------------------------- */

int gba_save_is_eeprom(const GbaRuntime *rt, uint32_t addr)
{
    if (rt->save.type != GBA_SAVE_EEPROM || (addr >> 24) != 0x0D)
        return 0;
    return rt->rom_size <= 0x01000000u || addr >= 0x0DFFFF00u;  /* 32 MiB ROMs: the top only */
}

static void eeprom_set_bits(GbaSave *s, int bits)
{
    s->eeprom_address_bits = bits;
    s->size = bits == 6 ? 0x200 : 0x2000;
}

void gba_eeprom_dma(GbaRuntime *rt, uint32_t count)
{
    GbaSave *s = &rt->save;
    if (s->eeprom_address_bits)
        return;
    if (count == 9 || count == 73)
        eeprom_set_bits(s, 6);
    else if (count == 17 || count == 81)
        eeprom_set_bits(s, 14);
}

static uint32_t eeprom_bits(const GbaSave *s, uint32_t first, uint32_t count)
{
    uint32_t value = 0;
    for (uint32_t i = first; i < first + count; i++)
        value = value << 1 | s->eeprom_in[i];
    return value;
}

void gba_eeprom_write(GbaRuntime *rt, uint32_t value)
{
    GbaSave *s = &rt->save;
    if (!s->eeprom_address_bits)
        eeprom_set_bits(s, 6);  /* no DMA to tell: the small chip */
    uint32_t bits = (uint32_t)s->eeprom_address_bits;
    s->eeprom_in[s->eeprom_count++] = value & 1;
    if (s->eeprom_count < 2)
        return;
    uint32_t command = eeprom_bits(s, 0, 2);
    uint32_t block = 0;
    if (s->eeprom_count >= 2 + bits)
        block = eeprom_bits(s, 2, bits) & ((s->size / 8) - 1);
    if (command == 3 && s->eeprom_count == 2 + bits + 1) {  /* read request */
        s->eeprom_out = 0;
        for (int i = 0; i < 8; i++)
            s->eeprom_out = s->eeprom_out << 8 | s->data[block * 8 + i];
        s->eeprom_out_left = 68;
        s->eeprom_count = 0;
    } else if (command == 2 && s->eeprom_count == 2 + bits + 64 + 1) {  /* write request */
        for (int i = 0; i < 8; i++)
            s->data[block * 8 + i] = (uint8_t)eeprom_bits(s, 2 + bits + 8 * i, 8);
        s->dirty = 1;
        s->eeprom_count = 0;
    } else if (command < 2 || s->eeprom_count >= sizeof s->eeprom_in) {
        s->eeprom_count = 0;  /* not a request: start over */
    }
}

uint32_t gba_eeprom_read(GbaRuntime *rt)
{
    GbaSave *s = &rt->save;
    if (!s->eeprom_out_left)
        return 1;  /* ready */
    s->eeprom_out_left--;
    if (s->eeprom_out_left >= 64)
        return 0;  /* the 4 bits before the data */
    return (uint32_t)(s->eeprom_out >> s->eeprom_out_left) & 1;
}

/* ---- for the host ------------------------------------------------------------------- */
```

In `src/gbaport/runtime/save.c`, replace:
```c
    GbaSave *s = &rt->save;
    if (s->type == GBA_SAVE_NONE)
```
with:
```c
    GbaSave *s = &rt->save;
    if (s->type == GBA_SAVE_EEPROM && (size == 0x200 || size == 0x2000))
        eeprom_set_bits(s, size == 0x200 ? 6 : 14);
    if (s->type == GBA_SAVE_NONE)
```

In `src/gbaport/runtime/save.c`, replace:
```c
                 "the save file has %u bytes, but this game's save chip holds %s",
                 (unsigned)size, s->type == GBA_SAVE_SRAM ? "32768" :
                 s->type == GBA_SAVE_FLASH64K ? "65536" : "131072");
```
with:
```c
                 "the save file has %u bytes, but this game's save chip holds %s",
                 (unsigned)size, s->type == GBA_SAVE_EEPROM ? "512 or 8192" :
                 s->type == GBA_SAVE_SRAM ? "32768" :
                 s->type == GBA_SAVE_FLASH64K ? "65536" : "131072");
```

In `src/gbaport/runtime/memory.c`, replace:
```c
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus (wider reads repeat the byte). */
#include <string.h>
```
with:
```c
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus (wider reads repeat the byte), and an EEPROM at 0x0D000000. */
#include <string.h>
```

In `src/gbaport/runtime/memory.c`, replace:
```c
        return get16(mem + offset);
    if (is_save(addr))
```
with:
```c
        return get16(mem + offset);
    if (gba_save_is_eeprom(rt, addr))
        return gba_eeprom_read(rt);
    if (is_save(addr))
```

In `src/gbaport/runtime/memory.c`, replace:
```c
            debug_write16(rt, addr, value);
        break;
```
with:
```c
            debug_write16(rt, addr, value);
        break;
    case 0x0D:
        if (gba_save_is_eeprom(rt, addr))
            gba_eeprom_write(rt, value);
        break;
```

In `src/gbaport/runtime/dma.c`, replace:
```c
    int32_t dst_step = step(dst_control, size), src_step = step(src_control, size);
    for (uint32_t i = 0; i < d->count; i++) {
```
with:
```c
    int32_t dst_step = step(dst_control, size), src_step = step(src_control, size);
    if (gba_save_is_eeprom(rt, d->dst) || gba_save_is_eeprom(rt, d->src))
        gba_eeprom_dma(rt, d->count);  /* the length tells the EEPROM's size */
    for (uint32_t i = 0; i < d->count; i++) {
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 577 passed (552 from Plans 1-4a, 25 new); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime tests/gbaroms/save_eeprom.c tests/runtime/test_saves.py
git commit -m "feat: EEPROM saves over DMA, 512 bytes or 8 KiB"
```

---

### Task 8: README, spec, the game's config, and a smoke test on the real dump

**Files:**
- Create: `games/BT4E/game.toml` (addresses and the ROM's SHA-1 only)
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Interfaces:**
- Consumes: everything above.
- Produces: the 70 entries BT4E needs. These are 26 constructors that start-up code reaches through a table of relative offsets, the IWRAM interrupt dispatcher's ARM handlers, and functions reached through pointers. They were found by running the native build and adding each address it reported.

- [ ] **Step 1: Write the game's config and the documentation**

Create `games/BT4E/game.toml`:
```toml
# Dragon Ball GT Transformation (BT4E). Addresses only: this file holds no ROM bytes.
#
# The entries are code the analysis cannot reach by itself, found by running the native
# build and adding each address it reported as missing:
# - 26 static constructors that start-up code (0x080359cc) calls through a table of
#   relative offsets at 0x08036778-0x080367df;
# - the IWRAM interrupt dispatcher's handlers (ARM, copied to 0x03000000 at start-up);
# - functions reached through pointers during the first minute of play.
[rom]
sha1 = "8dd4b6e95dca4554a919bff55128481a9a95b611"

[code]
entries = [
    0x03000604, 0x03000660, 0x030008d8, 0x03000d24,
]
thumb_entries = [
    0x0800308e, 0x0800dc9a, 0x0800dcbe, 0x0800e064, 0x0800e666, 0x0800ea48, 0x0801a3e6,
    0x08031750, 0x080324dc, 0x08032c84, 0x0803325c, 0x080332ea, 0x08033394, 0x080333d6,
    0x08033418, 0x080353e4, 0x08035406, 0x08035422, 0x080354c8, 0x080360b0, 0x080360b4,
    0x080360d4, 0x080360e4, 0x080360f4, 0x08036108, 0x0803613c, 0x08036148, 0x08036280,
    0x0803628c, 0x0803629c, 0x080362a8, 0x08036318, 0x08036504, 0x0803651c, 0x08036574,
    0x08036580, 0x08036590, 0x0803659c, 0x080365ac, 0x080365c8, 0x08036604, 0x08036628,
    0x08036644, 0x0803669c, 0x080366b8, 0x08039854, 0x080398ec, 0x080398f0, 0x080398f4,
    0x08039904, 0x080399c8, 0x08039a3c, 0x08039a50, 0x08039a64, 0x08039a68, 0x08039a6c,
    0x08039aa0, 0x08039ab8, 0x08039f98, 0x08039f9c, 0x0803a05c, 0x0803a1fc, 0x0803a200,
    0x0803a404, 0x0803a418, 0x0803b0fc,
]
```

In `README.md`, replace:
````markdown
    games/XXXX/build/XXXX.exe roms/mygame.gba [--frames N]

It runs without a window for now (the desktop window comes in Plan 4c). Lines the game
prints through mGBA's debug log go to stdout. It exits with 0 when the game executes the
BIOS Stop call, 2 for bad arguments or a different ROM, 3 for a runtime error, and 4 when
`--frames` runs out.

With Windows' Smart App Control on, Windows judges every newly built program by its
content and refuses some of them ("An Application Control policy has blocked this file").
Sometimes a second start works; a program it keeps refusing stays refused, and building
the same sources again gives the same file. Any change to the build (a new `game.toml`
entry, a new version of gbaport) gives a new file and a new verdict. Turning Smart App
Control off ends this, but Windows cannot turn it back on without a reinstall.
````
with:
````markdown
    games/XXXX/build/XXXX.exe roms/mygame.gba [--frames N] [--save PATH]

It runs without a window for now (the desktop window comes in Plan 4c). Lines the game
prints through mGBA's debug log go to stdout. It exits with 0 when the game executes the
BIOS Stop call, 2 for bad arguments, a different ROM or an unusable save file, 3 for a
runtime error, and 4 when `--frames` runs out.

The game's save chip (SRAM, Flash or EEPROM, as its library ID string or `game.toml`'s
`[rom] save` says) lives in a save file: `--save PATH`, by default the ROM's path with
`.sav` (`roms/mygame.sav`, which git ignores). It is written once a second while the game
changes it and again when the program ends, also after a runtime error. A save file of
the wrong size is refused and left as it is.

Windows' Smart App Control judges every newly built program by its content and refuses
some of them for good ("An Application Control policy has blocked this file"). `gbaport
build` checks that the program starts and, when Windows refuses it, links it again with a
few different bytes, up to 5 times.
````

In `README.md`, replace:
````markdown
Add the address to `games/<game_code>/game.toml` (`thumb_entries` or `entries`, as the
message says) and build again, or record a trace with mGBA (below).
````
with:
````markdown
Add the address to `games/<game_code>/game.toml` (`thumb_entries` or `entries`, as the
message says) and build again, or record a trace with mGBA (below).
`games/BT4E/game.toml` is an example: the entries Dragon Ball GT Transformation needs to
boot and play its first minute.
````

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
````markdown
- **Performance**: per-access memory dispatch; mitigated by region fast paths. The GBA
  workload (16.78 MHz CPU) is small for a modern phone.
````
with:
````markdown
- **Performance**: per-access memory dispatch; mitigated by region fast paths. The GBA
  workload (16.78 MHz CPU) is small for a modern phone.
- **Windows Smart App Control** refuses some freshly built, unsigned programs for good,
  judged by their content: `gbaport build` re-links a refused program with a random
  unused string until Windows takes it.
````

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 577 passed; ruff clean.

- [ ] **Step 3: Smoke-test on the real dump**

Run, from the repo root:

```bash
uv run python -m gbaport.cli build roms/mygame.gba --out build/bt4e
build/bt4e/build/BT4E.exe roms/mygame.gba --frames 3600 --save build/bt4e/bt4e.sav; echo "exit $?"
build/bt4e/build/BT4E.exe roms/mygame.gba --frames 3600 --save build/bt4e/bt4e.sav; echo "exit $?"
```

Expected for BT4E (validated before this plan was approved):
- **Build:** `config       games\BT4E\game.toml`, `functions    577`, `lift issues  0`, then `built ...BT4E.exe`.
- **First run:** `stopped after 3600 frames` and exit 4, in well under a second. No runtime error, and no warning. `build/bt4e/bt4e.sav` is 8192 bytes: the game set up its 8 KiB EEPROM, 47 blocks of 8 bytes.
- **Second run:** the same, starting from that save file, which stays unchanged.

The game cannot be seen yet: rendering comes in Plan 5 and the window in Plan 4c. Record the numbers in the ledger.

- [ ] **Step 4: Commit**

```bash
git add games/BT4E/game.toml README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: save files, the BT4E entries, and refused builds"
```

---

## Done criteria for Plan 4b

- `uv run pytest` passes 577 tests and `uv run ruff check src tests` is clean.
- Every BIOS call from 0x00 to 0x2A is handled.
  - Arithmetic, BitUnPack and the affine calls match `biosref` on hundreds of cases.
  - The decompressors give back the original data for streams `biosref` compressed, in EWRAM and in BG VRAM.
  - CpuSet and CpuFastSet copy, fill, round up and protect the BIOS.
  - The sound driver is ignored with a warning.
- SRAM, both Flash sizes and both EEPROM sizes work and survive into the next run through the save file. Save files of the wrong size are refused and left untouched.
- `gbaport build` gets programs past Windows' Smart App Control by linking them again when it refuses them.
- BT4E, with `games/BT4E/game.toml`, runs its first minute natively and keeps its EEPROM save across runs.
