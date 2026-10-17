# Plan 1 — Foundation (ROM ingest + ARMv4T decoders) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `gbaport` Python package with ROM inspection (`gbaport info`) and a verified ARMv4T ARM+Thumb decoder, formatter and linear disassembler (`gbaport disasm`).

**Architecture:** A pure-stdlib Python package under `src/gbaport/`. `rom/` reads a ROM image at its GBA bus address and parses the header and save hardware. `isa/` decodes ARM and Thumb into one shared `Instruction` model (Thumb is decoded into ARM-equivalent operations so later stages see one semantic model) and formats it as UAL assembly. Correctness is proven by round-tripping a corpus through the Keystone assembler (test-only dependency) and by totality tests over the whole Thumb space and a large random ARM sample.

**Tech Stack:** Python 3.13 (uv-managed), hatchling, pytest, ruff; test-only: keystone-engine 0.9.2.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md` (this plan is roadmap item P1)

## Global Constraints

- Python `>=3.13`, managed with uv (`uv sync`, `uv run …`); repo root is `C:\Users\J-ASUS\Dev\GBA`; shell commands are written for Git Bash.
- The `gbaport` package has **no runtime dependencies** (stdlib only). Keystone is a dev-group dependency imported only from `tests/`.
- Never commit ROM dumps, saves or bytes extracted from a ROM. Tests build synthetic ROMs with `tests/romkit.py`. No Nintendo logo or BIOS bytes anywhere in the repo.
- Target ISA is **ARMv4T only** (ARM7TDMI). Anything else (coprocessor, ARMv5+ BLX/CLZ/LDRD/STRD, ARMv6 media, Thumb-2, NV condition) decodes to `Op.UNDEFINED`. The decoder must never raise on any 32-bit word or 16-bit halfword.
- All addresses are absolute GBA bus addresses; the cartridge ROM is mapped at `0x08000000`. All computed addresses are masked to 32 bits.
- Formatter output must be Keystone 0.9.2 / LLVM **UAL** syntax: condition after the `s`/size suffix (`addseq`, `ldrbeq`, `ldmiaeq`); Thumb flag-setting ALU forms always carry `s` (`adds`, `lsls`) because the plain forms select 32-bit Thumb-2 encodings; branch operands are absolute targets (`b #0x8000020`); Thumb `adr` takes the byte offset (`adr r0, #8`).
- Commit messages are plain: no `Co-Authored-By` or other attribution trailer. Commits use the repo-local identity `Ken <ahmadsoud63@gmail.com>`.

## Review Focus

1. **Truncated or oversized ROM files** (fewer than 0xC0 bytes, odd length, over 32 MiB) must raise a clear `RomError`, never `IndexError`. Pinned in Task 2 (`test_rejects_rom_smaller_than_header`, `test_rejects_rom_larger_than_32_mib`, `test_reads_outside_rom_raise`).
2. **Data disassembled as code** (any bit pattern, including ARMv5+/Thumb-2 encodings) must decode to `Op.UNDEFINED` and format as a data directive instead of crashing. Pinned in Task 4 (`test_decoder_is_total_over_random_words`), Task 5 (`test_decoder_is_total_over_every_halfword`) and Task 6 (`test_every_thumb_halfword_formats`, `test_random_arm_words_format`).
3. **Disassembly running off the end of the ROM**, including a Thumb BL prefix in the very last halfword, must stop cleanly. Pinned in Task 7 (`test_stops_at_rom_end`, `test_bl_prefix_in_last_halfword_decodes_alone`).
4. **Backward branches near the start of the ROM** must produce correct 32-bit targets below 0x08000000, never negative numbers. Pinned in Task 4 (`beq #0x07fffff8` case) and Task 5 (`bne #0x07ffffe0`, `bl #0x07ff0000` cases).
5. **Bad user input to `disasm`** (unaligned `--start`, start outside the ROM) must give an `error:` message and exit code 1. Pinned in Task 7 (`test_unaligned_start_is_an_error`, `test_start_outside_rom_is_an_error`).

## File Structure

```
pyproject.toml                 package metadata, deps, pytest/ruff config
.python-version                uv Python pin (3.13)
.gitignore                     excludes ROMs, saves, build output, generated code
README.md                      setup + commands
src/gbaport/__init__.py        __version__
src/gbaport/cli.py             argparse entry point; one _add_*_command per subcommand
src/gbaport/rom/__init__.py    (empty)
src/gbaport/rom/image.py       RomImage, RomError, ROM_BASE, MAX_ROM_SIZE
src/gbaport/rom/header.py      RomHeader, parse_header, header_checksum
src/gbaport/rom/savetype.py    SaveType, SaveDetection, detect_save_type
src/gbaport/rom/info.py        RomInfo, inspect_rom
src/gbaport/isa/__init__.py    (empty)
src/gbaport/isa/bits.py        field, bit, sign_extend, ror32
src/gbaport/isa/model.py       Mode, Cond, Op, ShiftKind, Shift, Instruction, op groups
src/gbaport/isa/arm.py         decode_arm
src/gbaport/isa/thumb.py       decode_thumb
src/gbaport/isa/fmt.py         format_instruction
src/gbaport/disasm.py          disassemble, format_line
tests/romkit.py                build_rom: synthetic ROM images (independent of gbaport code)
tests/ksasm.py                 assemble: Keystone wrapper (test-only)
tests/test_cli.py
tests/test_disasm.py
tests/rom/test_header.py
tests/rom/test_savetype.py
tests/isa/test_bits.py
tests/isa/test_arm.py
tests/isa/test_thumb.py
tests/isa/test_fmt.py
tests/isa/test_roundtrip.py
```

---

### Task 1: Project scaffold and CLI skeleton

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`, `src/gbaport/__init__.py`, `src/gbaport/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `gbaport.__version__: str`; `gbaport.cli.build_parser() -> argparse.ArgumentParser`; `gbaport.cli.main(argv: list[str] | None = None) -> int` — dispatches to `args.handler(args)`, converts `OSError`/`ValueError` into `error: <message>` on stderr and return code 1. Console script `gbaport`.

- [ ] **Step 1: Initialise git and the project files**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git init -b main
mkdir -p src/gbaport tests
```

Create `pyproject.toml`:

```toml
[project]
name = "gbaport"
version = "0.1.0"
description = "Personal-use pipeline that turns GBA ROMs into native C ports"
requires-python = ">=3.13"
dependencies = []

[project.scripts]
gbaport = "gbaport.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.3",
    "ruff>=0.7",
    "keystone-engine==0.9.2",
]

[build-system]
requires = ["hatchling>=1.25"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gbaport"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py313"
```

Create `.python-version`:

```
3.13
```

Create `.gitignore`:

```
# ROM dumps and anything derived from them are never committed
roms/
*.gba
*.sav
games/*/generated/
build/

# Python
__pycache__/
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
```

Create `README.md`:

```markdown
# gbaport

Personal-use pipeline that turns a Game Boy Advance ROM dumped from your own cartridge
into native C, and from there into Android and iOS apps — with no emulator in the app.

Design: `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Never commit ROMs, saves, or anything extracted from them.** Put dumps in `roms/`
(gitignored).

## Setup

    uv sync

## Tests

    uv run pytest
    uv run ruff check src tests

## Commands
```

Create `src/gbaport/__init__.py`:

```python
"""gbaport: turn GBA ROMs into native C ports."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_cli.py`:

```python
import pytest

from gbaport import __version__
from gbaport.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"gbaport {__version__}"


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv sync && uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.cli'`

- [ ] **Step 4: Write minimal implementation**

Create `src/gbaport/cli.py`:

```python
"""Command-line entry point: ``gbaport <command> ...``."""

import argparse
import sys

from gbaport import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gbaport", description="GBA ROM to native C port pipeline."
    )
    parser.add_argument("--version", action="version", version=f"gbaport {__version__}")
    parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests and the console script**

Run: `uv run pytest tests/test_cli.py -v && uv run gbaport --version && uv run ruff check src tests`
Expected: 2 passed; prints `gbaport 0.1.0`; ruff reports `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore README.md src tests docs
git commit -m "feat: scaffold gbaport package and CLI"
```

---

### Task 2: ROM image and header parsing

**Files:**
- Create: `src/gbaport/rom/__init__.py` (empty), `src/gbaport/rom/image.py`, `src/gbaport/rom/header.py`, `tests/romkit.py`
- Test: `tests/rom/test_header.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `gbaport.rom.image`: `ROM_BASE = 0x08000000`, `HEADER_SIZE = 0xC0`, `MAX_ROM_SIZE = 32 * 1024 * 1024`, `class RomError(ValueError)`, `@dataclass(frozen=True) class RomImage(data: bytes)` with `load(path) -> RomImage`, `contains(addr: int, size: int = 1) -> bool`, `read(addr: int, size: int) -> bytes`, `read8/read16/read32(addr: int) -> int` (little-endian; raise `RomError` outside the ROM).
  - `gbaport.rom.header`: `@dataclass(frozen=True) class RomHeader(title: str, game_code: str, maker_code: str, version: int, entry_point: int | None, checksum: int, checksum_ok: bool)`, `header_checksum(data: bytes) -> int`, `parse_header(rom: RomImage) -> RomHeader`.
  - `tests/romkit.py`: `ROM_BASE`, `build_rom(code=b"", *, code_offset=0xC0, title=b"TESTGAME", game_code=b"ATST", maker=b"01", version=0, size=0x400, patches=None, fix_checksum=True) -> bytes`.

- [ ] **Step 1: Write the test helper and the failing tests**

Create `tests/romkit.py`:

```python
"""Synthetic GBA ROM images for tests.

Deliberately independent of gbaport's own code so it can act as an oracle.
The Nintendo logo area (0x04-0x9F) is left zeroed: the repo never contains it.
"""

ROM_BASE = 0x08000000


def build_rom(
    code: bytes = b"",
    *,
    code_offset: int = 0xC0,
    title: bytes = b"TESTGAME",
    game_code: bytes = b"ATST",
    maker: bytes = b"01",
    version: int = 0,
    size: int = 0x400,
    patches: dict[int, bytes] | None = None,
    fix_checksum: bool = True,
) -> bytes:
    """Build a ROM whose entry branch jumps to ``code`` placed at ``code_offset``.

    ``patches`` (file offset -> bytes) are applied before the header checksum is
    computed, so header patches still get a valid checksum unless
    ``fix_checksum`` is False.
    """
    assert code_offset + len(code) <= size, "code does not fit in the ROM"
    rom = bytearray(size)
    branch = ((code_offset - 8) >> 2) & 0xFFFFFF
    rom[0:4] = (0xEA000000 | branch).to_bytes(4, "little")
    rom[0xA0:0xAC] = title.ljust(12, b"\0")
    rom[0xAC:0xB0] = game_code
    rom[0xB0:0xB2] = maker
    rom[0xB2] = 0x96
    rom[0xBC] = version
    rom[code_offset:code_offset + len(code)] = code
    for offset, blob in (patches or {}).items():
        rom[offset:offset + len(blob)] = blob
    if fix_checksum:
        total = 0
        for byte in rom[0xA0:0xBD]:
            total -= byte
        rom[0xBD] = (total - 0x19) & 0xFF
    return bytes(rom)
```

Create `tests/rom/test_header.py`:

```python
import pytest
from romkit import ROM_BASE, build_rom

from gbaport.rom.header import parse_header
from gbaport.rom.image import MAX_ROM_SIZE, RomError, RomImage


def test_parses_header_fields():
    rom = RomImage(build_rom(title=b"POCKETDEMO", game_code=b"APDE", maker=b"7Z", version=2))
    header = parse_header(rom)
    assert header.title == "POCKETDEMO"
    assert header.game_code == "APDE"
    assert header.maker_code == "7Z"
    assert header.version == 2
    assert header.checksum_ok is True


def test_entry_point_follows_branch_at_rom_start():
    rom = RomImage(build_rom(code_offset=0x100, size=0x200))
    assert parse_header(rom).entry_point == ROM_BASE + 0x100


def test_entry_point_none_when_first_word_is_not_a_branch():
    rom = RomImage(build_rom(patches={0: b"\0\0\0\0"}))
    assert parse_header(rom).entry_point is None


def test_bad_checksum_is_reported_not_rejected():
    data = bytearray(build_rom())
    data[0xBD] ^= 0xFF
    assert parse_header(RomImage(bytes(data))).checksum_ok is False


def test_rejects_rom_smaller_than_header():
    with pytest.raises(RomError, match="too small"):
        RomImage(bytes(0xBF))


def test_rejects_rom_larger_than_32_mib():
    with pytest.raises(RomError, match="too large"):
        RomImage(bytes(MAX_ROM_SIZE + 1))


def test_rejects_missing_fixed_byte():
    with pytest.raises(RomError, match="0x96"):
        parse_header(RomImage(build_rom(patches={0xB2: b"\x00"})))


def test_reads_little_endian_values_at_bus_addresses():
    rom = RomImage(build_rom(code=bytes([0x78, 0x56, 0x34, 0x12])))
    assert rom.read8(ROM_BASE + 0xC0) == 0x78
    assert rom.read16(ROM_BASE + 0xC0) == 0x5678
    assert rom.read32(ROM_BASE + 0xC0) == 0x12345678


def test_reads_outside_rom_raise():
    rom = RomImage(build_rom(size=0x201))
    assert rom.contains(ROM_BASE + 0x200)
    assert not rom.contains(ROM_BASE + 0x200, 2)
    with pytest.raises(RomError, match="outside ROM"):
        rom.read16(ROM_BASE + 0x200)
    with pytest.raises(RomError, match="outside ROM"):
        rom.read8(ROM_BASE - 1)


def test_load_reads_file(tmp_path):
    path = tmp_path / "game.gba"
    path.write_bytes(build_rom())
    assert RomImage.load(path).data == build_rom()


def test_repr_does_not_dump_rom_bytes():
    assert len(repr(RomImage(build_rom()))) < 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rom/test_header.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.rom'`

- [ ] **Step 3: Write minimal implementation**

Create empty `src/gbaport/rom/__init__.py`.

Create `src/gbaport/rom/image.py`:

```python
"""Read-only view of a cartridge ROM mapped at its GBA bus address."""

from dataclasses import dataclass, field
from pathlib import Path

ROM_BASE = 0x08000000
HEADER_SIZE = 0xC0
MAX_ROM_SIZE = 32 * 1024 * 1024


class RomError(ValueError):
    """The file is not a usable GBA ROM, or an access fell outside it."""


@dataclass(frozen=True)
class RomImage:
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.data) < HEADER_SIZE:
            raise RomError(f"ROM too small: {len(self.data)} bytes, header needs {HEADER_SIZE}")
        if len(self.data) > MAX_ROM_SIZE:
            raise RomError(f"ROM too large: {len(self.data)} bytes, GBA maximum is {MAX_ROM_SIZE}")

    @classmethod
    def load(cls, path: str | Path) -> "RomImage":
        return cls(Path(path).read_bytes())

    def contains(self, addr: int, size: int = 1) -> bool:
        offset = addr - ROM_BASE
        return offset >= 0 and offset + size <= len(self.data)

    def read(self, addr: int, size: int) -> bytes:
        if not self.contains(addr, size):
            raise RomError(f"read of {size} bytes at {addr:#010x} is outside ROM")
        offset = addr - ROM_BASE
        return self.data[offset:offset + size]

    def read8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def read16(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 2), "little")

    def read32(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 4), "little")
```

Create `src/gbaport/rom/header.py`:

```python
"""Cartridge header (0x08000000-0x080000BF) parsing.

The Nintendo logo bytes (0x04-0x9F) are deliberately not checked, so the
repository never needs a copy of them.
"""

from dataclasses import dataclass

from gbaport.rom.image import ROM_BASE, RomError, RomImage

FIXED_BYTE_OFFSET = 0xB2
FIXED_BYTE_VALUE = 0x96


@dataclass(frozen=True)
class RomHeader:
    title: str
    game_code: str
    maker_code: str
    version: int
    entry_point: int | None  # target of the ARM branch at 0x08000000
    checksum: int
    checksum_ok: bool


def header_checksum(data: bytes) -> int:
    """Complement check over 0xA0-0xBC, computed the way the BIOS does."""
    total = 0
    for byte in data[0xA0:0xBD]:
        total -= byte
    return (total - 0x19) & 0xFF


def parse_header(rom: RomImage) -> RomHeader:
    data = rom.data
    if data[FIXED_BYTE_OFFSET] != FIXED_BYTE_VALUE:
        raise RomError(
            f"not a GBA ROM: header byte {FIXED_BYTE_OFFSET:#x} is "
            f"{data[FIXED_BYTE_OFFSET]:#04x}, expected {FIXED_BYTE_VALUE:#04x}"
        )
    return RomHeader(
        title=_ascii(data[0xA0:0xAC]),
        game_code=_ascii(data[0xAC:0xB0]),
        maker_code=_ascii(data[0xB0:0xB2]),
        version=data[0xBC],
        entry_point=_entry_point(rom.read32(ROM_BASE)),
        checksum=data[0xBD],
        checksum_ok=data[0xBD] == header_checksum(data),
    )


def _ascii(raw: bytes) -> str:
    return raw.rstrip(b"\0").decode("ascii", errors="replace")


def _entry_point(word: int) -> int | None:
    """Target of the unconditional ARM branch every cartridge starts with."""
    if word >> 24 != 0xEA:
        return None
    offset = word & 0xFFFFFF
    if offset & 0x800000:
        offset -= 0x1000000
    return (ROM_BASE + 8 + offset * 4) & 0xFFFFFFFF
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rom/test_header.py -v && uv run ruff check src tests`
Expected: 11 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/rom tests/romkit.py tests/rom/test_header.py
git commit -m "feat: ROM image access and header parsing"
```

---

### Task 3: Save-type detection and `gbaport info`

**Files:**
- Create: `src/gbaport/rom/savetype.py`, `src/gbaport/rom/info.py`
- Modify: `src/gbaport/cli.py` (register `info`), `README.md` (Commands section)
- Test: `tests/rom/test_savetype.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `RomImage`, `RomError` (Task 2); `RomHeader`, `parse_header` (Task 2); `build_rom` (Task 2); `main`, `build_parser` (Task 1).
- Produces:
  - `gbaport.rom.savetype`: `class SaveType(Enum)` with values `NONE="none"`, `EEPROM="eeprom"`, `SRAM="sram"`, `FLASH64K="flash64k"`, `FLASH128K="flash128k"`; `@dataclass(frozen=True) class SaveDetection(save_type: SaveType, markers: tuple[str, ...])`; `detect_save_type(rom: RomImage) -> SaveDetection`.
  - `gbaport.rom.info`: `@dataclass(frozen=True) class RomInfo(header: RomHeader, size: int, sha1: str, save: SaveDetection)` with `to_dict() -> dict`; `inspect_rom(rom: RomImage) -> RomInfo`.
  - CLI: `gbaport info ROM [--json]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/rom/test_savetype.py`:

```python
import pytest
from romkit import build_rom

from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveType, detect_save_type


def rom_with(*blobs: bytes) -> RomImage:
    patches = {0x200 + 0x40 * i: blob for i, blob in enumerate(blobs)}
    return RomImage(build_rom(size=0x400, patches=patches))


@pytest.mark.parametrize(
    "marker,expected",
    [
        (b"EEPROM_V124", SaveType.EEPROM),
        (b"SRAM_V113", SaveType.SRAM),
        (b"SRAM_F_V100", SaveType.SRAM),
        (b"FLASH_V126", SaveType.FLASH64K),
        (b"FLASH512_V131", SaveType.FLASH64K),
        (b"FLASH1M_V103", SaveType.FLASH128K),
    ],
)
def test_detects_library_marker(marker, expected):
    result = detect_save_type(rom_with(marker))
    assert result.save_type is expected
    assert result.markers == (marker.decode(),)


def test_no_marker_means_no_save():
    assert detect_save_type(rom_with()).save_type is SaveType.NONE


def test_marker_without_version_digits_is_ignored():
    assert detect_save_type(rom_with(b"FLASH_Vxyz")).save_type is SaveType.NONE


def test_first_marker_wins_and_all_are_reported():
    result = detect_save_type(rom_with(b"SRAM_V110", b"FLASH1M_V103"))
    assert result.save_type is SaveType.SRAM
    assert result.markers == ("SRAM_V110", "FLASH1M_V103")
```

Append to `tests/test_cli.py`:

```python
import json

from romkit import build_rom


def write_rom(tmp_path, **kwargs):
    path = tmp_path / "game.gba"
    path.write_bytes(build_rom(**kwargs))
    return path


def test_info_json_reports_header_and_save(tmp_path, capsys):
    path = write_rom(
        tmp_path, title=b"POCKETDEMO", game_code=b"APDE", patches={0x300: b"FLASH1M_V103"}
    )
    assert main(["info", str(path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["title"] == "POCKETDEMO"
    assert info["game_code"] == "APDE"
    assert info["entry_point"] == "0x080000c0"
    assert info["checksum_ok"] is True
    assert info["size"] == 0x400
    assert info["save_type"] == "flash128k"
    assert info["save_markers"] == ["FLASH1M_V103"]
    assert len(info["sha1"]) == 40


def test_info_text_output(tmp_path, capsys):
    assert main(["info", str(write_rom(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "title" in out and "TESTGAME" in out


def test_info_missing_file_fails_cleanly(tmp_path, capsys):
    assert main(["info", str(tmp_path / "nope.gba")]) == 1
    assert capsys.readouterr().err.startswith("error:")


def test_info_rejects_non_rom(tmp_path, capsys):
    path = tmp_path / "junk.gba"
    path.write_bytes(bytes(0x400))
    assert main(["info", str(path)]) == 1
    assert "not a GBA ROM" in capsys.readouterr().err
```

Move the two new imports (`import json`, `from romkit import build_rom`) to the top of `tests/test_cli.py` with the existing imports so ruff's E402 stays clean.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rom/test_savetype.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.rom.savetype'`, and the `info` CLI tests exit with code 2 (`invalid choice: 'info'`).

- [ ] **Step 3: Write minimal implementation**

Create `src/gbaport/rom/savetype.py`:

```python
"""Save-hardware detection from the library ID strings Nintendo's SDK embeds.

Every commercial game links one save library whose ID string (for example
``FLASH1M_V103``) sits in ROM. EEPROM size (512 B vs 8 KiB) cannot be told from
the string; the runtime infers it from the DMA transfer length.
"""

import re
from dataclasses import dataclass
from enum import Enum

from gbaport.rom.image import RomImage


class SaveType(Enum):
    NONE = "none"
    EEPROM = "eeprom"
    SRAM = "sram"
    FLASH64K = "flash64k"
    FLASH128K = "flash128k"


_MARKER = re.compile(rb"(EEPROM_V|SRAM_F_V|SRAM_V|FLASH1M_V|FLASH512_V|FLASH_V)\d{3}")
_TYPES = {
    b"EEPROM_V": SaveType.EEPROM,
    b"SRAM_V": SaveType.SRAM,
    b"SRAM_F_V": SaveType.SRAM,
    b"FLASH_V": SaveType.FLASH64K,
    b"FLASH512_V": SaveType.FLASH64K,
    b"FLASH1M_V": SaveType.FLASH128K,
}


@dataclass(frozen=True)
class SaveDetection:
    save_type: SaveType
    markers: tuple[str, ...]  # every library ID found, in ROM order


def detect_save_type(rom: RomImage) -> SaveDetection:
    matches = list(_MARKER.finditer(rom.data))
    if not matches:
        return SaveDetection(SaveType.NONE, ())
    markers = tuple(m.group(0).decode("ascii") for m in matches)
    return SaveDetection(_TYPES[matches[0].group(1)], markers)
```

Create `src/gbaport/rom/info.py`:

```python
"""One-call summary of a ROM: header, size, hash and save hardware."""

import hashlib
from dataclasses import dataclass

from gbaport.rom.header import RomHeader, parse_header
from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveDetection, detect_save_type


@dataclass(frozen=True)
class RomInfo:
    header: RomHeader
    size: int
    sha1: str
    save: SaveDetection

    def to_dict(self) -> dict:
        header = self.header
        return {
            "title": header.title,
            "game_code": header.game_code,
            "maker_code": header.maker_code,
            "version": header.version,
            "entry_point": None if header.entry_point is None else f"{header.entry_point:#010x}",
            "checksum_ok": header.checksum_ok,
            "size": self.size,
            "sha1": self.sha1,
            "save_type": self.save.save_type.value,
            "save_markers": list(self.save.markers),
        }


def inspect_rom(rom: RomImage) -> RomInfo:
    return RomInfo(
        header=parse_header(rom),
        size=len(rom.data),
        sha1=hashlib.sha1(rom.data).hexdigest(),
        save=detect_save_type(rom),
    )
```

Modify `src/gbaport/cli.py` — replace the imports and `build_parser`, and add the `info` command:

```python
"""Command-line entry point: ``gbaport <command> ...``."""

import argparse
import json
import sys

from gbaport import __version__
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gbaport", description="GBA ROM to native C port pipeline."
    )
    parser.add_argument("--version", action="version", version=f"gbaport {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _add_info_command(commands)
    return parser


def _add_info_command(commands) -> None:
    info = commands.add_parser("info", help="show ROM header, hash and save type")
    info.add_argument("rom", help="path to a .gba file")
    info.add_argument("--json", action="store_true", help="print JSON instead of text")
    info.set_defaults(handler=_run_info)


def _run_info(args: argparse.Namespace) -> int:
    summary = inspect_rom(RomImage.load(args.rom)).to_dict()
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key:<13}{value}")
    return 0
```

(`main` and the `__main__` block stay unchanged.)

Append to the `## Commands` section of `README.md`:

```markdown
    uv run gbaport info roms/mygame.gba [--json]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run ruff check src tests`
Expected: all tests pass (6 CLI + 11 header + 9 save type = 26); ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/rom/savetype.py src/gbaport/rom/info.py src/gbaport/cli.py README.md tests/rom/test_savetype.py tests/test_cli.py
git commit -m "feat: save-type detection and gbaport info"
```

---

### Task 4: Instruction model and ARM decoder

**Files:**
- Create: `src/gbaport/isa/__init__.py` (empty), `src/gbaport/isa/bits.py`, `src/gbaport/isa/model.py`, `src/gbaport/isa/arm.py`
- Test: `tests/isa/test_bits.py`, `tests/isa/test_arm.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `gbaport.isa.bits`: `field(word, hi, lo) -> int`, `bit(word, n) -> bool`, `sign_extend(value, bits) -> int`, `ror32(value, amount) -> int`.
  - `gbaport.isa.model`: `Mode` (`ARM`, `THUMB`), `Cond(IntEnum)` (`EQ`=0 … `AL`=14), `Op(Enum)` (values are lowercase mnemonics: data-processing ops, `MUL MLA UMULL UMLAL SMULL SMLAL LDR STR LDRB STRB LDRH STRH LDRSB LDRSH LDM STM SWP SWPB B BL BX SWI MRS MSR BL_HI BL_LO UNDEFINED`), `ShiftKind` (`LSL LSR ASR ROR RRX`), `SHIFT_FIELD_KINDS`, `@dataclass(frozen=True) Shift(kind, amount=0, reg=None)` with `Shift.from_imm_field(kind_bits, amount) -> Shift | None`, `@dataclass(frozen=True) Instruction(...)` (fields listed in the code below), `DATA_PROCESSING_OPS: tuple[Op, ...]` (index = ARM opcode), `COMPARE_OPS`, `MOVE_OPS`.
  - `gbaport.isa.arm`: `decode_arm(word: int, addr: int) -> Instruction`.

- [ ] **Step 1: Write the failing tests**

Create `tests/isa/test_bits.py`:

```python
from gbaport.isa.bits import bit, field, ror32, sign_extend


def test_field_extracts_inclusive_range():
    assert field(0xE3A004FF, 31, 28) == 0xE
    assert field(0xE3A004FF, 11, 8) == 0x4


def test_bit():
    assert bit(0b1000, 3) is True
    assert bit(0b1000, 2) is False


def test_sign_extend():
    assert sign_extend(0xFFFFFC, 24) == -4
    assert sign_extend(0x7FFFFF, 24) == 0x7FFFFF
    assert sign_extend(0xEE, 8) == -18


def test_ror32():
    assert ror32(0xFF, 8) == 0xFF000000
    assert ror32(0x0F, 4) == 0xF0000000
    assert ror32(0x12345678, 0) == 0x12345678
```

Create `tests/isa/test_arm.py` (every word below was produced by Keystone from the text in the first column, at address 0x08000000):

```python
import random

import pytest

from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Cond, Mode, Op, Shift, ShiftKind

BASE = 0x08000000

CASES = [
    ("add r0, r1, r2, lsl #3", 0xE0810182,
     dict(op=Op.ADD, cond=Cond.AL, s=False, rd=0, rn=1, rm=2, shift=Shift(ShiftKind.LSL, 3))),
    ("addseq r0, r1, r2", 0x00910002,
     dict(op=Op.ADD, cond=Cond.EQ, s=True, rd=0, rn=1, rm=2, shift=None)),
    ("mov r0, #0xff000000", 0xE3A004FF,
     dict(op=Op.MOV, rd=0, rn=None, imm=0xFF000000, imm_rot=4)),
    ("mov r0, r1, lsl r2", 0xE1A00211,
     dict(op=Op.MOV, rd=0, rm=1, shift=Shift(ShiftKind.LSL, reg=2))),
    ("movs r0, r1, lsr #32", 0xE1B00021,
     dict(op=Op.MOV, s=True, rm=1, shift=Shift(ShiftKind.LSR, 32))),
    ("mov r0, r1, rrx", 0xE1A00061, dict(op=Op.MOV, rm=1, shift=Shift(ShiftKind.RRX))),
    ("tst r0, r1, lsl #3", 0xE1100181,
     dict(op=Op.TST, s=True, rd=None, rn=0, rm=1, shift=Shift(ShiftKind.LSL, 3))),
    ("teq r0, #1", 0xE3300001, dict(op=Op.TEQ, rn=0, imm=1, imm_rot=0)),
    ("mulseq r0, r1, r2", 0x00100291,
     dict(op=Op.MUL, cond=Cond.EQ, s=True, rd=0, rm=1, rs=2, rn=None)),
    ("mla r0, r1, r2, r3", 0xE0203291, dict(op=Op.MLA, rd=0, rm=1, rs=2, rn=3)),
    ("umull r0, r1, r2, r3", 0xE0810392, dict(op=Op.UMULL, rd=0, rd_hi=1, rm=2, rs=3)),
    ("smlals r0, r1, r2, r3", 0xE0F10392,
     dict(op=Op.SMLAL, s=True, rd=0, rd_hi=1, rm=2, rs=3)),
    ("swpb r0, r1, [r2]", 0xE1420091, dict(op=Op.SWPB, rd=0, rm=1, rn=2)),
    ("bx lr", 0xE12FFF1E, dict(op=Op.BX, rm=14)),
    ("bl #0x08000100", 0xEB00003E, dict(op=Op.BL, target=0x08000100)),
    ("beq #0x07fffff8", 0x0AFFFFFC, dict(op=Op.B, cond=Cond.EQ, target=0x07FFFFF8)),
    ("svc #0x50000", 0xEF050000, dict(op=Op.SWI, imm=0x50000)),
    ("mrs r0, spsr", 0xE14F0000, dict(op=Op.MRS, rd=0, spsr=True)),
    ("msr cpsr_fc, r0", 0xE129F000, dict(op=Op.MSR, spsr=False, psr_mask=0b1001, rm=0)),
    ("msr cpsr_f, #0xf0000000", 0xE328F20F,
     dict(op=Op.MSR, psr_mask=0b1000, imm=0xF0000000, imm_rot=2)),
    ("ldr r0, [r1, r2, lsl #2]", 0xE7910102,
     dict(op=Op.LDR, rd=0, rn=1, rm=2, shift=Shift(ShiftKind.LSL, 2),
          pre=True, up=True, writeback=False)),
    ("str r0, [r1], -r2, asr #3", 0xE60101C2,
     dict(op=Op.STR, pre=False, up=False, writeback=True, user=False, rm=2,
          shift=Shift(ShiftKind.ASR, 3))),
    ("ldrbt r0, [r1], #4", 0xE4F10004,
     dict(op=Op.LDRB, pre=False, writeback=True, user=True, imm=4)),
    ("ldr r0, [r1, #-4]!", 0xE5310004,
     dict(op=Op.LDR, pre=True, up=False, writeback=True, imm=4, target=None)),
    ("ldr r0, [pc, #8]", 0xE59F0008, dict(op=Op.LDR, rn=15, imm=8, target=0x08000010)),
    ("ldrh r0, [r1, #2]", 0xE1D100B2, dict(op=Op.LDRH, rd=0, rn=1, imm=2, pre=True)),
    ("ldrsh r0, [r1], #-4", 0xE05100F4,
     dict(op=Op.LDRSH, pre=False, up=False, writeback=True, imm=4)),
    ("ldrh r0, [r1, -r2]!", 0xE13100B2,
     dict(op=Op.LDRH, rm=2, up=False, writeback=True, imm=None)),
    ("ldmfd sp!, {r4-r7, pc}", 0xE8BD80F0,
     dict(op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=(4, 5, 6, 7, 15))),
    ("stmdb sp!, {r4, lr}", 0xE92D4010,
     dict(op=Op.STM, rn=13, pre=True, up=False, writeback=True, reglist=(4, 14))),
    ("ldm r0, {r1, r2}^", 0xE8D00006,
     dict(op=Op.LDM, user=True, writeback=False, reglist=(1, 2))),
]


@pytest.mark.parametrize("text,word,expected", CASES, ids=[case[0] for case in CASES])
def test_decode(text, word, expected):
    ins = decode_arm(word, BASE)
    assert {key: getattr(ins, key) for key in expected} == expected
    assert (ins.mode, ins.size, ins.raw, ins.addr) == (Mode.ARM, 4, word, BASE)


UNDEFINED = [
    ("NV condition", 0xF0000000),
    ("mcr (coprocessor)", 0xEE000010),
    ("ldc (coprocessor transfer)", 0xEC000000),
    ("clz (ARMv5)", 0xE16F0F11),
    ("blx reg (ARMv5)", 0xE12FFF31),
    ("ldrd (ARMv5TE)", 0xE1C000D0),
    ("media space (ARMv6)", 0xE6100010),
    ("movw (ARMv6T2)", 0xE3000000),
    ("unallocated multiply space", 0xE1600090),
    ("halfword post-index with W", 0xE0B100B2),
]


@pytest.mark.parametrize("name,word", UNDEFINED, ids=[case[0] for case in UNDEFINED])
def test_non_armv4t_encodings_are_undefined(name, word):
    assert decode_arm(word, BASE).op is Op.UNDEFINED


def test_decoder_is_total_over_random_words():
    rng = random.Random(1234)
    for _ in range(200_000):
        word = rng.getrandbits(32)
        ins = decode_arm(word, BASE)
        assert ins.size == 4 and ins.raw == word
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/isa -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.isa'`

- [ ] **Step 3: Write the bit helpers and the model**

Create empty `src/gbaport/isa/__init__.py`.

Create `src/gbaport/isa/bits.py`:

```python
"""Bit-twiddling helpers shared by the decoders."""


def field(word: int, hi: int, lo: int) -> int:
    """Return bits ``hi..lo`` (inclusive) of ``word``."""
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


def bit(word: int, n: int) -> bool:
    return bool((word >> n) & 1)


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def ror32(value: int, amount: int) -> int:
    amount &= 31
    return ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF
```

Create `src/gbaport/isa/model.py`:

```python
"""Decoded-instruction model shared by the ARM and Thumb decoders.

Thumb instructions decode into the equivalent ARM operation, so analysis and
lifting handle one semantic model. Field meanings per operation:

- Data processing: ``rd`` (None for TST/TEQ/CMP/CMN), ``rn`` (None for
  MOV/MVN); the second operand is ``imm`` (``imm_rot`` is the ARM rotate field,
  needed for the shifter carry-out) or ``rm`` with an optional ``shift``.
- MUL: rd = rm * rs.  MLA: rd = rm * rs + rn.
- Long multiply: ``rd`` is RdLo, ``rd_hi`` is RdHi, operands ``rm`` and ``rs``.
- Single/halfword transfer: ``rd`` data register, ``rn`` base; the offset is
  ``imm`` (a magnitude) or ``rm`` (+``shift``). ``up`` adds the offset, ``pre``
  applies it before the access, ``writeback`` updates the base (always true
  when post-indexed), ``user`` marks LDRT/STRT.
- Block transfer: ``rn``, ``reglist``, ``pre``/``up``/``writeback``; ``user``
  is the ``^`` (S) bit.
- SWP/SWPB: rd <- [rn], then [rn] <- rm.
- B/BL: absolute ``target``.  BX: ``rm``.  SWI: ``imm`` is the comment field.
- MRS: ``rd``, ``spsr``.  MSR: ``spsr``, ``psr_mask`` (bit0 c, bit1 x, bit2 s,
  bit3 f) and ``rm`` or ``imm``/``imm_rot``.
- BL_HI/BL_LO: a Thumb BL half seen without its partner; ``imm`` is the
  sign-extended high offset (already << 12) or the low offset (already << 1).

``target`` is also set to the absolute address of PC-relative literal loads and
Thumb ADR; when present it takes precedence over ``rn == 15`` arithmetic.
``thumb_format`` is the ARM7TDMI Thumb format number (1-19), kept for
formatting only.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum


class Mode(Enum):
    ARM = "arm"
    THUMB = "thumb"


class Cond(IntEnum):
    EQ = 0x0
    NE = 0x1
    CS = 0x2
    CC = 0x3
    MI = 0x4
    PL = 0x5
    VS = 0x6
    VC = 0x7
    HI = 0x8
    LS = 0x9
    GE = 0xA
    LT = 0xB
    GT = 0xC
    LE = 0xD
    AL = 0xE


class Op(Enum):
    AND = "and"
    EOR = "eor"
    SUB = "sub"
    RSB = "rsb"
    ADD = "add"
    ADC = "adc"
    SBC = "sbc"
    RSC = "rsc"
    TST = "tst"
    TEQ = "teq"
    CMP = "cmp"
    CMN = "cmn"
    ORR = "orr"
    MOV = "mov"
    BIC = "bic"
    MVN = "mvn"
    MUL = "mul"
    MLA = "mla"
    UMULL = "umull"
    UMLAL = "umlal"
    SMULL = "smull"
    SMLAL = "smlal"
    LDR = "ldr"
    STR = "str"
    LDRB = "ldrb"
    STRB = "strb"
    LDRH = "ldrh"
    STRH = "strh"
    LDRSB = "ldrsb"
    LDRSH = "ldrsh"
    LDM = "ldm"
    STM = "stm"
    SWP = "swp"
    SWPB = "swpb"
    B = "b"
    BL = "bl"
    BX = "bx"
    SWI = "swi"
    MRS = "mrs"
    MSR = "msr"
    BL_HI = "bl_hi"
    BL_LO = "bl_lo"
    UNDEFINED = "undefined"


# Index == the 4-bit ARM data-processing opcode field.
DATA_PROCESSING_OPS = (
    Op.AND, Op.EOR, Op.SUB, Op.RSB, Op.ADD, Op.ADC, Op.SBC, Op.RSC,
    Op.TST, Op.TEQ, Op.CMP, Op.CMN, Op.ORR, Op.MOV, Op.BIC, Op.MVN,
)
COMPARE_OPS = frozenset({Op.TST, Op.TEQ, Op.CMP, Op.CMN})
MOVE_OPS = frozenset({Op.MOV, Op.MVN})


class ShiftKind(Enum):
    LSL = "lsl"
    LSR = "lsr"
    ASR = "asr"
    ROR = "ror"
    RRX = "rrx"


# Index == the 2-bit shift-type field.
SHIFT_FIELD_KINDS = (ShiftKind.LSL, ShiftKind.LSR, ShiftKind.ASR, ShiftKind.ROR)


@dataclass(frozen=True)
class Shift:
    kind: ShiftKind
    amount: int = 0  # immediate amount, normalised (LSR/ASR #0 encode #32)
    reg: int | None = None  # register holding the amount, for register shifts

    @classmethod
    def from_imm_field(cls, kind_bits: int, amount: int) -> "Shift | None":
        """Decode an immediate shift field; ``None`` means no shift (LSL #0)."""
        kind = SHIFT_FIELD_KINDS[kind_bits]
        if amount == 0:
            if kind is ShiftKind.LSL:
                return None
            if kind is ShiftKind.ROR:
                return cls(ShiftKind.RRX)
            return cls(kind, 32)
        return cls(kind, amount)


@dataclass(frozen=True)
class Instruction:
    addr: int
    mode: Mode
    size: int
    raw: int
    op: Op
    cond: Cond = Cond.AL
    s: bool = False
    rd: int | None = None
    rn: int | None = None
    rm: int | None = None
    rs: int | None = None
    rd_hi: int | None = None
    imm: int | None = None
    imm_rot: int = 0
    shift: Shift | None = None
    pre: bool = True
    up: bool = True
    writeback: bool = False
    user: bool = False
    reglist: tuple[int, ...] = ()
    spsr: bool = False
    psr_mask: int = 0
    target: int | None = None
    thumb_format: int | None = None
```

- [ ] **Step 4: Write the ARM decoder**

Create `src/gbaport/isa/arm.py`:

```python
"""ARMv4T (ARM7TDMI) ARM-state decoder.

Anything outside ARMv4T decodes to ``Op.UNDEFINED``: coprocessor instructions
(the GBA has no coprocessor), ARMv5+ encodings (BLX, CLZ, LDRD/STRD, QADD, ...),
ARMv6 media instructions and the NV condition.
"""

from gbaport.isa.bits import bit, field, ror32, sign_extend
from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    MOVE_OPS,
    SHIFT_FIELD_KINDS,
    Cond,
    Instruction,
    Mode,
    Op,
    Shift,
)

_LONG_MULTIPLY = ((Op.UMULL, Op.UMLAL), (Op.SMULL, Op.SMLAL))  # [signed][accumulate]
_SINGLE_OPS = ((Op.STR, Op.STRB), (Op.LDR, Op.LDRB))  # [load][byte]
_HALFWORD_OPS = {
    (False, 1): Op.STRH,
    (True, 1): Op.LDRH,
    (True, 2): Op.LDRSB,
    (True, 3): Op.LDRSH,
}  # (load, SH field)


def decode_arm(word: int, addr: int) -> Instruction:
    """Decode the 32-bit ARM instruction ``word`` located at bus address ``addr``."""
    if word >> 28 == 0xF:
        return Instruction(addr=addr, mode=Mode.ARM, size=4, raw=word, op=Op.UNDEFINED)
    base = {"addr": addr, "mode": Mode.ARM, "size": 4, "raw": word, "cond": Cond(word >> 28)}
    group = field(word, 27, 25)
    if group == 0b000:
        return _group0(word, base)
    if group == 0b001:
        return _group1(word, base)
    if group in (0b010, 0b011):
        return _single_transfer(word, base)
    if group == 0b100:
        return _block_transfer(word, base)
    if group == 0b101:
        offset = sign_extend(word & 0xFFFFFF, 24) << 2
        return Instruction(
            **base, op=Op.BL if bit(word, 24) else Op.B, target=(addr + 8 + offset) & 0xFFFFFFFF
        )
    if group == 0b111 and bit(word, 24):
        return Instruction(**base, op=Op.SWI, imm=word & 0xFFFFFF)
    return Instruction(**base, op=Op.UNDEFINED)  # coprocessor space


def _group0(word: int, base: dict) -> Instruction:
    if (word & 0x0FFFFFF0) == 0x012FFF10:
        return Instruction(**base, op=Op.BX, rm=word & 0xF)
    if (word & 0x0FC000F0) == 0x00000090:
        accumulate = bit(word, 21)
        return Instruction(
            **base,
            op=Op.MLA if accumulate else Op.MUL,
            s=bit(word, 20),
            rd=field(word, 19, 16),
            rn=field(word, 15, 12) if accumulate else None,
            rs=field(word, 11, 8),
            rm=word & 0xF,
        )
    if (word & 0x0F8000F0) == 0x00800090:
        return Instruction(
            **base,
            op=_LONG_MULTIPLY[bit(word, 22)][bit(word, 21)],
            s=bit(word, 20),
            rd_hi=field(word, 19, 16),
            rd=field(word, 15, 12),
            rs=field(word, 11, 8),
            rm=word & 0xF,
        )
    if (word & 0x0FB00FF0) == 0x01000090:
        return Instruction(
            **base,
            op=Op.SWPB if bit(word, 22) else Op.SWP,
            rn=field(word, 19, 16),
            rd=field(word, 15, 12),
            rm=word & 0xF,
        )
    if (word & 0x90) == 0x90:
        if (word & 0x60) == 0:
            return Instruction(**base, op=Op.UNDEFINED)  # unallocated multiply space
        return _halfword_transfer(word, base)
    if (word & 0x0FBF0FFF) == 0x010F0000:
        return Instruction(**base, op=Op.MRS, rd=field(word, 15, 12), spsr=bit(word, 22))
    if (word & 0x0FB0FFF0) == 0x0120F000:
        return Instruction(
            **base, op=Op.MSR, spsr=bit(word, 22), psr_mask=field(word, 19, 16), rm=word & 0xF
        )
    if (word & 0x01900000) == 0x01000000:
        return Instruction(**base, op=Op.UNDEFINED)  # ARMv5+ miscellaneous space
    op = DATA_PROCESSING_OPS[field(word, 24, 21)]
    if bit(word, 4):
        shift = Shift(SHIFT_FIELD_KINDS[field(word, 6, 5)], reg=field(word, 11, 8))
    else:
        shift = Shift.from_imm_field(field(word, 6, 5), field(word, 11, 7))
    return Instruction(**base, op=op, rm=word & 0xF, shift=shift, **_dp_registers(word, op))


def _group1(word: int, base: dict) -> Instruction:
    rot = field(word, 11, 8)
    value = ror32(word & 0xFF, rot * 2)
    if (word & 0x0FB0F000) == 0x0320F000:
        return Instruction(
            **base, op=Op.MSR, spsr=bit(word, 22), psr_mask=field(word, 19, 16),
            imm=value, imm_rot=rot,
        )
    if (word & 0x01900000) == 0x01000000:
        return Instruction(**base, op=Op.UNDEFINED)  # MOVW/MOVT (ARMv6T2)
    op = DATA_PROCESSING_OPS[field(word, 24, 21)]
    return Instruction(**base, op=op, imm=value, imm_rot=rot, **_dp_registers(word, op))


def _dp_registers(word: int, op: Op) -> dict:
    return {
        "s": bit(word, 20),
        "rd": None if op in COMPARE_OPS else field(word, 15, 12),
        "rn": None if op in MOVE_OPS else field(word, 19, 16),
    }


def _transfer_fields(word: int) -> dict:
    pre = bit(word, 24)
    return {
        "rd": field(word, 15, 12),
        "rn": field(word, 19, 16),
        "pre": pre,
        "up": bit(word, 23),
        "writeback": bit(word, 21) or not pre,
    }


def _literal_target(addr: int, fields: dict) -> int | None:
    """Absolute address of a PC-relative, pre-indexed access without writeback."""
    if fields["rn"] != 15 or not fields["pre"] or fields["writeback"]:
        return None
    offset = fields["imm"] if fields["up"] else -fields["imm"]
    return (addr + 8 + offset) & 0xFFFFFFFF


def _single_transfer(word: int, base: dict) -> Instruction:
    register_offset = bit(word, 25)
    if register_offset and bit(word, 4):
        return Instruction(**base, op=Op.UNDEFINED)  # ARMv6 media space
    fields = _transfer_fields(word)
    fields["user"] = not bit(word, 24) and bit(word, 21)
    op = _SINGLE_OPS[bit(word, 20)][bit(word, 22)]
    if register_offset:
        fields["rm"] = word & 0xF
        fields["shift"] = Shift.from_imm_field(field(word, 6, 5), field(word, 11, 7))
    else:
        fields["imm"] = word & 0xFFF
        fields["target"] = _literal_target(base["addr"], fields)
    return Instruction(**base, op=op, **fields)


def _halfword_transfer(word: int, base: dict) -> Instruction:
    op = _HALFWORD_OPS.get((bit(word, 20), field(word, 6, 5)))
    post_writeback = not bit(word, 24) and bit(word, 21)
    immediate = bit(word, 22)
    if op is None or post_writeback or (not immediate and field(word, 11, 8)):
        # LDRD/STRD (ARMv5TE), unpredictable post-index writeback, or non-zero SBZ bits
        return Instruction(**base, op=Op.UNDEFINED)
    fields = _transfer_fields(word)
    if immediate:
        fields["imm"] = (field(word, 11, 8) << 4) | (word & 0xF)
        fields["target"] = _literal_target(base["addr"], fields)
    else:
        fields["rm"] = word & 0xF
    return Instruction(**base, op=op, **fields)


def _block_transfer(word: int, base: dict) -> Instruction:
    return Instruction(
        **base,
        op=Op.LDM if bit(word, 20) else Op.STM,
        rn=field(word, 19, 16),
        pre=bit(word, 24),
        up=bit(word, 23),
        user=bit(word, 22),
        writeback=bit(word, 21),
        reglist=tuple(r for r in range(16) if bit(word, r)),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/isa -v && uv run ruff check src tests`
Expected: all `test_bits.py` and `test_arm.py` tests pass (4 + 31 + 10 + 1 = 46); ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/isa tests/isa/test_bits.py tests/isa/test_arm.py
git commit -m "feat: instruction model and ARMv4T ARM decoder"
```

---

### Task 5: Thumb decoder

**Files:**
- Create: `src/gbaport/isa/thumb.py`
- Test: `tests/isa/test_thumb.py`

**Interfaces:**
- Consumes: `Instruction`, `Mode`, `Cond`, `Op`, `Shift`, `ShiftKind` from `gbaport.isa.model`; `sign_extend` from `gbaport.isa.bits` (Task 4).
- Produces: `gbaport.isa.thumb.decode_thumb(halfword: int, addr: int, next_halfword: int | None = None) -> Instruction`. A BL prefix followed by a BL suffix decodes as one `Op.BL` with `size=4` and `raw = halfword | next_halfword << 16`; an unpaired half decodes as `Op.BL_HI`/`Op.BL_LO` with `size=2`.

- [ ] **Step 1: Write the failing tests**

Create `tests/isa/test_thumb.py` (every halfword below was produced by Keystone from the text in the first column):

```python
import pytest

from gbaport.isa.model import Cond, Mode, Op, Shift, ShiftKind
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000

# (text, halfword, next halfword, address, expected fields)
CASES = [
    ("lsls r0, r1, #2", 0x0088, None, BASE,
     dict(thumb_format=1, op=Op.MOV, s=True, rd=0, rm=1, shift=Shift(ShiftKind.LSL, 2))),
    ("lsrs r0, r1, #32", 0x0808, None, BASE, dict(op=Op.MOV, shift=Shift(ShiftKind.LSR, 32))),
    ("lsls r0, r1, #0", 0x0008, None, BASE, dict(op=Op.MOV, rm=1, shift=None)),
    ("adds r0, r1, r2", 0x1888, None, BASE,
     dict(thumb_format=2, op=Op.ADD, s=True, rd=0, rn=1, rm=2, imm=None)),
    ("subs r0, r1, #3", 0x1EC8, None, BASE, dict(op=Op.SUB, rd=0, rn=1, imm=3, rm=None)),
    ("movs r0, #5", 0x2005, None, BASE,
     dict(thumb_format=3, op=Op.MOV, s=True, rd=0, rn=None, imm=5)),
    ("cmp r0, #5", 0x2805, None, BASE, dict(op=Op.CMP, s=True, rd=None, rn=0, imm=5)),
    ("adds r0, #200", 0x30C8, None, BASE, dict(op=Op.ADD, rd=0, rn=0, imm=200)),
    ("ands r0, r1", 0x4008, None, BASE,
     dict(thumb_format=4, op=Op.AND, s=True, rd=0, rn=0, rm=1)),
    ("rors r0, r1", 0x41C8, None, BASE,
     dict(op=Op.MOV, s=True, rd=0, rm=0, shift=Shift(ShiftKind.ROR, reg=1))),
    ("negs r0, r1", 0x4248, None, BASE, dict(op=Op.RSB, s=True, rd=0, rn=1, imm=0)),
    ("muls r0, r1, r0", 0x4348, None, BASE, dict(op=Op.MUL, s=True, rd=0, rm=1, rs=0)),
    ("tst r0, r1", 0x4208, None, BASE, dict(op=Op.TST, s=True, rd=None, rn=0, rm=1)),
    ("add r0, r8", 0x4440, None, BASE,
     dict(thumb_format=5, op=Op.ADD, s=False, rd=0, rn=0, rm=8)),
    ("mov r8, r0", 0x4680, None, BASE, dict(op=Op.MOV, s=False, rd=8, rm=0)),
    ("cmp r0, r8", 0x4540, None, BASE, dict(op=Op.CMP, s=True, rn=0, rm=8)),
    ("mov pc, lr", 0x46F7, None, BASE, dict(op=Op.MOV, rd=15, rm=14)),
    ("bx r0", 0x4700, None, BASE, dict(op=Op.BX, rm=0)),
    ("ldr r0, [pc, #8] @ 0x08000002", 0x4802, None, BASE + 2,
     dict(thumb_format=6, op=Op.LDR, rd=0, rn=15, imm=8, target=0x0800000C)),
    ("str r0, [r1, r2]", 0x5088, None, BASE,
     dict(thumb_format=7, op=Op.STR, rd=0, rn=1, rm=2)),
    ("ldrsb r0, [r1, r2]", 0x5688, None, BASE,
     dict(thumb_format=8, op=Op.LDRSB, rd=0, rn=1, rm=2)),
    ("ldrb r0, [r1, #3]", 0x78C8, None, BASE,
     dict(thumb_format=9, op=Op.LDRB, rd=0, rn=1, imm=3)),
    ("ldr r0, [r1, #124]", 0x6FC8, None, BASE, dict(op=Op.LDR, imm=124)),
    ("ldrh r0, [r1, #2]", 0x8848, None, BASE,
     dict(thumb_format=10, op=Op.LDRH, rd=0, rn=1, imm=2)),
    ("str r0, [sp, #4]", 0x9001, None, BASE,
     dict(thumb_format=11, op=Op.STR, rd=0, rn=13, imm=4)),
    ("add r0, sp, #8", 0xA802, None, BASE,
     dict(thumb_format=12, op=Op.ADD, rd=0, rn=13, imm=8, target=None)),
    ("adr r0, #8 @ 0x08000002", 0xA002, None, BASE + 2,
     dict(op=Op.ADD, rd=0, rn=15, imm=8, target=0x0800000C)),
    ("sub sp, #8", 0xB082, None, BASE,
     dict(thumb_format=13, op=Op.SUB, rd=13, rn=13, imm=8)),
    ("push {r4, lr}", 0xB510, None, BASE,
     dict(thumb_format=14, op=Op.STM, rn=13, pre=True, up=False, writeback=True,
          reglist=(4, 14))),
    ("pop {r4, pc}", 0xBD10, None, BASE,
     dict(op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=(4, 15))),
    ("ldmia r0!, {r1, r2}", 0xC806, None, BASE,
     dict(thumb_format=15, op=Op.LDM, rn=0, pre=False, writeback=True, reglist=(1, 2))),
    ("ldm r0, {r0, r1}", 0xC803, None, BASE, dict(op=Op.LDM, writeback=False, reglist=(0, 1))),
    ("beq #0x08000010", 0xD006, None, BASE,
     dict(thumb_format=16, op=Op.B, cond=Cond.EQ, target=0x08000010)),
    ("bne #0x07ffffe0", 0xD1EE, None, BASE, dict(op=Op.B, cond=Cond.NE, target=0x07FFFFE0)),
    ("svc #5", 0xDF05, None, BASE, dict(thumb_format=17, op=Op.SWI, imm=5)),
    ("b #0x08000020", 0xE00E, None, BASE, dict(thumb_format=18, op=Op.B, target=0x08000020)),
    ("bl #0x08000100", 0xF000, 0xF87E, BASE,
     dict(thumb_format=19, op=Op.BL, size=4, raw=0xF87EF000, target=0x08000100)),
    ("bl #0x07ff0000", 0xF7EF, 0xFFFE, BASE, dict(op=Op.BL, size=4, target=0x07FF0000)),
    ("lone BL prefix", 0xF000, None, BASE, dict(op=Op.BL_HI, size=2, imm=0)),
    ("BL prefix before non-suffix", 0xF000, 0x2005, BASE, dict(op=Op.BL_HI, size=2)),
    ("lone BL suffix", 0xF87E, None, BASE, dict(op=Op.BL_LO, size=2, imm=0xFC)),
]


@pytest.mark.parametrize("text,hw,nxt,addr,expected", CASES, ids=[case[0] for case in CASES])
def test_decode(text, hw, nxt, addr, expected):
    ins = decode_thumb(hw, addr, nxt)
    assert {key: getattr(ins, key) for key in expected} == expected
    assert ins.mode is Mode.THUMB and ins.addr == addr


UNDEFINED = [
    ("cond 1110 branch", 0xDE00),
    ("BLX suffix (ARMv5)", 0xE800),
    ("sxth (ARMv6)", 0xB200),
    ("bkpt (ARMv5)", 0xBE00),
    ("blx reg (ARMv5)", 0x4780),
]


@pytest.mark.parametrize("name,hw", UNDEFINED, ids=[case[0] for case in UNDEFINED])
def test_non_armv4t_encodings_are_undefined(name, hw):
    assert decode_thumb(hw, BASE).op is Op.UNDEFINED


def test_decoder_is_total_over_every_halfword():
    for hw in range(0x10000):
        ins = decode_thumb(hw, BASE)
        assert ins.size == 2 and ins.raw == hw and ins.mode is Mode.THUMB
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/isa/test_thumb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.isa.thumb'`

- [ ] **Step 3: Write the Thumb decoder**

Create `src/gbaport/isa/thumb.py`:

```python
"""ARMv4T Thumb-state decoder (ARM7TDMI formats 1-19).

Each Thumb instruction decodes into the equivalent ARM operation so later stages
see one semantic model; ``thumb_format`` keeps the original format number.
PC-relative forms (format 6 literal loads, format 12 ADR) get their absolute
address in ``target`` because Thumb word-aligns the PC for them.
"""

from gbaport.isa.bits import sign_extend
from gbaport.isa.model import Cond, Instruction, Mode, Op, Shift, ShiftKind

_F3_OPS = (Op.MOV, Op.CMP, Op.ADD, Op.SUB)
_F4_BINARY = {0: Op.AND, 1: Op.EOR, 5: Op.ADC, 6: Op.SBC, 12: Op.ORR, 14: Op.BIC}
_F4_SHIFTS = {2: ShiftKind.LSL, 3: ShiftKind.LSR, 4: ShiftKind.ASR, 7: ShiftKind.ROR}
_F4_COMPARE = {8: Op.TST, 10: Op.CMP, 11: Op.CMN}
_F7_OPS = (Op.STR, Op.STRB, Op.LDR, Op.LDRB)  # index: L << 1 | B
_F8_OPS = (Op.STRH, Op.LDRSB, Op.LDRH, Op.LDRSH)  # index: H << 1 | S


def decode_thumb(halfword: int, addr: int, next_halfword: int | None = None) -> Instruction:
    """Decode the Thumb halfword at ``addr``.

    ``next_halfword`` lets a BL prefix pair with its suffix into one 4-byte BL.
    """
    hw = halfword
    top = hw >> 13
    if top == 0b000:
        return _format2(hw, addr) if ((hw >> 11) & 3) == 3 else _format1(hw, addr)
    if top == 0b001:
        return _format3(hw, addr)
    if top == 0b010:
        if (hw >> 10) == 0b010000:
            return _format4(hw, addr)
        if (hw >> 10) == 0b010001:
            return _format5(hw, addr)
        if (hw >> 11) == 0b01001:
            return _format6(hw, addr)
        return _format8(hw, addr) if hw & 0x0200 else _format7(hw, addr)
    if top == 0b011:
        return _format9(hw, addr)
    if top == 0b100:
        return _format11(hw, addr) if hw & 0x1000 else _format10(hw, addr)
    if top == 0b101:
        if not hw & 0x1000:
            return _format12(hw, addr)
        if (hw & 0xFF00) == 0xB000:
            return _format13(hw, addr)
        if (hw & 0xF600) == 0xB400:
            return _format14(hw, addr)
        return _undefined(hw, addr)
    if top == 0b110:
        return _format16_17(hw, addr) if hw & 0x1000 else _format15(hw, addr)
    return _format18_19(hw, addr, next_halfword)


def _base(hw: int, addr: int, fmt: int) -> dict:
    return {"addr": addr, "mode": Mode.THUMB, "size": 2, "raw": hw, "thumb_format": fmt}


def _undefined(hw: int, addr: int) -> Instruction:
    return Instruction(addr=addr, mode=Mode.THUMB, size=2, raw=hw, op=Op.UNDEFINED)


def _lo(hw: int, shift: int) -> int:
    return (hw >> shift) & 7


def _aligned_pc_target(addr: int, imm: int) -> int:
    return (((addr + 4) & ~3) + imm) & 0xFFFFFFFF


def _format1(hw: int, addr: int) -> Instruction:  # LSL/LSR/ASR Rd, Rs, #offset5
    return Instruction(
        **_base(hw, addr, 1), op=Op.MOV, s=True, rd=_lo(hw, 0), rm=_lo(hw, 3),
        shift=Shift.from_imm_field((hw >> 11) & 3, (hw >> 6) & 0x1F),
    )


def _format2(hw: int, addr: int) -> Instruction:  # ADD/SUB Rd, Rs, Rn|#offset3
    operand = {"imm": _lo(hw, 6)} if hw & 0x0400 else {"rm": _lo(hw, 6)}
    return Instruction(
        **_base(hw, addr, 2), op=Op.SUB if hw & 0x0200 else Op.ADD, s=True,
        rd=_lo(hw, 0), rn=_lo(hw, 3), **operand,
    )


def _format3(hw: int, addr: int) -> Instruction:  # MOV/CMP/ADD/SUB Rd, #offset8
    op = _F3_OPS[(hw >> 11) & 3]
    reg = _lo(hw, 8)
    if op is Op.MOV:
        regs = {"rd": reg}
    elif op is Op.CMP:
        regs = {"rn": reg}
    else:
        regs = {"rd": reg, "rn": reg}
    return Instruction(**_base(hw, addr, 3), op=op, s=True, imm=hw & 0xFF, **regs)


def _format4(hw: int, addr: int) -> Instruction:  # ALU operations
    alu, rs, rd = (hw >> 6) & 0xF, _lo(hw, 3), _lo(hw, 0)
    base = _base(hw, addr, 4)
    if alu in _F4_BINARY:
        return Instruction(**base, op=_F4_BINARY[alu], s=True, rd=rd, rn=rd, rm=rs)
    if alu in _F4_SHIFTS:
        return Instruction(
            **base, op=Op.MOV, s=True, rd=rd, rm=rd, shift=Shift(_F4_SHIFTS[alu], reg=rs)
        )
    if alu in _F4_COMPARE:
        return Instruction(**base, op=_F4_COMPARE[alu], s=True, rn=rd, rm=rs)
    if alu == 9:  # NEG Rd, Rs == RSBS Rd, Rs, #0
        return Instruction(**base, op=Op.RSB, s=True, rd=rd, rn=rs, imm=0)
    if alu == 13:  # MUL Rd, Rs == MULS Rd, Rs, Rd
        return Instruction(**base, op=Op.MUL, s=True, rd=rd, rm=rs, rs=rd)
    return Instruction(**base, op=Op.MVN, s=True, rd=rd, rm=rs)  # alu == 15


def _format5(hw: int, addr: int) -> Instruction:  # hi-register ops / BX
    op_bits = (hw >> 8) & 3
    rd = _lo(hw, 0) | ((hw >> 4) & 8)  # H1 is bit 7
    rm = _lo(hw, 3) | ((hw >> 3) & 8)  # H2 is bit 6
    base = _base(hw, addr, 5)
    if op_bits == 0:
        return Instruction(**base, op=Op.ADD, rd=rd, rn=rd, rm=rm)
    if op_bits == 1:
        return Instruction(**base, op=Op.CMP, s=True, rn=rd, rm=rm)
    if op_bits == 2:
        return Instruction(**base, op=Op.MOV, rd=rd, rm=rm)
    if hw & 0x0080:  # H1 set on BX is BLX (ARMv5)
        return _undefined(hw, addr)
    return Instruction(**base, op=Op.BX, rm=rm)


def _format6(hw: int, addr: int) -> Instruction:  # LDR Rd, [PC, #imm]
    imm = (hw & 0xFF) * 4
    return Instruction(
        **_base(hw, addr, 6), op=Op.LDR, rd=_lo(hw, 8), rn=15, imm=imm,
        target=_aligned_pc_target(addr, imm),
    )


def _format7(hw: int, addr: int) -> Instruction:  # LDR/STR{B} Rd, [Rb, Ro]
    return Instruction(
        **_base(hw, addr, 7), op=_F7_OPS[(hw >> 10) & 3],
        rd=_lo(hw, 0), rn=_lo(hw, 3), rm=_lo(hw, 6),
    )


def _format8(hw: int, addr: int) -> Instruction:  # STRH/LDRH/LDSB/LDSH Rd, [Rb, Ro]
    return Instruction(
        **_base(hw, addr, 8), op=_F8_OPS[(hw >> 10) & 3],
        rd=_lo(hw, 0), rn=_lo(hw, 3), rm=_lo(hw, 6),
    )


def _format9(hw: int, addr: int) -> Instruction:  # LDR/STR{B} Rd, [Rb, #offset5]
    byte, load = bool(hw & 0x1000), bool(hw & 0x0800)
    offset = (hw >> 6) & 0x1F
    return Instruction(
        **_base(hw, addr, 9), op=((Op.STR, Op.LDR), (Op.STRB, Op.LDRB))[byte][load],
        rd=_lo(hw, 0), rn=_lo(hw, 3), imm=offset if byte else offset * 4,
    )


def _format10(hw: int, addr: int) -> Instruction:  # LDRH/STRH Rd, [Rb, #offset5]
    return Instruction(
        **_base(hw, addr, 10), op=Op.LDRH if hw & 0x0800 else Op.STRH,
        rd=_lo(hw, 0), rn=_lo(hw, 3), imm=((hw >> 6) & 0x1F) * 2,
    )


def _format11(hw: int, addr: int) -> Instruction:  # LDR/STR Rd, [SP, #imm]
    return Instruction(
        **_base(hw, addr, 11), op=Op.LDR if hw & 0x0800 else Op.STR,
        rd=_lo(hw, 8), rn=13, imm=(hw & 0xFF) * 4,
    )


def _format12(hw: int, addr: int) -> Instruction:  # ADD Rd, SP|PC, #imm
    imm = (hw & 0xFF) * 4
    base = _base(hw, addr, 12)
    if hw & 0x0800:
        return Instruction(**base, op=Op.ADD, rd=_lo(hw, 8), rn=13, imm=imm)
    return Instruction(
        **base, op=Op.ADD, rd=_lo(hw, 8), rn=15, imm=imm, target=_aligned_pc_target(addr, imm)
    )


def _format13(hw: int, addr: int) -> Instruction:  # ADD/SUB SP, #imm
    return Instruction(
        **_base(hw, addr, 13), op=Op.SUB if hw & 0x80 else Op.ADD,
        rd=13, rn=13, imm=(hw & 0x7F) * 4,
    )


def _format14(hw: int, addr: int) -> Instruction:  # PUSH/POP
    regs = [r for r in range(8) if hw & (1 << r)]
    base = _base(hw, addr, 14)
    if hw & 0x0800:
        if hw & 0x0100:
            regs.append(15)
        return Instruction(
            **base, op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=tuple(regs)
        )
    if hw & 0x0100:
        regs.append(14)
    return Instruction(
        **base, op=Op.STM, rn=13, pre=True, up=False, writeback=True, reglist=tuple(regs)
    )


def _format15(hw: int, addr: int) -> Instruction:  # LDMIA/STMIA Rb!, {Rlist}
    rb = _lo(hw, 8)
    regs = tuple(r for r in range(8) if hw & (1 << r))
    load = bool(hw & 0x0800)
    # A load that includes the base overwrites the written-back value, so no writeback.
    return Instruction(
        **_base(hw, addr, 15), op=Op.LDM if load else Op.STM, rn=rb, pre=False, up=True,
        writeback=not (load and rb in regs), reglist=regs,
    )


def _format16_17(hw: int, addr: int) -> Instruction:  # B{cond} / SWI
    cond = (hw >> 8) & 0xF
    if cond == 0xF:
        return Instruction(**_base(hw, addr, 17), op=Op.SWI, imm=hw & 0xFF)
    if cond == 0xE:
        return _undefined(hw, addr)
    offset = sign_extend(hw & 0xFF, 8) * 2
    return Instruction(
        **_base(hw, addr, 16), op=Op.B, cond=Cond(cond), target=(addr + 4 + offset) & 0xFFFFFFFF
    )


def _format18_19(hw: int, addr: int, next_hw: int | None) -> Instruction:  # B / BL
    kind = (hw >> 11) & 3
    if kind == 0b00:
        offset = sign_extend(hw & 0x7FF, 11) * 2
        return Instruction(
            **_base(hw, addr, 18), op=Op.B, target=(addr + 4 + offset) & 0xFFFFFFFF
        )
    if kind == 0b01:
        return _undefined(hw, addr)  # BLX suffix (ARMv5)
    if kind == 0b10:
        high = sign_extend(hw & 0x7FF, 11) << 12
        if next_hw is not None and (next_hw & 0xF800) == 0xF800:
            target = (addr + 4 + high + ((next_hw & 0x7FF) << 1)) & 0xFFFFFFFF
            return Instruction(
                addr=addr, mode=Mode.THUMB, size=4, raw=hw | (next_hw << 16), op=Op.BL,
                target=target, thumb_format=19,
            )
        return Instruction(**_base(hw, addr, 19), op=Op.BL_HI, imm=high)
    return Instruction(**_base(hw, addr, 19), op=Op.BL_LO, imm=(hw & 0x7FF) << 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/isa/test_thumb.py -v && uv run ruff check src tests`
Expected: 41 + 5 + 1 = 47 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/isa/thumb.py tests/isa/test_thumb.py
git commit -m "feat: ARMv4T Thumb decoder"
```

---

### Task 6: Formatter with Keystone round-trip verification

**Files:**
- Create: `src/gbaport/isa/fmt.py`, `tests/ksasm.py`
- Test: `tests/isa/test_fmt.py`, `tests/isa/test_roundtrip.py`

**Interfaces:**
- Consumes: `decode_arm` (Task 4), `decode_thumb` (Task 5), model types (Task 4).
- Produces: `gbaport.isa.fmt.format_instruction(ins: Instruction) -> str` (UAL text; undefined words print as `.word 0x…` / `.hword 0x…`; unpaired Thumb BL halves print as `.hword 0x…  @ bl_hi …`). `tests/ksasm.py`: `assemble(text: str, *, thumb: bool = False, addr: int = 0x08000000) -> bytes`.

- [ ] **Step 1: Write the Keystone helper and the failing tests**

Create `tests/ksasm.py`:

```python
"""Test-only assembler (Keystone). Never imported by gbaport itself."""

import keystone

_ARM = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
_THUMB = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_THUMB)


def assemble(text: str, *, thumb: bool = False, addr: int = 0x08000000) -> bytes:
    """Assemble UAL ``text`` (statements separated by newlines) located at ``addr``."""
    encoding, _ = (_THUMB if thumb else _ARM).asm(text, addr)
    if encoding is None:
        raise ValueError(f"Keystone produced no bytes for {text!r}")
    return bytes(encoding)
```

Create `tests/isa/test_fmt.py`:

```python
import random

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000


def test_arm_text():
    assert format_instruction(decode_arm(0xE0810182, BASE)) == "add r0, r1, r2, lsl #3"
    assert format_instruction(decode_arm(0x00910002, BASE)) == "addseq r0, r1, r2"
    assert format_instruction(decode_arm(0xE8BD80F0, BASE)) == "ldmia sp!, {r4, r5, r6, r7, pc}"
    assert format_instruction(decode_arm(0xEB00003E, BASE)) == "bl #0x8000100"
    assert format_instruction(decode_arm(0xE5310004, BASE)) == "ldr r0, [r1, #-4]!"


def test_thumb_text():
    assert format_instruction(decode_thumb(0x0088, BASE)) == "lsls r0, r1, #2"
    assert format_instruction(decode_thumb(0x4248, BASE)) == "rsbs r0, r1, #0"
    assert format_instruction(decode_thumb(0xB510, BASE)) == "push {r4, lr}"
    assert format_instruction(decode_thumb(0xF000, BASE, 0xF87E)) == "bl #0x8000100"


def test_undefined_prints_as_data():
    assert format_instruction(decode_arm(0xF0000000, BASE)) == ".word 0xf0000000"
    assert format_instruction(decode_thumb(0xDE00, BASE)) == ".hword 0xde00"


def test_lone_bl_half_prints_as_annotated_data():
    assert format_instruction(decode_thumb(0xF000, BASE)).startswith(".hword 0xf000  @ bl_hi")


def test_every_thumb_halfword_formats():
    for hw in range(0x10000):
        assert format_instruction(decode_thumb(hw, BASE))


def test_random_arm_words_format():
    rng = random.Random(0x6BA)
    for _ in range(100_000):
        assert format_instruction(decode_arm(rng.getrandbits(32), BASE))
```

Create `tests/isa/test_roundtrip.py`:

```python
"""Assemble -> decode -> format -> re-assemble must reproduce the original bytes.

Every corpus entry is canonical assembler output, so a mismatch means the
decoder or the formatter lost information.
"""

import pytest
from ksasm import assemble

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Op
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000

ARM_CORPUS = [
    "add r0, r1, r2, lsl #3", "addseq r0, r1, r2", "mov r0, #0xff000000", "mov r0, r1, lsl r2",
    "movs r0, r1, lsr #32", "mov r0, r1, asr #32", "mov r0, r1, rrx", "tst r0, r1, lsl #3",
    "teq r0, #1", "cmp r0, r1, rrx", "mvns r0, #0", "rsc r0, r1, r2, ror r3", "movs pc, lr",
    "mulseq r0, r1, r2", "mla r0, r1, r2, r3", "umull r0, r1, r2, r3", "smlals r0, r1, r2, r3",
    "umullseq r0, r1, r2, r3", "swp r0, r1, [r2]", "swpbeq r0, r1, [r2]",
    "ldr r0, [r1, r2, lsl #2]", "str r0, [r1], -r2, asr #3", "ldr r0, [r1, -r2, ror #4]!",
    "ldr r0, [r1], r2", "ldr r0, [r1, #-4]!", "ldr r0, [r1, #-0]", "ldrbteq r0, [r1], #4",
    "ldrt r0, [r1], -r2", "ldrbeq r0, [r1]", "ldr r0, [pc, #8]", "str r0, [r1, #0]",
    "ldrh r0, [r1, #2]", "ldrheq r0, [r1]", "ldrsbne r0, [r1]", "ldrsb r0, [r1, -r2]!",
    "ldrh r0, [r1, -r2]!", "ldrsh r0, [r1], #-4", "strh r0, [r1], #-6", "ldrsh r0, [r1]",
    "ldmfd sp!, {r4-r7, pc}", "stmdb sp!, {r4, lr}", "ldmib r0, {r1}", "stmda r0!, {r1}",
    "ldmda r0, {r1, pc}^", "ldm r0, {r1, r2}^", "ldmiaeq r0, {r1}",
    "b #0x08000100", "beq #0x07fffff8", "blne #0x08100000", "bl #0x08000100", "bx lr",
    "bxeq lr", "svc #0x50000", "svceq #0x123456",
    "mrs r0, cpsr", "mrsne r0, cpsr", "mrs r0, spsr", "msr cpsr_fc, r0", "msr cpsr_fsxc, r0",
    "msr cpsr_c, r0", "msr spsr_fc, r0", "msr cpsr_f, #0xf0000000", "msr spsr_fsxc, #0x1f",
]

THUMB_CORPUS = [
    "adds r0, r1, r2", "subs r0, r1, #3", "adds r0, r1, #0", "lsls r0, r1, #2", "lsls r0, r1, #0",
    "lsrs r0, r1, #32", "asrs r0, r1, #32", "movs r0, #5", "cmp r0, #5", "adds r0, #200",
    "ands r0, r1", "eors r0, r1", "adcs r0, r1", "sbcs r0, r1", "rors r0, r1", "lsls r0, r1",
    "tst r0, r1", "negs r0, r1", "cmn r0, r1", "orrs r0, r1", "muls r0, r1, r0", "bics r0, r1",
    "mvns r0, r1", "add r0, r8", "mov r8, r0", "cmp r0, r8", "add r8, r9", "cmp r8, r9",
    "mov pc, lr", "add pc, r0", "bx r0", "bx pc", "ldr r0, [pc, #8]", "ldr r0, [pc, #1020]",
    "str r0, [r1, r2]", "ldrb r0, [r1, r2]", "strh r0, [r1, r2]", "ldrsh r0, [r1, r2]",
    "ldrsb r0, [r1, r2]", "ldrh r0, [r1, #2]", "ldrb r0, [r1, #3]", "ldrb r0, [r1, #31]",
    "ldr r0, [r1, #124]", "strh r0, [r1, #62]", "str r0, [sp, #4]", "ldr r0, [sp, #1020]",
    "add r0, sp, #8", "add r0, sp, #1020", "adr r0, #8", "adr r0, #1020", "add sp, #8",
    "sub sp, #8", "add sp, #508", "sub sp, #508", "push {r4, lr}", "pop {r4, pc}", "push {lr}",
    "pop {pc}", "push {r0-r7, lr}", "ldmia r0!, {r1, r2}", "stmia r0!, {r1, r2}",
    "ldm r0, {r0, r1}", "beq #0x08000010", "bne #0x07ffffe0", "b #0x08000020",
    "b #0x08000400", "svc #5", "svc #255", "bl #0x08000100", "bl #0x07ff0000",
]


@pytest.mark.parametrize("text", ARM_CORPUS)
def test_arm_roundtrip(text):
    code = assemble(text, addr=BASE)
    assert len(code) == 4
    ins = decode_arm(int.from_bytes(code, "little"), BASE)
    assert ins.op is not Op.UNDEFINED
    rendered = format_instruction(ins)
    assert assemble(rendered, addr=BASE) == code, f"{text!r} rendered as {rendered!r}"


@pytest.mark.parametrize("text", THUMB_CORPUS)
def test_thumb_roundtrip(text):
    code = assemble(text, thumb=True, addr=BASE)
    assert len(code) in (2, 4), f"Keystone chose a Thumb-2 encoding for {text!r}"
    nxt = int.from_bytes(code[2:4], "little") if len(code) == 4 else None
    ins = decode_thumb(int.from_bytes(code[0:2], "little"), BASE, nxt)
    assert ins.op is not Op.UNDEFINED and ins.size == len(code)
    rendered = format_instruction(ins)
    assert assemble(rendered, thumb=True, addr=BASE) == code, f"{text!r} rendered as {rendered!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/isa/test_fmt.py tests/isa/test_roundtrip.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.isa.fmt'`

- [ ] **Step 3: Write the formatter**

Create `src/gbaport/isa/fmt.py`:

```python
"""Render decoded instructions as Keystone/LLVM-compatible UAL assembly.

The output must re-assemble to the same bytes (tests/isa/test_roundtrip.py).
Thumb flag-setting forms always carry ``s`` (``adds``, ``lsls``) because the
plain UAL forms would select 32-bit Thumb-2 encodings. Undefined words and
unpaired Thumb BL halves have no assembler syntax and print as data directives.
"""

from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    MOVE_OPS,
    Cond,
    Instruction,
    Mode,
    Op,
    Shift,
    ShiftKind,
)

REG_NAMES = tuple(f"r{n}" for n in range(13)) + ("sp", "lr", "pc")
_LONG_MULTIPLY_OPS = frozenset({Op.UMULL, Op.UMLAL, Op.SMULL, Op.SMLAL})
_TRANSFER_OPS = frozenset(
    {Op.LDR, Op.STR, Op.LDRB, Op.STRB, Op.LDRH, Op.STRH, Op.LDRSB, Op.LDRSH}
)
_BLOCK_MODES = {(False, True): "ia", (True, True): "ib", (False, False): "da", (True, False): "db"}
_PSR_FIELDS = ((3, "f"), (2, "s"), (1, "x"), (0, "c"))


def format_instruction(ins: Instruction) -> str:
    if ins.op is Op.UNDEFINED:
        return _data(ins)
    if ins.mode is Mode.THUMB:
        return _thumb(ins)
    return _arm(ins)


def _data(ins: Instruction) -> str:
    if ins.mode is Mode.ARM:
        return f".word {ins.raw:#010x}"
    return f".hword {ins.raw:#06x}"


def _reg(n: int) -> str:
    return REG_NAMES[n]


def _cond(ins: Instruction) -> str:
    return "" if ins.cond is Cond.AL else ins.cond.name.lower()


def _shift(shift: Shift | None) -> str:
    if shift is None:
        return ""
    if shift.kind is ShiftKind.RRX:
        return ", rrx"
    if shift.reg is not None:
        return f", {shift.kind.value} {_reg(shift.reg)}"
    return f", {shift.kind.value} #{shift.amount}"


def _reglist(regs: tuple[int, ...]) -> str:
    return "{" + ", ".join(_reg(r) for r in regs) + "}"


def _address(ins: Instruction) -> str:
    base = _reg(ins.rn)
    sign = "" if ins.up else "-"
    if ins.rm is not None:
        offset = f"{sign}{_reg(ins.rm)}{_shift(ins.shift)}"
    elif ins.pre and ins.up and not ins.writeback and ins.imm == 0:
        return f"[{base}]"
    else:
        offset = f"#{sign}{ins.imm}"
    if not ins.pre:
        return f"[{base}], {offset}"
    return f"[{base}, {offset}]" + ("!" if ins.writeback else "")


def _arm(ins: Instruction) -> str:
    op, c = ins.op, _cond(ins)
    s = "s" if ins.s and op not in COMPARE_OPS else ""
    if op in DATA_PROCESSING_OPS:
        operands = []
        if op not in COMPARE_OPS:
            operands.append(_reg(ins.rd))
        if op not in MOVE_OPS:
            operands.append(_reg(ins.rn))
        if ins.imm is not None:
            operands.append(f"#{ins.imm:#x}")
        else:
            operands.append(_reg(ins.rm) + _shift(ins.shift))
        return f"{op.value}{s}{c} " + ", ".join(operands)
    if op in (Op.MUL, Op.MLA):
        text = f"{op.value}{s}{c} {_reg(ins.rd)}, {_reg(ins.rm)}, {_reg(ins.rs)}"
        return text + (f", {_reg(ins.rn)}" if op is Op.MLA else "")
    if op in _LONG_MULTIPLY_OPS:
        return (
            f"{op.value}{s}{c} {_reg(ins.rd)}, {_reg(ins.rd_hi)}, "
            f"{_reg(ins.rm)}, {_reg(ins.rs)}"
        )
    if op in (Op.SWP, Op.SWPB):
        return f"{op.value}{c} {_reg(ins.rd)}, {_reg(ins.rm)}, [{_reg(ins.rn)}]"
    if op in _TRANSFER_OPS:
        t = "t" if ins.user else ""
        return f"{op.value}{t}{c} {_reg(ins.rd)}, {_address(ins)}"
    if op in (Op.LDM, Op.STM):
        mode = _BLOCK_MODES[(ins.pre, ins.up)]
        writeback = "!" if ins.writeback else ""
        caret = "^" if ins.user else ""
        return f"{op.value}{mode}{c} {_reg(ins.rn)}{writeback}, {_reglist(ins.reglist)}{caret}"
    if op in (Op.B, Op.BL):
        return f"{op.value}{c} #{ins.target:#x}"
    if op is Op.BX:
        return f"bx{c} {_reg(ins.rm)}"
    if op is Op.SWI:
        return f"svc{c} #{ins.imm:#x}"
    if op is Op.MRS:
        return f"mrs{c} {_reg(ins.rd)}, {'spsr' if ins.spsr else 'cpsr'}"
    if op is Op.MSR:
        fields = "".join(letter for bit, letter in _PSR_FIELDS if (ins.psr_mask >> bit) & 1)
        if not fields:
            return _data(ins)
        source = f"#{ins.imm:#x}" if ins.imm is not None else _reg(ins.rm)
        return f"msr{c} {'spsr' if ins.spsr else 'cpsr'}_{fields}, {source}"
    raise ValueError(f"no ARM syntax for {op}")


def _thumb(ins: Instruction) -> str:
    fmt, op = ins.thumb_format, ins.op
    if fmt == 1:
        kind = ins.shift.kind.value if ins.shift else "lsl"
        amount = ins.shift.amount if ins.shift else 0
        return f"{kind}s {_reg(ins.rd)}, {_reg(ins.rm)}, #{amount}"
    if fmt == 2:
        operand = f"#{ins.imm}" if ins.imm is not None else _reg(ins.rm)
        return f"{op.value}s {_reg(ins.rd)}, {_reg(ins.rn)}, {operand}"
    if fmt == 3:
        if op is Op.CMP:
            return f"cmp {_reg(ins.rn)}, #{ins.imm}"
        return f"{op.value}s {_reg(ins.rd)}, #{ins.imm}"
    if fmt == 4:
        if ins.shift is not None:
            return f"{ins.shift.kind.value}s {_reg(ins.rd)}, {_reg(ins.shift.reg)}"
        if op in COMPARE_OPS:
            return f"{op.value} {_reg(ins.rn)}, {_reg(ins.rm)}"
        if op is Op.RSB:
            return f"rsbs {_reg(ins.rd)}, {_reg(ins.rn)}, #0"
        if op is Op.MUL:
            return f"muls {_reg(ins.rd)}, {_reg(ins.rm)}, {_reg(ins.rd)}"
        return f"{op.value}s {_reg(ins.rd)}, {_reg(ins.rm)}"
    if fmt == 5:
        if op is Op.BX:
            return f"bx {_reg(ins.rm)}"
        if op is Op.CMP:
            return f"cmp {_reg(ins.rn)}, {_reg(ins.rm)}"
        return f"{op.value} {_reg(ins.rd)}, {_reg(ins.rm)}"
    if fmt == 6:
        return f"ldr {_reg(ins.rd)}, [pc, #{ins.imm}]"
    if fmt in (7, 8, 9, 10, 11):
        return f"{op.value} {_reg(ins.rd)}, {_address(ins)}"
    if fmt == 12:
        if ins.rn == 13:
            return f"add {_reg(ins.rd)}, sp, #{ins.imm}"
        return f"adr {_reg(ins.rd)}, #{ins.imm}"
    if fmt == 13:
        return f"{op.value} sp, #{ins.imm}"
    if fmt == 14:
        return f"{'pop' if op is Op.LDM else 'push'} {_reglist(ins.reglist)}"
    if fmt == 15:
        if ins.writeback:
            return f"{op.value}ia {_reg(ins.rn)}!, {_reglist(ins.reglist)}"
        return f"ldm {_reg(ins.rn)}, {_reglist(ins.reglist)}"
    if fmt in (16, 18):
        return f"b{_cond(ins)} #{ins.target:#x}"
    if fmt == 17:
        return f"svc #{ins.imm:#x}"
    if op is Op.BL:
        return f"bl #{ins.target:#x}"
    return f".hword {ins.raw:#06x}  @ {op.value} {ins.imm:+#x}"  # unpaired BL half
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/isa -v && uv run ruff check src tests`
Expected: all pass (6 in `test_fmt.py`, 63 ARM + 70 Thumb round-trips, plus earlier tasks); ruff clean.

If a single corpus entry fails **only** because Keystone re-encodes the rendered text with a different but equivalent encoding (the decoded fields match the ARM7TDMI data sheet for the original bytes), remove that entry and add a one-line comment above the corpus naming it and the reason. Any other failure is a decoder or formatter bug: fix the code, not the corpus.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/isa/fmt.py tests/ksasm.py tests/isa/test_fmt.py tests/isa/test_roundtrip.py
git commit -m "feat: UAL formatter verified by Keystone round-trip"
```

---

### Task 7: Linear disassembler and `gbaport disasm`

**Files:**
- Create: `src/gbaport/disasm.py`
- Modify: `src/gbaport/cli.py` (register `disasm`), `README.md` (Commands section)
- Test: `tests/test_disasm.py`

**Interfaces:**
- Consumes: `RomImage`, `RomError`, `ROM_BASE` (Task 2); `decode_arm` (Task 4); `decode_thumb` (Task 5); `format_instruction` (Task 6); `Mode`, `Instruction` (Task 4); CLI `build_parser` with `commands` subparsers (Task 3); test helpers `build_rom` (Task 2) and `assemble` (Task 6).
- Produces: `gbaport.disasm.disassemble(rom: RomImage, start: int, count: int, mode: Mode) -> list[Instruction]` (raises `ValueError` if `start` is misaligned, `RomError` if it is outside the ROM; stops early at the ROM end); `gbaport.disasm.format_line(ins: Instruction) -> str` (`"aaaaaaaa:  <raw, 9 wide>  <text>"`; Thumb BL raw shows both halfwords). CLI: `gbaport disasm ROM [--start ADDR] [--count N] [--thumb]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_disasm.py`:

```python
from ksasm import assemble
from romkit import ROM_BASE, build_rom

from gbaport.cli import main
from gbaport.disasm import disassemble
from gbaport.isa.model import Mode, Op
from gbaport.rom.image import RomImage

CODE_ADDR = ROM_BASE + 0xC0


def write(tmp_path, data: bytes):
    path = tmp_path / "game.gba"
    path.write_bytes(data)
    return path


def test_arm_listing(tmp_path, capsys):
    code = assemble("mov r0, #0x04000000\nldr r1, [pc, #4]\nstr r1, [r0]", addr=CODE_ADDR)
    path = write(tmp_path, build_rom(code))
    assert main(["disasm", str(path), "--start", hex(CODE_ADDR), "--count", "3"]) == 0
    words = [int.from_bytes(code[i:i + 4], "little") for i in range(0, 12, 4)]
    texts = ["mov r0, #0x4000000", "ldr r1, [pc, #4]", "str r1, [r0]"]
    expected = [
        f"{CODE_ADDR + 4 * i:08x}:  {word:08x}   {text}"
        for i, (word, text) in enumerate(zip(words, texts))
    ]
    assert capsys.readouterr().out.splitlines() == expected


def test_thumb_listing_joins_bl_halves(tmp_path, capsys):
    code = assemble("movs r0, #1\nbl #0x08000100", thumb=True, addr=CODE_ADDR)
    path = write(tmp_path, build_rom(code))
    args = ["disasm", str(path), "--start", hex(CODE_ADDR), "--count", "2", "--thumb"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "080000c0:  2001       movs r0, #1",
        "080000c2:  f000 f81d  bl #0x8000100",
    ]


def test_stops_at_rom_end():
    rom = RomImage(build_rom(size=0x200))
    listing = disassemble(rom, ROM_BASE + 0x1F8, 10, Mode.ARM)
    assert [ins.addr for ins in listing] == [ROM_BASE + 0x1F8, ROM_BASE + 0x1FC]


def test_bl_prefix_in_last_halfword_decodes_alone():
    rom = RomImage(build_rom(size=0x200, patches={0x1FE: (0xF000).to_bytes(2, "little")}))
    listing = disassemble(rom, ROM_BASE + 0x1FE, 5, Mode.THUMB)
    assert len(listing) == 1 and listing[0].op is Op.BL_HI


def test_unaligned_start_is_an_error(tmp_path, capsys):
    path = write(tmp_path, build_rom())
    assert main(["disasm", str(path), "--start", hex(CODE_ADDR + 2)]) == 1
    assert "not 4-byte aligned" in capsys.readouterr().err


def test_start_outside_rom_is_an_error(tmp_path, capsys):
    path = write(tmp_path, build_rom())
    assert main(["disasm", str(path), "--start", "0x02000000"]) == 1
    assert "outside ROM" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_disasm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.disasm'`

- [ ] **Step 3: Write the disassembler and register the command**

Create `src/gbaport/disasm.py`:

```python
"""Linear-sweep disassembly. Following control flow is Plan 2's job."""

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Instruction, Mode
from gbaport.isa.thumb import decode_thumb
from gbaport.rom.image import RomError, RomImage


def disassemble(rom: RomImage, start: int, count: int, mode: Mode) -> list[Instruction]:
    """Decode up to ``count`` consecutive instructions from ``start``; stops at the ROM end."""
    width = 4 if mode is Mode.ARM else 2
    if start % width:
        raise ValueError(f"start {start:#010x} is not {width}-byte aligned for {mode.value} code")
    if not rom.contains(start, width):
        raise RomError(f"start {start:#010x} is outside ROM")
    listing: list[Instruction] = []
    addr = start
    while len(listing) < count and rom.contains(addr, width):
        if mode is Mode.ARM:
            ins = decode_arm(rom.read32(addr), addr)
        else:
            following = rom.read16(addr + 2) if rom.contains(addr + 2, 2) else None
            ins = decode_thumb(rom.read16(addr), addr, following)
        listing.append(ins)
        addr += ins.size
    return listing


def format_line(ins: Instruction) -> str:
    if ins.mode is Mode.THUMB and ins.size == 4:
        raw = f"{ins.raw & 0xFFFF:04x} {ins.raw >> 16:04x}"
    else:
        raw = f"{ins.raw:0{ins.size * 2}x}"
    return f"{ins.addr:08x}:  {raw:<9}  {format_instruction(ins)}"
```

Modify `src/gbaport/cli.py`:

Add imports below the existing ones:

```python
from gbaport.disasm import disassemble, format_line
from gbaport.isa.model import Mode
from gbaport.rom.image import ROM_BASE
```

(Merge `ROM_BASE` into the existing `from gbaport.rom.image import RomImage` line: `from gbaport.rom.image import ROM_BASE, RomImage`.)

In `build_parser`, register the command after `_add_info_command(commands)`:

```python
    _add_disasm_command(commands)
```

Add these functions after `_run_info`:

```python
def _int_auto(text: str) -> int:
    """Parse decimal or 0x-prefixed hex."""
    return int(text, 0)


def _add_disasm_command(commands) -> None:
    disasm = commands.add_parser("disasm", help="linear-sweep disassembly of a ROM range")
    disasm.add_argument("rom", help="path to a .gba file")
    disasm.add_argument(
        "--start", type=_int_auto, default=ROM_BASE, help="bus address (default 0x08000000)"
    )
    disasm.add_argument("--count", type=int, default=32, help="instructions to show (default 32)")
    disasm.add_argument("--thumb", action="store_true", help="decode as Thumb instead of ARM")
    disasm.set_defaults(handler=_run_disasm)


def _run_disasm(args: argparse.Namespace) -> int:
    mode = Mode.THUMB if args.thumb else Mode.ARM
    for ins in disassemble(RomImage.load(args.rom), args.start, args.count, mode):
        print(format_line(ins))
    return 0
```

Append to the `## Commands` section of `README.md`:

```markdown
    uv run gbaport disasm roms/mygame.gba --start 0x080000c0 --count 40 [--thumb]
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -v && uv run ruff check src tests`
Expected: every test passes; ruff clean.

- [ ] **Step 5: Smoke-test on a real dump (manual, optional)**

If a dump is available in `roms/` (gitignored), run:

```bash
uv run gbaport info roms/<game>.gba
uv run gbaport disasm roms/<game>.gba --count 4
uv run gbaport disasm roms/<game>.gba --start <entry_point from info> --count 40
```

Expected: `info` shows the real title/game code and a save type; the first `disasm` line is `08000000:  ea00002e   b #0x80000c0` (or another branch); the entry-point listing reads as plausible ARM start-up code (`mov r0, #0x12`, `msr cpsr_fc, r0`, … is typical).

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/disasm.py src/gbaport/cli.py README.md tests/test_disasm.py
git commit -m "feat: linear disassembler and gbaport disasm"
```

---

## Done criteria for Plan 1

- `uv run pytest` passes: header, save type, CLI, bits, ARM decode table, Thumb decode table, 200k random ARM words, all 65,536 Thumb halfwords, formatter totality, 133 Keystone round-trips, disassembler.
- `uv run ruff check src tests` is clean.
- `gbaport info` and `gbaport disasm` work on a real dump.
- No ROM bytes are tracked by git (`git ls-files | grep -iE '\.(gba|sav)$'` prints nothing).

Next: write Plan 2 (code discovery) against the spec, using what the real-dump smoke test shows.
