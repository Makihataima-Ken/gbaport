# Plan 2 — Code Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `gbaport analyze ROM` finds the game's functions, basic blocks, jump tables and literal pools by recursive descent from the entry point and `game.toml` seeds, reports what it could not resolve, and writes the result as `analysis.json` for the recompiler (Plan 3).

**Architecture:** A new `gbaport.analysis` package. `config` loads `games/<code>/game.toml`; `space` exposes the decodable address space (ROM, its mirrors, RAM copies); `effects` and `flow` describe what one instruction does to registers and control flow; `tables` recognises compiler jump-table patterns; `discover` walks the code with per-walk constant tracking; `cfg` groups instructions into blocks and functions; `analyze` ties it together with coverage, JSON and a text summary. Everything is verified with small programs assembled by Keystone at test time.

**Tech Stack:** Python 3.13 stdlib (`tomllib`, `dataclasses`, `collections`), pytest, ruff, keystone-engine 0.9.2 (tests only).

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md` (this plan is roadmap item P2; trace import moves to a later plan, see Task 8 note)

## Global Constraints

- Python `>=3.13`, uv-managed; repo root `C:\Users\J-ASUS\Dev\GBA`; shell commands for Git Bash; work on a feature branch, not `main`.
- No new runtime dependencies (stdlib only). Keystone is imported only from `tests/`.
- Never commit ROM bytes or anything extracted from them. `game.toml` and `analysis.json` hold addresses, counts and hashes only.
- All addresses are absolute GBA bus addresses, masked to 32 bits. ROM mirrors (0x0A000000, 0x0C000000) fold onto 0x08000000.
- Analysis must never raise on any ROM content: unknown or garbage code becomes an `Issue`, never an exception. Bad user input (`game.toml`, CLI) raises `ConfigError`/`RomError` (both `ValueError`) so the CLI prints `error: …` and exits 1.
- Results are deterministic: same ROM + config → identical JSON.
- Commit messages are plain: no `Co-Authored-By` or other attribution trailer. Commits use the repo-local identity `Ken <ahmadsoud63@gmail.com>`.

## Review Focus

1. **Garbage reached as code** (data walked as instructions, random bytes, either mode) must end in issues, never an exception or a hang. Pinned in Task 6 (`test_garbage_never_crashes`).
2. **Loops and recursion** (`b .`, mutual recursion, branches back to a function's own entry) must terminate and give sane successors. Pinned in Task 6 (`test_loops_and_recursion_terminate`).
3. **A jump-table bound larger than the table** (for example `cmp r0, #200` near the end of the ROM) must stop at the ROM end instead of reading past it. Pinned in Task 5 (`test_table_rows_stop_at_rom_end`).
4. **Malformed `game.toml`** (wrong types, negative numbers, booleans, unknown keys, TOML syntax errors) must raise `ConfigError` naming the file and key. Pinned in Task 1 (`test_rejects_bad_config`).
5. **A config that does not fit the ROM** (sha1 mismatch, RAM blob outside the ROM, data range outside the ROM) must raise `ConfigError` before any analysis. Pinned in Task 2 (`test_rejects_bad_overlays`) and Task 8 (`test_sha1_mismatch_is_rejected`, `test_data_range_outside_rom_is_rejected`).

## File Structure

```
src/gbaport/analysis/__init__.py   (empty)
src/gbaport/analysis/config.py     GameConfig, RamCode, JumpTableOverride, parse/load, default path
src/gbaport/analysis/space.py      CodeSpace: ROM + mirrors + RAM-copied blobs
src/gbaport/analysis/effects.py    written_registers, computed_value, RegState, pc/interwork helpers
src/gbaport/analysis/flow.py       FlowKind, Flow, classify
src/gbaport/analysis/tables.py     Step, JumpTable, TableMatch, find_jump_table
src/gbaport/analysis/discover.py   Issue, Exploration, explore
src/gbaport/analysis/cfg.py        Block, Function, Program, build_program
src/gbaport/analysis/analyze.py    Coverage, Analysis, analyze_rom, analysis_to_dict, summary_lines
src/gbaport/cli.py                 + `analyze` command
tests/progkit.py                   sample programs + assemble/decode/explore helpers
tests/analysis/test_config.py
tests/analysis/test_space.py
tests/analysis/test_effects.py
tests/analysis/test_flow.py
tests/analysis/test_tables.py
tests/analysis/test_discover.py
tests/analysis/test_cfg.py
tests/analysis/test_analyze.py
tests/test_analyze_cli.py
```

---

### Task 1: `game.toml` loader

**Files:**
- Create: `src/gbaport/analysis/__init__.py` (empty), `src/gbaport/analysis/config.py`
- Modify: `docs/superpowers/specs/2026-10-17-gba-native-port-design.md` (jump_tables example)
- Test: `tests/analysis/test_config.py`

**Interfaces:**
- Consumes: `Mode` (`gbaport.isa.model`), `SaveType` (`gbaport.rom.savetype`).
- Produces: `class ConfigError(ValueError)`; `@dataclass(frozen=True) RamCode(rom: int, ram: int, size: int, mode: Mode)`; `@dataclass(frozen=True) JumpTableOverride(at: int, table: int, count: int)`; `@dataclass(frozen=True) GameConfig(rom_sha1: str | None = None, save: SaveType | None = None, entries: tuple[int, ...] = (), thumb_entries: tuple[int, ...] = (), data: tuple[tuple[int, int], ...] = (), jump_tables: tuple[JumpTableOverride, ...] = (), ram_code: tuple[RamCode, ...] = (), timing_model: str = "block")`; `parse_config(text: str, source: str = "game.toml") -> GameConfig`; `load_config(path) -> GameConfig`; `default_config_path(game_code: str, root: Path = Path(".")) -> Path | None`.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-02-code-discovery
```

- [ ] **Step 2: Write the failing tests**

Create `tests/analysis/test_config.py`:

```python
import re

import pytest

from gbaport.analysis.config import (
    ConfigError,
    GameConfig,
    JumpTableOverride,
    RamCode,
    default_config_path,
    load_config,
    parse_config,
)
from gbaport.isa.model import Mode
from gbaport.rom.savetype import SaveType

FULL = """
[rom]
sha1 = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"
save = "flash128k"

[code]
entries = [0x08000204]
thumb_entries = [0x08012345, 0x08012400]
data = [[0x08100000, 0x08180000]]
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]

[[ram_code]]
rom = 0x080F0000
ram = 0x03000000
size = 0x800
mode = "arm"

[timing]
model = "frame"
"""


def test_parses_full_config():
    assert parse_config(FULL) == GameConfig(
        rom_sha1="abcdef0123456789abcdef0123456789abcdef01",
        save=SaveType.FLASH128K,
        entries=(0x08000204,),
        thumb_entries=(0x08012345, 0x08012400),
        data=((0x08100000, 0x08180000),),
        jump_tables=(JumpTableOverride(0x0801F00C, 0x0801F010, 12),),
        ram_code=(RamCode(0x080F0000, 0x03000000, 0x800, Mode.ARM),),
        timing_model="frame",
    )


def test_empty_config_has_defaults():
    assert parse_config("") == GameConfig()


@pytest.mark.parametrize(
    "text,message",
    [
        ("[cod]\nentries = []", "unknown key(s): cod"),
        ("[code]\nentrys = [1]", "[code]: unknown key(s): entrys"),
        ("[code]\nentries = [-1]", "non-negative integer"),
        ("[code]\nentries = [true]", "non-negative integer"),
        ("[code]\nentries = 5", "list of addresses"),
        ("[code]\ndata = [[2, 1]]", "is empty"),
        ("[code]\ndata = [[1, 2, 3]]", "[start, end] pairs"),
        ("[code]\njump_tables = [{ at = 1, count = 2 }]", "missing key(s): table"),
        ("[code]\njump_tables = [{ at = 1, table = 2, count = 0 }]", "at least 1"),
        ('[[ram_code]]\nrom = 1\nram = 2\nsize = 3\nmode = "arm64"', "mode must be"),
        ('[[ram_code]]\nrom = 1\nram = 2\nmode = "arm"', "missing key(s): size"),
        ('[rom]\nsave = "floppy"', "save must be one of"),
        ('[rom]\nsha1 = "abc"', "40-character"),
        ('[timing]\nmodel = "cycle"', "model must be"),
        ("rom = 5", "[rom] must be a table"),
        ("[code\n", "game.toml"),
    ],
)
def test_rejects_bad_config(text, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        parse_config(text)


def test_load_config_reads_file(tmp_path):
    path = tmp_path / "game.toml"
    path.write_text("[code]\nentries = [0x08000100]\n")
    assert load_config(path).entries == (0x08000100,)


def test_load_config_names_the_file_in_errors(tmp_path):
    path = tmp_path / "mygame.toml"
    path.write_text("[code]\nbogus = 1\n")
    with pytest.raises(ConfigError, match="mygame.toml"):
        load_config(path)


def test_default_config_path(tmp_path):
    assert default_config_path("ATST", tmp_path) is None
    target = tmp_path / "games" / "ATST" / "game.toml"
    target.parent.mkdir(parents=True)
    target.write_text("")
    assert default_config_path("ATST", tmp_path) == target
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis'`

- [ ] **Step 4: Write the loader**

Create empty `src/gbaport/analysis/__init__.py`.

Create `src/gbaport/analysis/config.py`:

```python
"""Per-game overrides read from ``games/<game_code>/game.toml``.

The file holds addresses and counts only, never ROM bytes. Unknown keys are
errors so a typo cannot silently change the analysis.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbaport.isa.model import Mode
from gbaport.rom.savetype import SaveType


class ConfigError(ValueError):
    """game.toml is malformed or does not fit the ROM."""


@dataclass(frozen=True)
class RamCode:
    rom: int  # where the blob sits in the cartridge
    ram: int  # where the game copies it and runs it
    size: int
    mode: Mode


@dataclass(frozen=True)
class JumpTableOverride:
    at: int  # the instruction that jumps through the table
    table: int  # address of the first table entry
    count: int


@dataclass(frozen=True)
class GameConfig:
    rom_sha1: str | None = None
    save: SaveType | None = None
    entries: tuple[int, ...] = ()
    thumb_entries: tuple[int, ...] = ()
    data: tuple[tuple[int, int], ...] = ()  # [start, end) ranges that are never code
    jump_tables: tuple[JumpTableOverride, ...] = ()
    ram_code: tuple[RamCode, ...] = ()
    timing_model: str = "block"


_SECTIONS = {
    "rom": {"sha1", "save"},
    "code": {"entries", "thumb_entries", "data", "jump_tables"},
    "timing": {"model"},
}
_RAM_CODE_KEYS = {"rom", "ram", "size", "mode"}
_JUMP_TABLE_KEYS = {"at", "table", "count"}
_TIMING_MODELS = ("block", "frame")


def default_config_path(game_code: str, root: Path = Path(".")) -> Path | None:
    """``games/<game_code>/game.toml`` under ``root``, if it exists."""
    path = root / "games" / game_code / "game.toml"
    return path if path.is_file() else None


def load_config(path: str | Path) -> GameConfig:
    path = Path(path)
    return parse_config(path.read_text(encoding="utf-8"), str(path))


def parse_config(text: str, source: str = "game.toml") -> GameConfig:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: {exc}") from None
    _check_keys(doc, set(_SECTIONS) | {"ram_code"}, source)
    rom, code, timing = (_section(doc, name, source) for name in ("rom", "code", "timing"))
    return GameConfig(
        rom_sha1=_sha1(rom, source),
        save=_save(rom, source),
        entries=_addresses(code, "entries", source),
        thumb_entries=_addresses(code, "thumb_entries", source),
        data=_ranges(code, source),
        jump_tables=tuple(
            _jump_table(item, source) for item in _tables(code, "jump_tables", source)
        ),
        ram_code=tuple(_ram_code(item, source) for item in _tables(doc, "ram_code", source)),
        timing_model=_timing(timing, source),
    )


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _section(doc: dict, name: str, source: str) -> dict:
    value = doc.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: [{name}] must be a table")
    _check_keys(value, _SECTIONS[name], f"{source} [{name}]")
    return value


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where}: expected a non-negative integer, got {value!r}")
    return value


def _addresses(table: dict, key: str, source: str) -> tuple[int, ...]:
    values = table.get(key, [])
    if not isinstance(values, list):
        raise ConfigError(f"{source}: {key} must be a list of addresses")
    return tuple(_int(value, f"{source}: {key}") for value in values)


def _ranges(table: dict, source: str) -> tuple[tuple[int, int], ...]:
    values = table.get("data", [])
    if not isinstance(values, list):
        raise ConfigError(f"{source}: data must be a list of [start, end] pairs")
    ranges = []
    for item in values:
        if not isinstance(item, list) or len(item) != 2:
            raise ConfigError(f"{source}: data entries must be [start, end] pairs, got {item!r}")
        start, end = (_int(value, f"{source}: data") for value in item)
        if start >= end:
            raise ConfigError(f"{source}: data range [{start:#x}, {end:#x}] is empty")
        ranges.append((start, end))
    return tuple(ranges)


def _tables(table: dict, key: str, source: str) -> list[dict]:
    items = table.get(key, [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ConfigError(f"{source}: {key} must be an array of tables")
    return items


def _required(item: dict, keys: set[str], where: str) -> None:
    _check_keys(item, keys, where)
    missing = sorted(keys - set(item))
    if missing:
        raise ConfigError(f"{where}: missing key(s): {', '.join(missing)}")


def _jump_table(item: dict, source: str) -> JumpTableOverride:
    where = f"{source} jump_tables"
    _required(item, _JUMP_TABLE_KEYS, where)
    count = _int(item["count"], where)
    if count == 0:
        raise ConfigError(f"{where}: count must be at least 1")
    return JumpTableOverride(
        at=_int(item["at"], where), table=_int(item["table"], where), count=count
    )


def _ram_code(item: dict, source: str) -> RamCode:
    where = f"{source} [[ram_code]]"
    _required(item, _RAM_CODE_KEYS, where)
    size = _int(item["size"], where)
    if size == 0:
        raise ConfigError(f"{where}: size must be at least 1")
    return RamCode(
        rom=_int(item["rom"], where),
        ram=_int(item["ram"], where),
        size=size,
        mode=_mode(item["mode"], where),
    )


def _mode(value: object, where: str) -> Mode:
    if value not in ("arm", "thumb"):
        raise ConfigError(f'{where}: mode must be "arm" or "thumb", got {value!r}')
    return Mode(value)


def _sha1(rom: dict, source: str) -> str | None:
    value = rom.get("sha1")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 40:
        raise ConfigError(f"{source}: [rom] sha1 must be a 40-character hex string")
    return value.lower()


def _save(rom: dict, source: str) -> SaveType | None:
    value = rom.get("save")
    if value is None:
        return None
    try:
        return SaveType(value)
    except ValueError:
        names = ", ".join(save.value for save in SaveType)
        raise ConfigError(f"{source}: [rom] save must be one of {names}, got {value!r}") from None


def _timing(timing: dict, source: str) -> str:
    model = timing.get("model", "block")
    if model not in _TIMING_MODELS:
        raise ConfigError(f'{source}: [timing] model must be "block" or "frame", got {model!r}')
    return model
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace the line

```toml
jump_tables = [{ at = 0x0801F00C, count = 12, mode = "thumb" }]
```

with

```toml
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_config.py -v && uv run ruff check src tests`
Expected: 21 passed; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/analysis tests/analysis/test_config.py docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "feat: game.toml loader"
```

---

### Task 2: CodeSpace

**Files:**
- Create: `src/gbaport/analysis/space.py`
- Test: `tests/analysis/test_space.py`

**Interfaces:**
- Consumes: `ConfigError`, `RamCode` (Task 1); `RomImage`, `RomError`, `ROM_BASE` (`gbaport.rom.image`).
- Produces: `class CodeSpace(rom: RomImage, ram_code: tuple[RamCode, ...] = ())` with attribute `rom`, and methods `canonical(addr) -> int`, `rom_offset(addr, size=1) -> int | None`, `contains(addr, size=1) -> bool`, `read16(addr) -> int`, `read32(addr) -> int` (reads raise `RomError` outside).

- [ ] **Step 1: Write the failing tests**

Create `tests/analysis/test_space.py`:

```python
import pytest
from romkit import build_rom

from gbaport.analysis.config import ConfigError, RamCode
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.rom.image import RomError, RomImage


def rom_with_blob() -> RomImage:
    return RomImage(build_rom(size=0x400, patches={0x200: bytes(range(16))}))


def test_reads_rom_and_its_mirrors():
    space = CodeSpace(RomImage(build_rom(code=bytes([1, 2, 3, 4]))))
    assert space.read32(0x080000C0) == 0x04030201
    assert space.read32(0x0A0000C0) == 0x04030201
    assert space.read16(0x0C0000C2) == 0x0403
    assert space.canonical(0x0A0000C0) == 0x080000C0
    assert space.canonical(0x03000000) == 0x03000000


def test_ram_overlay_reads_blob_from_rom():
    blob = RamCode(rom=0x08000200, ram=0x03000000, size=16, mode=Mode.ARM)
    space = CodeSpace(rom_with_blob(), (blob,))
    assert space.read32(0x03000004) == 0x07060504
    assert space.contains(0x0300000C, 4)
    assert not space.contains(0x0300000E, 4)
    assert space.rom_offset(0x03000004) == 0x204


def test_reads_outside_raise():
    space = CodeSpace(RomImage(build_rom(size=0x400)))
    assert not space.contains(0x02000000)
    assert space.rom_offset(0x08000400) is None
    with pytest.raises(RomError, match="outside analysable code"):
        space.read16(0x02000000)


@pytest.mark.parametrize(
    "blobs,message",
    [
        ((RamCode(0x08000300, 0x03000000, 0x200, Mode.ARM),), "outside the ROM"),
        ((RamCode(0x08000200, 0x08001000, 0x10, Mode.ARM),), "inside cartridge space"),
        (
            (
                RamCode(0x08000200, 0x03000000, 0x10, Mode.ARM),
                RamCode(0x08000200, 0x03000008, 0x10, Mode.ARM),
            ),
            "overlap",
        ),
    ],
)
def test_rejects_bad_overlays(blobs, message):
    with pytest.raises(ConfigError, match=message):
        CodeSpace(rom_with_blob(), blobs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_space.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.space'`

- [ ] **Step 3: Write CodeSpace**

Create `src/gbaport/analysis/space.py`:

```python
"""The address space the analyser may decode: ROM, its mirrors, and RAM copies of ROM blobs."""

from gbaport.analysis.config import ConfigError, RamCode
from gbaport.rom.image import ROM_BASE, RomError, RomImage

ROM_MIRROR_END = 0x0E000000  # 0x08, 0x0A and 0x0C regions all show the cartridge


class CodeSpace:
    def __init__(self, rom: RomImage, ram_code: tuple[RamCode, ...] = ()) -> None:
        self.rom = rom
        self.overlays = tuple(sorted(ram_code, key=lambda blob: blob.ram))
        for blob in self.overlays:
            if not rom.contains(blob.rom, blob.size):
                raise ConfigError(f"ram_code blob {blob.rom:#x}+{blob.size:#x} is outside the ROM")
            if ROM_BASE <= blob.ram < ROM_MIRROR_END:
                raise ConfigError(f"ram_code target {blob.ram:#x} is inside cartridge space")
        for first, second in zip(self.overlays, self.overlays[1:]):
            if first.ram + first.size > second.ram:
                raise ConfigError(
                    f"ram_code blobs at {first.ram:#x} and {second.ram:#x} overlap"
                )

    def canonical(self, addr: int) -> int:
        """Fold the ROM wait-state mirrors onto 0x08000000."""
        if ROM_BASE <= addr < ROM_MIRROR_END:
            return ROM_BASE + (addr & 0x01FFFFFF)
        return addr

    def rom_offset(self, addr: int, size: int = 1) -> int | None:
        """Offset into the ROM file of the ``size`` bytes at ``addr``, or None."""
        addr = self.canonical(addr)
        if self.rom.contains(addr, size):
            return addr - ROM_BASE
        for blob in self.overlays:
            if blob.ram <= addr and addr + size <= blob.ram + blob.size:
                return blob.rom - ROM_BASE + (addr - blob.ram)
        return None

    def contains(self, addr: int, size: int = 1) -> bool:
        return self.rom_offset(addr, size) is not None

    def read16(self, addr: int) -> int:
        offset = self._offset(addr, 2)
        return int.from_bytes(self.rom.data[offset:offset + 2], "little")

    def read32(self, addr: int) -> int:
        offset = self._offset(addr, 4)
        return int.from_bytes(self.rom.data[offset:offset + 4], "little")

    def _offset(self, addr: int, size: int) -> int:
        offset = self.rom_offset(addr, size)
        if offset is None:
            raise RomError(f"{addr:#010x} is outside analysable code")
        return offset
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_space.py -v && uv run ruff check src tests`
Expected: 6 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/space.py tests/analysis/test_space.py
git commit -m "feat: CodeSpace with ROM mirrors and RAM overlays"
```

---

### Task 3: Register effects and constant tracking

**Files:**
- Create: `src/gbaport/analysis/effects.py`, `tests/progkit.py`
- Test: `tests/analysis/test_effects.py`

**Interfaces:**
- Consumes: `CodeSpace` (Task 2); model types (`gbaport.isa.model`); `assemble` (`tests/ksasm.py`), `build_rom` (`tests/romkit.py`).
- Produces:
  - `gbaport.analysis.effects`: `SP, LR, PC = 13, 14, 15`, `MASK`, `CALL_CLOBBERED`, `pc_value(ins) -> int`, `interwork_target(value) -> tuple[int, Mode]`, `written_registers(ins) -> frozenset[int]`, `computed_value(ins, state, space) -> int | None`, `@dataclass RegState(consts: dict[int, int], popped: frozenset[int])` with `value(reg, ins) -> int | None`, `step(ins, space) -> None`, `forget_call_clobbered() -> None`.
  - `tests/progkit.py`: `CODE_ADDR = 0x080000C0`, sample sources `CRT0`, `VENEER`, `THUMB_TABLE`, `UNBOUNDED_TABLE`, `ARM_TABLES`, `IRQ_IN_RAM`, `TAIL_CALLS`, `KNOWN_JUMP`, `RECURSION`; `program_rom(source, *, thumb=False, size=0x400, patches=None) -> RomImage`; `program_space(source, *, thumb=False, size=0x400) -> CodeSpace`; `decode_one(text, *, thumb=False, addr=CODE_ADDR) -> Instruction`; `decode_program(space, count, *, thumb=False, start=CODE_ADDR) -> list[Instruction]`.

- [ ] **Step 1: Write the test helper and the failing tests**

Create `tests/progkit.py`:

```python
"""Small programs assembled at test time, and helpers to decode them.

Address comments assume the program starts at CODE_ADDR (0x080000C0).
"""

from ksasm import assemble
from romkit import build_rom

from gbaport.analysis.space import CodeSpace
from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Instruction
from gbaport.isa.thumb import decode_thumb
from gbaport.rom.image import RomImage

CODE_ADDR = 0x080000C0

# ARM start-up code: installs an ARM IRQ handler and calls Thumb main via `mov lr, pc; bx`.
#   c0 start (ARM)   dc irqvec   e0 mainptr   e4 irq (ARM)
#   e8 main (Thumb)  f6 helper   fa, fc: helper's later blocks
CRT0 = """
start:
    ldr r1, irqvec
    adr r0, irq
    str r0, [r1]
    ldr r1, mainptr
    mov lr, pc
    bx r1
    b start
irqvec: .word 0x03007FFC
mainptr: .word main+1
irq:
    bx lr
.thumb
main:
    push {r4, lr}
    bl helper
    movs r0, #0
    pop {r4}
    pop {r1}
    bx r1
helper:
    cmp r0, #3
    beq done
    adds r0, #1
done:
    bx lr
"""

# Thumb call through an agbcc-style `bx r3` veneer.
#   c0 main   c4 bl via_r3   cc fptr   d0 via_r3   d4 target
VENEER = """
main:
    push {lr}
    ldr r3, fptr
    bl via_r3
    pop {r0}
    bx r0
.align 2
fptr: .word target+1
via_r3:
    bx r3
    mov r8, r8
target:
    bx lr
"""

# agbcc Thumb switch: bound check, scale, add table base, load, mov pc.
#   cc dispatch   d0 tabaddr   d4 table (3 words)   e0 c0   e2 c1   e4 c2   e6 dflt
THUMB_TABLE = """
disp:
    cmp r0, #2
    bhi dflt
    lsls r0, r0, #2
    ldr r1, tabaddr
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
.align 2
tabaddr: .word tab
tab:
    .word c0
    .word c1
    .word c2
c0: bx lr
c1: bx lr
c2: bx lr
dflt: bx lr
"""

# The same switch without its bound check.
#   c8 dispatch   cc tabaddr   d0 table (2 words)   d8 c0   da c1
UNBOUNDED_TABLE = """
disp:
    lsls r0, r0, #2
    ldr r1, tabaddr
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
.align 2
tabaddr: .word tab
tab:
    .word c0
    .word c1
c0: bx lr
c1: bx lr
"""

# ARM `ldrls pc, [pc, r0, lsl #2]` address table, then an `addls pc, pc` branch table.
#   c4 dispatch 1   cc table   d4 c0   d8 c1   dc dflt   e0 dispatch 2   e8/ec branches   f0 out
ARM_TABLES = """
disp:
    cmp r0, #1
    ldrls pc, [pc, r0, lsl #2]
    b dflt
    .word c0
    .word c1
c0: bx lr
c1: bx lr
dflt:
    cmp r1, #1
    addls pc, pc, r1, lsl #2
    b out
    b c0
    b c1
out:
    bx lr
"""

# ARM code storing a RAM address into the IRQ vector.   c8 the store
IRQ_IN_RAM = """
    ldr r1, vec
    ldr r0, handler
    str r0, [r1]
    bx lr
vec: .word 0x03007FFC
handler: .word 0x03001000
"""

# Thumb: f ends with a plain branch into another function.   c0 main   ca f   cc g
TAIL_CALLS = """
main:
    push {lr}
    bl g
    pop {r0}
    bx r0
f:
    b g
g:
    bx lr
"""

# Thumb jump through a known pointer.   c2 bx r0   c4 pointer   c8 other
KNOWN_JUMP = """
    ldr r0, ptr
    bx r0
.align 2
ptr: .word other+1
other:
    bx lr
"""

# Thumb mutual recursion plus a branch-to-self loop.   c0 fa   c6 fb   cc spin
RECURSION = """
fa:
    bl fb
    bx lr
fb:
    bl fa
    b spin
spin:
    b spin
"""


def program_rom(
    source: str, *, thumb: bool = False, size: int = 0x400, patches: dict | None = None
) -> RomImage:
    code = assemble(source, thumb=thumb, addr=CODE_ADDR)
    return RomImage(build_rom(code, size=size, patches=patches))


def program_space(source: str, *, thumb: bool = False, size: int = 0x400) -> CodeSpace:
    return CodeSpace(program_rom(source, thumb=thumb, size=size))


def decode_one(text: str, *, thumb: bool = False, addr: int = CODE_ADDR) -> Instruction:
    code = assemble(text, thumb=thumb, addr=addr)
    if thumb:
        following = int.from_bytes(code[2:4], "little") if len(code) >= 4 else None
        return decode_thumb(int.from_bytes(code[:2], "little"), addr, following)
    return decode_arm(int.from_bytes(code[:4], "little"), addr)


def decode_program(
    space: CodeSpace, count: int, *, thumb: bool = False, start: int = CODE_ADDR
) -> list[Instruction]:
    """Decode ``count`` consecutive instructions (a Thumb BL pair counts once)."""
    listing, addr = [], start
    for _ in range(count):
        if thumb:
            ins = decode_thumb(space.read16(addr), addr, space.read16(addr + 2))
        else:
            ins = decode_arm(space.read32(addr), addr)
        listing.append(ins)
        addr += ins.size
    return listing
```

Create `tests/analysis/test_effects.py`:

```python
import pytest
from progkit import decode_one, decode_program, program_space

from gbaport.analysis.effects import RegState, interwork_target, pc_value, written_registers
from gbaport.isa.model import Mode


def run_states(source: str, count: int, *, thumb: bool = False) -> RegState:
    space = program_space(source, thumb=thumb)
    state = RegState()
    for ins in decode_program(space, count, thumb=thumb):
        state.step(ins, space)
    return state


@pytest.mark.parametrize(
    "text,thumb,expected",
    [
        ("adds r0, r1, r2", True, {0}),
        ("cmp r0, #1", True, set()),
        ("ldr r0, [r1], #4", False, {0, 1}),
        ("str r0, [r1, #4]!", False, {1}),
        ("pop {r4, pc}", True, {4, 13}),
        ("push {r4, lr}", True, {13}),
        ("umull r0, r1, r2, r3", False, {0, 1}),
        ("bl #0x08000100", True, {14}),
        ("svc #1", True, {0, 1, 2, 3, 12}),
        ("mov pc, lr", True, set()),
    ],
)
def test_written_registers(text, thumb, expected):
    assert written_registers(decode_one(text, thumb=thumb)) == expected


def test_pc_value_and_interworking():
    assert pc_value(decode_one("bx lr")) == 0x080000C8
    assert pc_value(decode_one("bx lr", thumb=True)) == 0x080000C4
    assert interwork_target(0x08000201) == (0x08000200, Mode.THUMB)
    assert interwork_target(0x08000202) == (0x08000200, Mode.ARM)


def test_literal_load_is_constant():
    state = run_states("ldr r0, lit\nbx lr\nlit: .word 0x12345678", 1)
    assert state.consts == {0: 0x12345678}


def test_thumb_adr_moves_shifts_and_adds():
    source = (
        "adr r0, here\nmovs r1, #1\nlsls r1, r1, #26\nadds r2, r1, #4\nmov r3, r2\n"
        "bx lr\n.align 2\nhere: .word 0"
    )
    state = run_states(source, 5, thumb=True)
    assert state.consts == {0: 0x080000CC, 1: 0x04000000, 2: 0x04000004, 3: 0x04000004}


def test_arm_add_pc_reads_address_plus_8():
    assert run_states("add r0, pc, #4\nbx lr", 1).consts == {0: 0x080000CC}


def test_unknown_operands_and_overwrites_forget_constants():
    source = "movs r0, #1\nldr r0, [r1]\nmovs r2, #3\nadds r2, r2, r4\nbx lr"
    assert run_states(source, 4, thumb=True).consts == {}


def test_conditional_write_forgets_register():
    assert run_states("mov r0, #1\nmoveq r0, #2\nbx lr", 2).consts == {}


def test_pops_are_remembered_until_overwritten():
    state = run_states("push {r4, lr}\npop {r4}\npop {r1}\nbx r1", 3, thumb=True)
    assert state.popped == {1, 4}
    state = run_states("pop {r1}\nmovs r1, #0\nbx lr", 2, thumb=True)
    assert state.popped == frozenset()


def test_call_forgets_caller_saved_registers():
    state = RegState(consts={0: 1, 4: 2, 12: 3, 14: 4}, popped=frozenset({0, 5}))
    state.forget_call_clobbered()
    assert state.consts == {4: 2}
    assert state.popped == {5}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_effects.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.effects'`

- [ ] **Step 3: Write the effects module**

Create `src/gbaport/analysis/effects.py`:

```python
"""Register effects and the constants one linear walk can track."""

from dataclasses import dataclass, field

from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    Cond,
    Instruction,
    Mode,
    Op,
    Shift,
    ShiftKind,
)

SP, LR, PC = 13, 14, 15
MASK = 0xFFFFFFFF
# Registers a call (or a BIOS SWI) may change under the ARM procedure call standard.
CALL_CLOBBERED = frozenset({0, 1, 2, 3, 12, LR})
_LOADS = frozenset({Op.LDR, Op.LDRB, Op.LDRH, Op.LDRSB, Op.LDRSH})
_STORES = frozenset({Op.STR, Op.STRB, Op.STRH})
_TRANSFERS = _LOADS | _STORES | {Op.LDM, Op.STM}
_LONG_MULTIPLY = frozenset({Op.UMULL, Op.UMLAL, Op.SMULL, Op.SMLAL})
_SINGLE_DEST = frozenset({Op.MUL, Op.MLA, Op.SWP, Op.SWPB, Op.MRS}) | _LOADS


def pc_value(ins: Instruction) -> int:
    """What reading r15 yields while ``ins`` executes (Thumb: no word alignment)."""
    return ins.addr + (8 if ins.mode is Mode.ARM else 4)


def interwork_target(value: int) -> tuple[int, Mode]:
    """Where ``bx`` to ``value`` lands: bit 0 selects Thumb."""
    if value & 1:
        return value & ~1, Mode.THUMB
    return value & ~3, Mode.ARM


def written_registers(ins: Instruction) -> frozenset[int]:
    """General registers ``ins`` may change; r15 is never included."""
    op = ins.op
    regs: set[int] = set()
    if (op in DATA_PROCESSING_OPS and op not in COMPARE_OPS) or op in _SINGLE_DEST:
        regs.add(ins.rd)
    elif op in _LONG_MULTIPLY:
        regs.update((ins.rd, ins.rd_hi))
    elif op is Op.LDM:
        regs.update(ins.reglist)
    elif op in (Op.BL, Op.BL_HI, Op.BL_LO):
        regs.add(LR)
    elif op is Op.SWI:
        regs.update(CALL_CLOBBERED - {LR})
    if op in _TRANSFERS and ins.writeback:
        regs.add(ins.rn)
    regs.discard(PC)
    return frozenset(regs)


def computed_value(ins: Instruction, state: "RegState", space: CodeSpace) -> int | None:
    """The value ``ins`` writes to its destination, when it is a known constant.

    Covers literal loads, and MOV/MVN/ADD/SUB with immediate or known-register
    operands (immediate shifts included). The condition code is not checked.
    """
    op = ins.op
    if op is Op.LDR:
        if ins.rn == PC and ins.target is not None and space.contains(ins.target, 4):
            return space.read32(ins.target)
        return None
    if op not in (Op.MOV, Op.MVN, Op.ADD, Op.SUB):
        return None
    if ins.target is not None:  # Thumb ADR
        return ins.target
    if ins.imm is not None:
        operand = ins.imm
    else:
        operand = state.value(ins.rm, ins)
        if operand is not None and ins.shift is not None:
            operand = _shifted(operand, ins.shift)
    if operand is None:
        return None
    if op is Op.MOV:
        return operand
    if op is Op.MVN:
        return ~operand & MASK
    base = state.value(ins.rn, ins)
    if base is None:
        return None
    return (base + operand) & MASK if op is Op.ADD else (base - operand) & MASK


def _shifted(value: int, shift: Shift) -> int | None:
    if shift.reg is not None or shift.kind is ShiftKind.RRX:
        return None
    n = shift.amount
    if shift.kind is ShiftKind.LSL:
        return (value << n) & MASK
    if shift.kind is ShiftKind.LSR:
        return value >> n if n < 32 else 0
    if shift.kind is ShiftKind.ASR:
        signed = value - (1 << 32) if value & 0x80000000 else value
        return (signed >> min(n, 31)) & MASK
    return ((value >> n) | (value << (32 - n))) & MASK  # ROR by 1..31


@dataclass
class RegState:
    """What one linear walk knows: constant registers, and registers just popped."""

    consts: dict[int, int] = field(default_factory=dict)
    popped: frozenset[int] = frozenset()

    def value(self, reg: int, ins: Instruction) -> int | None:
        if reg == PC:
            return pc_value(ins)
        return self.consts.get(reg)

    def step(self, ins: Instruction, space: CodeSpace) -> None:
        """Advance past ``ins`` along its fall-through path."""
        result = None
        if ins.cond is Cond.AL and ins.rd is not None and ins.rd != PC:
            result = computed_value(ins, self, space)
        written = written_registers(ins)
        for reg in written:
            self.consts.pop(reg, None)
        self.popped -= written
        if ins.op is Op.LDM and ins.rn == SP:
            self.popped |= frozenset(ins.reglist) - {PC}
        if result is not None:
            self.consts[ins.rd] = result

    def forget_call_clobbered(self) -> None:
        for reg in CALL_CLOBBERED:
            self.consts.pop(reg, None)
        self.popped -= CALL_CLOBBERED
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_effects.py -v && uv run ruff check src tests`
Expected: 18 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/effects.py tests/progkit.py tests/analysis/test_effects.py
git commit -m "feat: register effects and per-walk constant tracking"
```

---

### Task 4: Control-flow classification

**Files:**
- Create: `src/gbaport/analysis/flow.py`
- Test: `tests/analysis/test_flow.py`

**Interfaces:**
- Consumes: `LR`, `PC`, `SP`, `RegState`, `computed_value`, `interwork_target` (Task 3); `CodeSpace` (Task 2); `decode_one`, `program_space` (Task 3 `progkit`).
- Produces: `NORETURN_SWIS`; `class FlowKind(Enum)` with `NEXT, CALL, BRANCH, RETURN, JUMP, INDIRECT, STOP`; `@dataclass(frozen=True) Flow(kind: FlowKind, target: tuple[int, Mode] | None = None, falls_through: bool = False)`; `classify(ins, state: RegState, prev: Instruction | None, space: CodeSpace) -> Flow`.

- [ ] **Step 1: Write the failing tests**

Create `tests/analysis/test_flow.py`:

```python
import pytest
from progkit import decode_one, program_space
from romkit import build_rom

from gbaport.analysis.effects import RegState
from gbaport.analysis.flow import Flow, FlowKind, classify
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage

EMPTY = CodeSpace(RomImage(build_rom()))
THUMB, ARM = Mode.THUMB, Mode.ARM


def flow(text, *, thumb=False, consts=None, popped=(), prev=None, space=EMPTY):
    state = RegState(consts=dict(consts or {}), popped=frozenset(popped))
    previous = None if prev is None else decode_one(prev, thumb=thumb)
    return classify(decode_one(text, thumb=thumb), state, previous, space)


@pytest.mark.parametrize(
    "text,thumb,expected",
    [
        ("adds r0, #1", True, Flow(FlowKind.NEXT)),
        ("svc #5", True, Flow(FlowKind.NEXT)),
        ("svc #0", True, Flow(FlowKind.STOP)),
        ("svc #0x260000", False, Flow(FlowKind.STOP)),
        (".hword 0xde00", True, Flow(FlowKind.STOP)),
        ("b #0x08000100", True, Flow(FlowKind.BRANCH, (0x08000100, THUMB))),
        ("beq #0x08000100", True, Flow(FlowKind.BRANCH, (0x08000100, THUMB), True)),
        ("bl #0x08000100", True, Flow(FlowKind.CALL, (0x08000100, THUMB), True)),
        (".hword 0xf87e", True, Flow(FlowKind.CALL, None, True)),
        ("bx lr", True, Flow(FlowKind.RETURN)),
        ("bxeq lr", False, Flow(FlowKind.RETURN, falls_through=True)),
        ("pop {r4, pc}", True, Flow(FlowKind.RETURN)),
        ("ldmfd sp!, {r4, pc}", False, Flow(FlowKind.RETURN)),
        ("subs pc, lr, #4", False, Flow(FlowKind.RETURN)),
        ("ldr pc, [sp], #4", False, Flow(FlowKind.RETURN)),
        ("mov pc, lr", True, Flow(FlowKind.RETURN)),
        ("bx r0", True, Flow(FlowKind.INDIRECT)),
        ("mov pc, r0", True, Flow(FlowKind.INDIRECT)),
        ("add pc, pc, r0, lsl #2", False, Flow(FlowKind.INDIRECT)),
        ("addls pc, pc, r0, lsl #2", False, Flow(FlowKind.INDIRECT, falls_through=True)),
    ],
)
def test_classify(text, thumb, expected):
    assert flow(text, thumb=thumb) == expected


def test_bx_to_popped_register_returns():
    assert flow("bx r1", thumb=True, popped={1}) == Flow(FlowKind.RETURN)


def test_bx_to_known_value_jumps_with_interworking():
    to_thumb = flow("bx r0", thumb=True, consts={0: 0x08000201})
    to_arm = flow("bx r0", thumb=True, consts={0: 0x08000200})
    assert to_thumb == Flow(FlowKind.JUMP, (0x08000200, THUMB))
    assert to_arm == Flow(FlowKind.JUMP, (0x08000200, ARM))


def test_bx_pc_switches_to_arm():
    assert flow("bx pc", thumb=True) == Flow(FlowKind.JUMP, (0x080000C4, ARM))


def test_link_idiom_turns_a_jump_into_a_call():
    called = flow("bx r1", consts={1: 0x080000E9}, prev="mov lr, pc")
    assert called == Flow(FlowKind.CALL, (0x080000E8, THUMB), falls_through=True)
    assert flow("bx r2", prev="mov lr, pc") == Flow(FlowKind.CALL, None, falls_through=True)


def test_ldr_pc_from_literal_jumps_without_interworking():
    space = program_space("ldr pc, lit\nlit: .word 0x08000201")
    assert flow("ldr pc, [pc, #-4]", space=space) == Flow(FlowKind.JUMP, (0x08000200, ARM))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_flow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.flow'`

- [ ] **Step 3: Write the classifier**

Create `src/gbaport/analysis/flow.py`:

```python
"""How control leaves one instruction, as seen by the code walk."""

from dataclasses import dataclass
from enum import Enum

from gbaport.analysis.effects import (
    LR,
    PC,
    SP,
    RegState,
    computed_value,
    interwork_target,
)
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import COMPARE_OPS, DATA_PROCESSING_OPS, Cond, Instruction, Mode, Op

NORETURN_SWIS = frozenset({0x00, 0x26})  # SoftReset, HardReset


class FlowKind(Enum):
    NEXT = "next"  # carries on with the following instruction
    CALL = "call"  # calls a function that returns here
    BRANCH = "branch"  # direct jump inside the function
    RETURN = "return"
    JUMP = "jump"  # leaves the function for a known address
    INDIRECT = "indirect"  # target unknown here; the walker tries jump-table patterns
    STOP = "stop"  # undefined instruction, or a BIOS call that never returns


@dataclass(frozen=True)
class Flow:
    kind: FlowKind
    target: tuple[int, Mode] | None = None  # BRANCH/CALL/JUMP destination; None = unknown
    falls_through: bool = False  # the following instruction may run next as well


def classify(
    ins: Instruction, state: RegState, prev: Instruction | None, space: CodeSpace
) -> Flow:
    op, conditional = ins.op, ins.cond is not Cond.AL
    if op is Op.UNDEFINED:
        return Flow(FlowKind.STOP)
    if op is Op.SWI:
        number = ins.imm >> 16 if ins.mode is Mode.ARM else ins.imm
        stops = number in NORETURN_SWIS and not conditional
        return Flow(FlowKind.STOP if stops else FlowKind.NEXT)
    if op is Op.B:
        return Flow(FlowKind.BRANCH, (ins.target, ins.mode), falls_through=conditional)
    if op is Op.BL:
        return Flow(FlowKind.CALL, (ins.target, ins.mode), falls_through=True)
    if op is Op.BL_LO:  # unpaired second half: calls LR + offset, and LR is unknown here
        return Flow(FlowKind.CALL, None, falls_through=True)
    if not _writes_pc(ins):
        return Flow(FlowKind.NEXT)
    if _is_return(ins, state):
        return Flow(FlowKind.RETURN, falls_through=conditional)
    target = _pc_target(ins, state, space)
    if _links_to_next(prev):
        return Flow(FlowKind.CALL, target, falls_through=True)
    if target is None:
        return Flow(FlowKind.INDIRECT, falls_through=conditional)
    return Flow(FlowKind.JUMP, target, falls_through=conditional)


def _writes_pc(ins: Instruction) -> bool:
    if ins.op is Op.BX:
        return True
    if ins.op in DATA_PROCESSING_OPS and ins.op not in COMPARE_OPS:
        return ins.rd == PC
    if ins.op is Op.LDR:
        return ins.rd == PC
    if ins.op is Op.LDM:
        return PC in ins.reglist
    return False


def _is_return(ins: Instruction, state: RegState) -> bool:
    if ins.op is Op.BX:
        return ins.rm == LR or ins.rm in state.popped
    if ins.op in (Op.LDM, Op.LDR):  # pop {..., pc} / ldr pc, [sp], #4
        return ins.rn == SP
    # mov pc, lr / movs pc, lr / subs pc, lr, #4 / mov pc, <register just popped>
    return LR in (ins.rn, ins.rm) or (ins.op is Op.MOV and ins.rm in state.popped)


def _pc_target(ins: Instruction, state: RegState, space: CodeSpace) -> tuple[int, Mode] | None:
    if ins.op is Op.BX:
        value = state.value(ins.rm, ins)
        return None if value is None else interwork_target(value)
    value = computed_value(ins, state, space)  # ARMv4T: writing pc never changes state
    if value is None:
        return None
    return value & (~1 if ins.mode is Mode.THUMB else ~3), ins.mode


def _links_to_next(prev: Instruction | None) -> bool:
    """``mov lr, pc`` just before a jump turns that jump into a call."""
    return (
        prev is not None
        and prev.op is Op.MOV
        and prev.rd == LR
        and prev.rm == PC
        and prev.shift is None
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_flow.py -v && uv run ruff check src tests`
Expected: 25 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/flow.py tests/analysis/test_flow.py
git commit -m "feat: control-flow classification"
```

---

### Task 5: Jump-table recognition

**Files:**
- Create: `src/gbaport/analysis/tables.py`
- Test: `tests/analysis/test_tables.py`

**Interfaces:**
- Consumes: `JumpTableOverride` (Task 1); `CodeSpace` (Task 2); `PC`, `RegState`, `written_registers` (Task 3); `THUMB_TABLE`, `UNBOUNDED_TABLE`, `ARM_TABLES`, `decode_program`, `program_space` (Task 3 `progkit`).
- Produces: `MAX_TABLE_ENTRIES = 1024`; `@dataclass(frozen=True) Step(ins: Instruction, consts: dict[int, int])`; `@dataclass(frozen=True) JumpTable(dispatch: int, table: int, mode: Mode, targets: tuple[int, ...], data: bool)`; `@dataclass(frozen=True) TableMatch(table: JumpTable | None, problem: str | None = None)`; `find_jump_table(dispatch, history: list[Step], space, overrides: dict[int, JumpTableOverride]) -> TableMatch | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/analysis/test_tables.py`:

```python
from progkit import ARM_TABLES, THUMB_TABLE, UNBOUNDED_TABLE, decode_program, program_space

from gbaport.analysis.config import JumpTableOverride
from gbaport.analysis.effects import RegState
from gbaport.analysis.tables import JumpTable, Step, TableMatch, find_jump_table
from gbaport.isa.model import Mode


def dispatch_after(space, count, *, thumb, start=0x080000C0):
    """Run ``count`` instructions; return the next one and the history before it."""
    listing = decode_program(space, count + 1, thumb=thumb, start=start)
    state, history = RegState(), []
    for ins in listing[:-1]:
        history.append(Step(ins, dict(state.consts)))
        state.step(ins, space)
    return listing[-1], history


def test_thumb_switch_table():
    space = program_space(THUMB_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 6, thumb=True)
    targets = (0x080000E0, 0x080000E2, 0x080000E4)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000CC, 0x080000D4, Mode.THUMB, targets, data=True)
    )


def test_arm_ldr_pc_table():
    space = program_space(ARM_TABLES)
    dispatch, history = dispatch_after(space, 1, thumb=False)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000C4, 0x080000CC, Mode.ARM, (0x080000D4, 0x080000D8), data=True)
    )


def test_arm_branch_table():
    space = program_space(ARM_TABLES)
    dispatch, history = dispatch_after(space, 1, thumb=False, start=0x080000DC)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000E0, 0x080000E8, Mode.ARM, (0x080000E8, 0x080000EC), data=False)
    )


def test_missing_bound_is_reported_not_guessed():
    space = program_space(UNBOUNDED_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 4, thumb=True)
    match = find_jump_table(dispatch, history, space, {})
    assert match.table is None
    assert "{ at = 0x080000c8, table = 0x080000d0, count = N }" in match.problem


def test_override_supplies_table_and_count():
    space = program_space(UNBOUNDED_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 4, thumb=True)
    overrides = {0x080000C8: JumpTableOverride(0x080000C8, 0x080000D0, 2)}
    match = find_jump_table(dispatch, history, space, overrides)
    assert match.table.targets == (0x080000D8, 0x080000DA)


def test_unrecognised_indirect_jump():
    space = program_space("ldr r0, [r1]\nmov pc, r0", thumb=True)
    dispatch, history = dispatch_after(space, 1, thumb=True)
    assert find_jump_table(dispatch, history, space, {}) is None


def test_table_rows_stop_at_rom_end():
    source = THUMB_TABLE.replace("cmp r0, #2", "cmp r0, #200")
    space = program_space(source, thumb=True, size=0x100)
    dispatch, history = dispatch_after(space, 6, thumb=True)
    match = find_jump_table(dispatch, history, space, {})
    assert len(match.table.targets) == (0x100 - 0xD4) // 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_tables.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.tables'`

- [ ] **Step 3: Write the recogniser**

Create `src/gbaport/analysis/tables.py`:

```python
"""Jump-table recognition at an indirect jump.

Patterns (``history`` is the current walk before the dispatch):

- agbcc Thumb switch: ``cmp rI, #N; b<hi> default; lsls rT, rI, #2;
  ldr rB, =table; adds rA, rT, rB; ldr rX, [rA]; mov pc, rX`` (also the
  ``ldr rX, [rT, rB]`` form). Entries are addresses.
- ARM ``ldr<ls> pc, [pc, rI, lsl #2]``: entries are addresses starting at dispatch + 8.
- ARM ``add<ls> pc, pc, rI, lsl #2``: a run of ``b`` instructions at dispatch + 8.

The entry count always comes from the guarding ``cmp rI, #N`` (N + 1 entries);
without it the table is reported instead of guessed.
"""

from dataclasses import dataclass

from gbaport.analysis.config import JumpTableOverride
from gbaport.analysis.effects import PC, written_registers
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Instruction, Mode, Op, Shift, ShiftKind

MAX_TABLE_ENTRIES = 1024
_TIMES_4 = Shift(ShiftKind.LSL, 2)


@dataclass(frozen=True)
class Step:
    """An instruction of the current walk and the constants known just before it ran."""

    ins: Instruction
    consts: dict[int, int]


@dataclass(frozen=True)
class JumpTable:
    dispatch: int  # the instruction that jumps through the table
    table: int  # first entry
    mode: Mode
    targets: tuple[int, ...]
    data: bool  # True: entries are addresses (data); False: entries are ARM B instructions


@dataclass(frozen=True)
class TableMatch:
    table: JumpTable | None
    problem: str | None = None  # why a recognised table could not be used


def find_jump_table(
    dispatch: Instruction,
    history: list[Step],
    space: CodeSpace,
    overrides: dict[int, JumpTableOverride],
) -> TableMatch | None:
    """The table ``dispatch`` jumps through, or None when no known pattern matches."""
    override = overrides.get(dispatch.addr)
    if override is not None:
        return TableMatch(_address_table(dispatch, override.table, override.count, space))
    found = _match(dispatch, history)
    if found is None:
        return None
    table, count, holds_addresses = found
    if count is None:
        return TableMatch(
            None,
            f"jump table at {table:#010x} has no bound; add "
            f"{{ at = {dispatch.addr:#010x}, table = {table:#010x}, count = N }} "
            "to [code] jump_tables",
        )
    if holds_addresses:
        return TableMatch(_address_table(dispatch, table, count, space))
    targets = tuple(table + 4 * i for i in range(min(count, MAX_TABLE_ENTRIES)))
    return TableMatch(JumpTable(dispatch.addr, table, dispatch.mode, targets, data=False))


def _match(dispatch: Instruction, history: list[Step]) -> tuple[int, int | None, bool] | None:
    """(table address, entry count or None, entries are addresses) for a known pattern."""
    last = len(history) - 1
    if (
        dispatch.op is Op.LDR
        and dispatch.rn == PC
        and dispatch.rm is not None
        and dispatch.shift == _TIMES_4
        and dispatch.pre
        and dispatch.up
    ):
        return dispatch.addr + 8, _bound(history, last, dispatch.rm), True
    if (
        dispatch.op is Op.ADD
        and dispatch.rn == PC
        and dispatch.rm is not None
        and dispatch.shift == _TIMES_4
    ):
        return dispatch.addr + 8, _bound(history, last, dispatch.rm), False
    if dispatch.op is Op.MOV and dispatch.rm is not None and dispatch.shift is None:
        return _loaded_from_table(dispatch.rm, history)
    return None


def _loaded_from_table(reg: int, history: list[Step]) -> tuple[int, int | None, bool] | None:
    """Match ``ldr reg, [base + index*4]`` where exactly one of base/index is a constant."""
    i = _definition(history, len(history) - 1, reg)
    if i is None:
        return None
    load = history[i].ins
    if load.op is not Op.LDR or load.target is not None or not load.pre or load.writeback:
        return None
    if load.rm is not None and load.shift is None:
        operands, consts, before = (load.rn, load.rm), history[i].consts, i - 1
    elif load.rm is None and load.imm == 0:
        j = _definition(history, i - 1, load.rn)
        if j is None:
            return None
        add = history[j].ins
        if add.op is not Op.ADD or add.rm is None or add.shift is not None:
            return None
        operands, consts, before = (add.rn, add.rm), history[j].consts, j - 1
    else:
        return None
    known = [r for r in operands if r in consts]
    if len(known) != 1 or operands[0] == operands[1]:
        return None
    index = operands[1] if known[0] == operands[0] else operands[0]
    k = _definition(history, before, index)
    if k is None:
        return None
    scale = history[k].ins
    if scale.op is not Op.MOV or scale.rm is None or scale.shift != _TIMES_4:
        return None
    return consts[known[0]], _bound(history, k - 1, scale.rm), True


def _definition(history: list[Step], start: int, reg: int) -> int | None:
    """Index of the latest instruction at or before ``start`` that writes ``reg``."""
    for i in range(start, -1, -1):
        if reg in written_registers(history[i].ins):
            return i
    return None


def _bound(history: list[Step], start: int, reg: int) -> int | None:
    """Entry count from a ``cmp reg, #N`` at or before ``start``, if ``reg`` is unchanged since."""
    for i in range(start, -1, -1):
        ins = history[i].ins
        if ins.op is Op.CMP and ins.rn == reg and ins.imm is not None:
            return ins.imm + 1
        if reg in written_registers(ins):
            return None
    return None


def _address_table(dispatch: Instruction, table: int, count: int, space: CodeSpace) -> JumpTable:
    mask = ~1 if dispatch.mode is Mode.THUMB else ~3
    targets = []
    for i in range(min(count, MAX_TABLE_ENTRIES)):
        row = table + 4 * i
        if not space.contains(row, 4):
            break
        targets.append(space.read32(row) & mask)
    return JumpTable(dispatch.addr, table, dispatch.mode, tuple(targets), data=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_tables.py -v && uv run ruff check src tests`
Expected: 7 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/tables.py tests/analysis/test_tables.py
git commit -m "feat: jump-table recognition"
```

---

### Task 6: Code discovery

**Files:**
- Create: `src/gbaport/analysis/discover.py`
- Modify: `tests/progkit.py` (add `explore_program`)
- Test: `tests/analysis/test_discover.py`

**Interfaces:**
- Consumes: `GameConfig`, `JumpTableOverride` (Task 1); `CodeSpace` (Task 2); `LR`, `MASK`, `PC`, `RegState`, `interwork_target` (Task 3); `Flow`, `FlowKind`, `classify` (Task 4); `JumpTable`, `Step`, `find_jump_table` (Task 5); decoders and `format_instruction` (Plan 1).
- Produces: `IRQ_VECTOR = 0x03007FFC`; `@dataclass(frozen=True) Issue(addr: int, kind: str, detail: str)` with kinds `undefined`, `unresolved_jump`, `unresolved_call`, `unbounded_table`, `outside_code`, `mode_conflict`, `misaligned`, `enters_data`, `overlap`; `@dataclass Exploration(instructions: dict[int, Instruction], successors: dict[int, tuple[int, ...]], entries: dict[int, Mode], entry_kinds: dict[int, str], calls: dict[int, tuple[int, ...]], jumps: dict[int, int], literals: dict[int, int], tables: list[JumpTable], issues: list[Issue])`; `explore(space, seeds: list[tuple[int, Mode, str]], config: GameConfig | None = None) -> Exploration`. Entry kinds: `seed`, `call`, `veneer`, `jump`, `irq`. `tests/progkit.py`: `explore_program(source, *, thumb=False, seeds=None, config=None, size=0x400) -> Exploration`.

- [ ] **Step 1: Extend the test helper and write the failing tests**

In `tests/progkit.py`, add to the import block (keep imports sorted with the existing ones):

```python
from gbaport.analysis.config import GameConfig
from gbaport.analysis.discover import Exploration, explore
from gbaport.isa.model import Instruction, Mode
```

(The existing `from gbaport.isa.model import Instruction` line is replaced by the combined one above.) Append at the end of the file:

```python
def explore_program(
    source: str,
    *,
    thumb: bool = False,
    seeds: list[tuple[int, Mode, str]] | None = None,
    config: GameConfig | None = None,
    size: int = 0x400,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    return explore(space, seeds or [(CODE_ADDR, mode, "seed")], config)
```

Create `tests/analysis/test_discover.py`:

```python
import random

from progkit import (
    ARM_TABLES,
    CODE_ADDR,
    CRT0,
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
    explore_program,
)
from romkit import build_rom

from gbaport.analysis.config import GameConfig, JumpTableOverride
from gbaport.analysis.discover import explore
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.tables import JumpTable
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage


def kinds(ex):
    return [(issue.addr, issue.kind) for issue in ex.issues]


def test_crt0_entries_calls_and_literals():
    ex = explore_program(CRT0)
    assert ex.entry_kinds == {
        0x080000C0: "seed",
        0x080000E4: "irq",
        0x080000E8: "call",
        0x080000F6: "call",
    }
    assert ex.entries[0x080000E4] is Mode.ARM
    assert ex.entries[0x080000E8] is Mode.THUMB
    assert ex.calls == {0x080000D4: (0x080000E8,), 0x080000EA: (0x080000F6,)}
    assert ex.literals == {0x080000DC: 4, 0x080000E0: 4}
    assert ex.issues == []


def test_crt0_successors():
    ex = explore_program(CRT0)
    assert ex.successors[0x080000D4] == (0x080000D8,)  # the call returns to the next instruction
    assert ex.successors[0x080000D8] == (0x080000C0,)  # b start
    assert ex.successors[0x080000F4] == ()  # pop {r1}; bx r1 returns
    assert ex.successors[0x080000F8] == (0x080000FC, 0x080000FA)  # beq done


def test_veneer_call_resolves_the_function_pointer():
    ex = explore_program(VENEER, thumb=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000D0: "veneer", 0x080000D4: "call"}
    assert ex.calls == {0x080000C4: (0x080000D4,)}
    assert ex.issues == []


def test_thumb_jump_table():
    ex = explore_program(THUMB_TABLE, thumb=True)
    targets = (0x080000E0, 0x080000E2, 0x080000E4)
    assert ex.tables == [JumpTable(0x080000CC, 0x080000D4, Mode.THUMB, targets, data=True)]
    assert ex.successors[0x080000CC] == targets
    assert ex.successors[0x080000C2] == (0x080000E6, 0x080000C4)
    assert ex.literals == {0x080000D0: 4, 0x080000D4: 4, 0x080000D8: 4, 0x080000DC: 4}
    assert set(ex.instructions) >= {0x080000E0, 0x080000E2, 0x080000E4, 0x080000E6}
    assert ex.issues == []


def test_arm_jump_tables():
    ex = explore_program(ARM_TABLES)
    assert ex.tables == [
        JumpTable(0x080000C4, 0x080000CC, Mode.ARM, (0x080000D4, 0x080000D8), data=True),
        JumpTable(0x080000E0, 0x080000E8, Mode.ARM, (0x080000E8, 0x080000EC), data=False),
    ]
    assert ex.successors[0x080000C4] == (0x080000D4, 0x080000D8, 0x080000C8)
    assert ex.successors[0x080000E0] == (0x080000E8, 0x080000EC, 0x080000E4)
    assert ex.literals == {0x080000CC: 4, 0x080000D0: 4}
    assert ex.issues == []


def test_unknown_indirect_jump_is_reported():
    ex = explore_program("ldr r0, [r1]\nbx r0", thumb=True)
    assert kinds(ex) == [(0x080000C2, "unresolved_jump")]


def test_undefined_instruction_is_reported():
    ex = explore_program("movs r0, #1\n.hword 0xde00", thumb=True)
    assert kinds(ex) == [(0x080000C2, "undefined")]


def test_irq_handler_in_ram_becomes_a_hint():
    ex = explore_program(IRQ_IN_RAM)
    assert kinds(ex) == [(0x080000C8, "outside_code")]
    assert "irq" in ex.issues[0].detail and "[[ram_code]]" in ex.issues[0].detail


def test_unknown_call_through_the_link_idiom():
    ex = explore_program("mov lr, pc\nbx r2\nbx lr")
    assert kinds(ex) == [(0x080000C4, "unresolved_call")]
    assert ex.successors[0x080000C4] == (0x080000C8,)


def test_known_jump_leaves_the_function():
    ex = explore_program(KNOWN_JUMP, thumb=True)
    assert ex.entry_kinds[0x080000C8] == "jump"
    assert ex.jumps == {0x080000C2: 0x080000C8}
    assert ex.issues == []


def test_mode_conflict():
    seeds = [(0x080000C0, Mode.ARM, "seed"), (0x080000C4, Mode.THUMB, "seed")]
    ex = explore_program("b th\n.thumb\nth: bx lr", seeds=seeds)
    assert kinds(ex) == [(0x080000C4, "mode_conflict")]


def test_data_range_stops_the_walk():
    config = GameConfig(data=((0x080000C8, 0x080000CC),))
    ex = explore_program("b skip\n.word 0\nskip: bx lr", config=config)
    assert kinds(ex) == [(0x080000C8, "enters_data")]


def test_unbounded_table_and_its_override():
    ex = explore_program(UNBOUNDED_TABLE, thumb=True)
    assert kinds(ex) == [(0x080000C8, "unbounded_table")]
    config = GameConfig(jump_tables=(JumpTableOverride(0x080000C8, 0x080000D0, 2),))
    ex = explore_program(UNBOUNDED_TABLE, thumb=True, config=config)
    assert ex.issues == []
    assert ex.successors[0x080000C8] == (0x080000D8, 0x080000DA)


def test_loops_and_recursion_terminate():
    ex = explore_program(RECURSION, thumb=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000C6: "call"}
    assert ex.calls == {0x080000C0: (0x080000C6,), 0x080000C6: (0x080000C0,)}
    assert ex.successors[0x080000CC] == (0x080000CC,)  # spin: b spin


def test_garbage_never_crashes():
    rng = random.Random(7)
    for mode in (Mode.ARM, Mode.THUMB):
        for _ in range(25):
            data = bytearray(build_rom(size=0x1000))
            data[0xC0:] = rng.randbytes(0x1000 - 0xC0)
            explore(CodeSpace(RomImage(bytes(data))), [(CODE_ADDR, mode, "seed")])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.discover'` (raised while importing `progkit`)

- [ ] **Step 3: Write the explorer**

Create `src/gbaport/analysis/discover.py`:

```python
"""Recursive-descent code discovery.

From the seed entry points, walk instructions linearly and follow branches,
calls, jump tables and indirect transfers whose target is a known constant.
Each linear walk tracks register constants (reset at the start of every walk),
so ``ldr r0, =func; bx r0`` style transfers resolve. Anything the walk cannot
follow becomes an ``Issue``; nothing in the ROM can make it raise.
"""

from collections import deque
from dataclasses import dataclass, field

from gbaport.analysis.config import GameConfig
from gbaport.analysis.effects import LR, MASK, PC, RegState, interwork_target
from gbaport.analysis.flow import Flow, FlowKind, classify
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.tables import JumpTable, Step, find_jump_table
from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Cond, Instruction, Mode, Op
from gbaport.isa.thumb import decode_thumb

IRQ_VECTOR = 0x03007FFC  # the BIOS enters the IRQ handler stored here, in ARM state
HISTORY_LIMIT = 16
_LITERAL_SIZES = {Op.LDR: 4, Op.LDRH: 2, Op.LDRSH: 2, Op.LDRB: 1, Op.LDRSB: 1}


@dataclass(frozen=True)
class Issue:
    addr: int
    kind: str
    detail: str


@dataclass
class Exploration:
    instructions: dict[int, Instruction] = field(default_factory=dict)
    # Successors inside the function for every decoded instruction (fall-through included).
    successors: dict[int, tuple[int, ...]] = field(default_factory=dict)
    entries: dict[int, Mode] = field(default_factory=dict)
    entry_kinds: dict[int, str] = field(default_factory=dict)
    calls: dict[int, tuple[int, ...]] = field(default_factory=dict)  # call site -> callees
    jumps: dict[int, int] = field(default_factory=dict)  # jump site -> entry it leaves for
    literals: dict[int, int] = field(default_factory=dict)  # address -> size
    tables: list[JumpTable] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def explore(
    space: CodeSpace, seeds: list[tuple[int, Mode, str]], config: GameConfig | None = None
) -> Exploration:
    """Discover the code reachable from ``seeds`` of (address, mode, entry kind)."""
    explorer = _Explorer(space, config or GameConfig())
    for addr, mode, kind in seeds:
        explorer.add_entry(addr, mode, kind, origin=addr)
    explorer.drain()
    return explorer.ex


class _Explorer:
    def __init__(self, space: CodeSpace, config: GameConfig) -> None:
        self.space = space
        self.data = config.data
        self.overrides = {table.at: table for table in config.jump_tables}
        self.ex = Exploration()
        self.work: deque[tuple[int, Mode]] = deque()

    def drain(self) -> None:
        while self.work:
            self.walk(*self.work.popleft())

    def issue(self, addr: int, kind: str, detail: str) -> None:
        self.ex.issues.append(Issue(addr, kind, detail))

    def add_entry(self, addr: int, mode: Mode, kind: str, origin: int) -> int | None:
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.issue(
                origin,
                "outside_code",
                f"{kind} target {addr:#010x} is not in analysable code; "
                "add a [[ram_code]] entry if the game copies code there",
            )
            return None
        if addr not in self.ex.entries:
            self.ex.entries[addr] = mode
            self.ex.entry_kinds[addr] = kind
            self.work.append((addr, mode))
        return addr

    def add_branch(self, addr: int, mode: Mode, origin: int) -> int | None:
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.issue(origin, "outside_code", f"branch target {addr:#010x} is outside the ROM")
            return None
        self.work.append((addr, mode))
        return addr

    def walk(self, addr: int, mode: Mode) -> None:
        state = RegState()
        history: list[Step] = []
        prev: Instruction | None = None
        while True:
            ins = self._take(addr, mode)
            if ins is None:
                return
            self._note_literal(ins)
            self._note_irq_vector(ins, state)
            flow = classify(ins, state, prev, self.space)
            successors, keep_going = self._follow(ins, flow, state, history)
            self.ex.successors[addr] = tuple(dict.fromkeys(successors))
            if not keep_going:
                return
            history.append(Step(ins, dict(state.consts)))
            del history[:-HISTORY_LIMIT]
            state.step(ins, self.space)
            if flow.kind is FlowKind.CALL:
                state.forget_call_clobbered()
            prev = ins
            addr += ins.size

    def _take(self, addr: int, mode: Mode) -> Instruction | None:
        """Decode and record the instruction at ``addr``, or report why the walk stops."""
        known = self.ex.instructions.get(addr)
        if known is not None:
            if known.mode is not mode:
                self.issue(
                    addr,
                    "mode_conflict",
                    f"reached as {mode.value} code but already decoded as {known.mode.value}",
                )
            return None
        if addr % (4 if mode is Mode.ARM else 2):
            self.issue(addr, "misaligned", f"{mode.value} code at an unaligned address")
            return None
        if self._is_data(addr):
            self.issue(addr, "enters_data", "walked into a [code] data range or a literal pool")
            return None
        ins = self._decode(addr, mode)
        if ins is None:
            self.issue(addr, "outside_code", "walked off the end of analysable code")
            return None
        if self._overlaps(ins):
            self.issue(addr, "overlap", "instruction overlaps one decoded earlier")
            return None
        self.ex.instructions[addr] = ins
        return ins

    def _decode(self, addr: int, mode: Mode) -> Instruction | None:
        if mode is Mode.ARM:
            if not self.space.contains(addr, 4):
                return None
            return decode_arm(self.space.read32(addr), addr)
        if not self.space.contains(addr, 2):
            return None
        following = self.space.read16(addr + 2) if self.space.contains(addr + 2, 2) else None
        return decode_thumb(self.space.read16(addr), addr, following)

    def _is_data(self, addr: int) -> bool:
        if any(start <= addr < end for start, end in self.data):
            return True
        return any(self.ex.literals.get(addr - back, 0) > back for back in range(4))

    def _overlaps(self, ins: Instruction) -> bool:
        inside = any(a in self.ex.instructions for a in range(ins.addr + 2, ins.addr + ins.size, 2))
        before = self.ex.instructions.get(ins.addr - 2)
        return inside or (before is not None and before.size == 4)

    def _note_literal(self, ins: Instruction) -> None:
        size = _LITERAL_SIZES.get(ins.op)
        if size is not None and ins.rn == PC and ins.target is not None:
            self.ex.literals.setdefault(self.space.canonical(ins.target), size)

    def _note_irq_vector(self, ins: Instruction, state: RegState) -> None:
        """``str rV, [rA]`` with rA == 0x03007FFC installs rV as the IRQ handler."""
        if ins.op is not Op.STR or ins.rm is not None or not ins.pre or ins.cond is not Cond.AL:
            return
        base, value = state.value(ins.rn, ins), state.value(ins.rd, ins)
        if base is None or value is None:
            return
        offset = ins.imm if ins.up else -ins.imm
        if (base + offset) & MASK == IRQ_VECTOR:
            self.add_entry(value & ~3, Mode.ARM, "irq", origin=ins.addr)

    def _follow(
        self, ins: Instruction, flow: Flow, state: RegState, history: list[Step]
    ) -> tuple[tuple[int, ...], bool]:
        """Successors of ``ins`` inside its function, and whether the walk goes on."""
        after = (ins.addr + ins.size,)
        kind = flow.kind
        if kind is FlowKind.NEXT:
            return after, True
        if kind is FlowKind.CALL:
            self._call(ins, flow, state)
            return after, True
        if kind is FlowKind.BRANCH:
            target = self.add_branch(*flow.target, origin=ins.addr)
            here = () if target is None else (target,)
        elif kind is FlowKind.JUMP:
            entry = self.add_entry(*flow.target, "jump", origin=ins.addr)
            if entry is not None:
                self.ex.jumps[ins.addr] = entry
            here = ()
        elif kind is FlowKind.INDIRECT:
            here = self._indirect(ins, history)
        elif kind is FlowKind.RETURN:
            here = ()
        else:  # STOP
            if ins.op is Op.UNDEFINED:
                self.issue(
                    ins.addr,
                    "undefined",
                    f"undefined instruction {format_instruction(ins)} (data, or the wrong mode?)",
                )
            return (), False
        if flow.falls_through:
            return here + after, True
        return here, False

    def _call(self, ins: Instruction, flow: Flow, state: RegState) -> None:
        if flow.target is None:
            self.issue(ins.addr, "unresolved_call", f"{format_instruction(ins)}: target unknown")
            return
        target, mode = flow.target
        register = self._veneer_register(target, mode)
        if register is None:
            callee = self.add_entry(target, mode, "call", origin=ins.addr)
        else:
            self.add_entry(target, mode, "veneer", origin=ins.addr)
            callee = self._call_through(register, ins, state)
        if callee is not None:
            self.ex.calls[ins.addr] = (callee,)

    def _veneer_register(self, target: int, mode: Mode) -> int | None:
        """N if ``target`` is a ``bx rN`` call veneer (like agbcc's ``_call_via_rN``)."""
        ins = self._decode(self.space.canonical(target), mode)
        if ins is not None and ins.op is Op.BX and ins.cond is Cond.AL and ins.rm not in (LR, PC):
            return ins.rm
        return None

    def _call_through(self, register: int, ins: Instruction, state: RegState) -> int | None:
        value = state.value(register, ins)
        if value is None:
            self.issue(
                ins.addr,
                "unresolved_call",
                f"call through a bx r{register} veneer with r{register} unknown",
            )
            return None
        target, mode = interwork_target(value)
        return self.add_entry(target, mode, "call", origin=ins.addr)

    def _indirect(self, ins: Instruction, history: list[Step]) -> tuple[int, ...]:
        match = find_jump_table(ins, history, self.space, self.overrides)
        if match is None:
            if self.ex.entry_kinds.get(ins.addr) != "veneer":
                self.issue(
                    ins.addr,
                    "unresolved_jump",
                    f"{format_instruction(ins)}: target unknown; "
                    "list possible targets as [code] entries or thumb_entries",
                )
            return ()
        if match.table is None:
            self.issue(ins.addr, "unbounded_table", match.problem)
            return ()
        table = match.table
        self.ex.tables.append(table)
        if table.data:
            for i in range(len(table.targets)):
                self.ex.literals.setdefault(table.table + 4 * i, 4)
        targets = (self.add_branch(t, table.mode, origin=ins.addr) for t in table.targets)
        return tuple(t for t in targets if t is not None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_discover.py -v && uv run ruff check src tests`
Expected: 15 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/discover.py tests/progkit.py tests/analysis/test_discover.py
git commit -m "feat: recursive-descent code discovery"
```

---

### Task 7: Blocks and functions

**Files:**
- Create: `src/gbaport/analysis/cfg.py`
- Test: `tests/analysis/test_cfg.py`

**Interfaces:**
- Consumes: `Exploration` (Task 6); `explore_program`, `CRT0`, `ARM_TABLES`, `TAIL_CALLS`, `KNOWN_JUMP` (`progkit`).
- Produces: `@dataclass(frozen=True) Block(start: int, mode: Mode, instructions: tuple[Instruction, ...], successors: tuple[int, ...])` with property `end -> int`; `@dataclass(frozen=True) Function(entry: int, mode: Mode, kind: str, blocks: tuple[int, ...], calls: tuple[int, ...], tail_calls: tuple[int, ...])`; `@dataclass(frozen=True) Program(blocks: dict[int, Block], functions: dict[int, Function])`; `build_program(ex: Exploration) -> Program`.

- [ ] **Step 1: Write the failing tests**

Create `tests/analysis/test_cfg.py`:

```python
from progkit import ARM_TABLES, CRT0, KNOWN_JUMP, TAIL_CALLS, explore_program

from gbaport.analysis.cfg import build_program
from gbaport.isa.model import Mode


def test_crt0_blocks():
    program = build_program(explore_program(CRT0))
    assert sorted(program.blocks) == [
        0x080000C0, 0x080000E4, 0x080000E8, 0x080000F6, 0x080000FA, 0x080000FC,
    ]
    start = program.blocks[0x080000C0]
    assert (start.end, start.successors, len(start.instructions)) == (0x080000DC, (0x080000C0,), 7)
    assert program.blocks[0x080000E8].end == 0x080000F6
    assert program.blocks[0x080000F6].successors == (0x080000FC, 0x080000FA)
    assert program.blocks[0x080000FA].successors == (0x080000FC,)


def test_crt0_functions():
    program = build_program(explore_program(CRT0))
    summary = {
        entry: (f.kind, f.mode, f.blocks, f.calls) for entry, f in program.functions.items()
    }
    assert summary == {
        0x080000C0: ("seed", Mode.ARM, (0x080000C0,), (0x080000E8,)),
        0x080000E4: ("irq", Mode.ARM, (0x080000E4,), ()),
        0x080000E8: ("call", Mode.THUMB, (0x080000E8,), (0x080000F6,)),
        0x080000F6: ("call", Mode.THUMB, (0x080000F6, 0x080000FA, 0x080000FC), ()),
    }


def test_jump_table_blocks_belong_to_the_function():
    program = build_program(explore_program(ARM_TABLES))
    assert program.blocks[0x080000C0].successors == (0x080000D4, 0x080000D8, 0x080000C8)
    assert program.functions[0x080000C0].blocks == (
        0x080000C0, 0x080000C8, 0x080000D4, 0x080000D8, 0x080000DC,
        0x080000E4, 0x080000E8, 0x080000EC, 0x080000F0,
    )


def test_branch_into_another_function_is_a_tail_call():
    seeds = [(0x080000C0, Mode.THUMB, "seed"), (0x080000CA, Mode.THUMB, "seed")]
    program = build_program(explore_program(TAIL_CALLS, thumb=True, seeds=seeds))
    f = program.functions[0x080000CA]
    assert (f.blocks, f.tail_calls) == ((0x080000CA,), (0x080000CC,))
    assert program.functions[0x080000C0].calls == (0x080000CC,)


def test_known_jump_is_a_tail_call():
    program = build_program(explore_program(KNOWN_JUMP, thumb=True))
    assert program.functions[0x080000C0].tail_calls == (0x080000C8,)
    assert program.functions[0x080000C8].kind == "jump"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_cfg.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.cfg'`

- [ ] **Step 3: Write the CFG builder**

Create `src/gbaport/analysis/cfg.py`:

```python
"""Group discovered instructions into basic blocks and functions.

A block may belong to several functions (shared tails); the recompiler emits
it in each. A successor that is another function's entry is a tail call, not a
block of the function.
"""

from dataclasses import dataclass

from gbaport.analysis.discover import Exploration
from gbaport.isa.model import Instruction, Mode


@dataclass(frozen=True)
class Block:
    start: int
    mode: Mode
    instructions: tuple[Instruction, ...]
    successors: tuple[int, ...]  # block starts control may reach next, inside the function

    @property
    def end(self) -> int:
        last = self.instructions[-1]
        return last.addr + last.size


@dataclass(frozen=True)
class Function:
    entry: int
    mode: Mode
    kind: str  # how it was found: seed, call, veneer, jump or irq
    blocks: tuple[int, ...]
    calls: tuple[int, ...]
    tail_calls: tuple[int, ...]


@dataclass(frozen=True)
class Program:
    blocks: dict[int, Block]
    functions: dict[int, Function]


def build_program(ex: Exploration) -> Program:
    blocks = _blocks(ex)
    functions = {
        entry: _function(ex, blocks, entry)
        for entry in sorted(ex.entries)
        if entry in blocks and blocks[entry].mode is ex.entries[entry]
    }
    return Program(blocks, functions)


def _leaders(ex: Exploration) -> set[int]:
    leaders = set(ex.entries)
    for addr, successors in ex.successors.items():
        after = addr + ex.instructions[addr].size
        if successors != (after,):
            leaders.update(successors)
            leaders.add(after)  # whatever follows a control transfer starts a new block
    return leaders & set(ex.instructions)


def _blocks(ex: Exploration) -> dict[int, Block]:
    leaders = _leaders(ex)
    blocks = {}
    for start in sorted(leaders):
        run, addr = [], start
        while True:
            ins = ex.instructions[addr]
            run.append(ins)
            after = addr + ins.size
            nxt = ex.instructions.get(after)
            if (
                ex.successors.get(addr) != (after,)
                or after in leaders
                or nxt is None
                or nxt.mode is not ins.mode
            ):
                break
            addr = after
        successors = tuple(
            s
            for s in ex.successors.get(addr, ())
            if s in leaders and ex.instructions[s].mode is ins.mode
        )
        blocks[start] = Block(start, run[0].mode, tuple(run), successors)
    return blocks


def _function(ex: Exploration, blocks: dict[int, Block], entry: int) -> Function:
    seen: set[int] = set()
    tails: set[int] = set()
    todo = [entry]
    while todo:
        start = todo.pop()
        if start in seen:
            continue
        seen.add(start)
        for successor in blocks[start].successors:
            if successor != entry and successor in ex.entries:
                tails.add(successor)
            elif successor in blocks:
                todo.append(successor)
    addrs = [ins.addr for start in seen for ins in blocks[start].instructions]
    calls = {callee for addr in addrs for callee in ex.calls.get(addr, ())}
    tails |= {ex.jumps[addr] for addr in addrs if addr in ex.jumps}
    return Function(
        entry=entry,
        mode=ex.entries[entry],
        kind=ex.entry_kinds[entry],
        blocks=tuple(sorted(seen)),
        calls=tuple(sorted(calls)),
        tail_calls=tuple(sorted(tails)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_cfg.py -v && uv run ruff check src tests`
Expected: 5 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/cfg.py tests/analysis/test_cfg.py
git commit -m "feat: basic blocks and functions"
```

---

### Task 8: `analyze_rom`, coverage, JSON and `gbaport analyze`

**Files:**
- Create: `src/gbaport/analysis/analyze.py`
- Modify: `src/gbaport/cli.py` (register `analyze`), `README.md` (Commands)
- Test: `tests/analysis/test_analyze.py`, `tests/test_analyze_cli.py`

**Interfaces:**
- Consumes: everything above; `RomImage`, `HEADER_SIZE`, `ROM_BASE` (`gbaport.rom.image`); `inspect_rom`, `RomInfo` (`gbaport.rom.info`); `parse_header` (`gbaport.rom.header`); `main` (`gbaport.cli`); `assemble` (`ksasm`); `program_rom`, `CRT0` (`progkit`).
- Produces: `FORMAT = "gbaport-analysis/1"`; `@dataclass(frozen=True) Coverage(rom_bytes, code_bytes, literal_bytes, data_bytes)` with `classified_percent`; `@dataclass(frozen=True) Analysis(info: RomInfo, exploration: Exploration, program: Program, coverage: Coverage)`; `analyze_rom(rom, config: GameConfig | None = None) -> Analysis`; `sorted_issues(ex) -> list[Issue]`; `analysis_to_dict(analysis) -> dict`; `summary_lines(analysis) -> list[str]`. CLI: `gbaport analyze ROM [--config PATH] [--out PATH] [--issues N]`.

Note: trace import (recording executed addresses with a dev-only emulator to seed discovery) is deliberately left out of Plan 2; it needs a real dump to design against and becomes its own plan once `gbaport analyze` shows what static analysis misses.

- [ ] **Step 1: Write the failing tests**

Create `tests/analysis/test_analyze.py`:

```python
import json

import pytest
from ksasm import assemble
from progkit import CRT0, program_rom

from gbaport.analysis.analyze import Coverage, analysis_to_dict, analyze_rom, summary_lines
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.isa.model import Mode


def test_analyze_crt0_rom():
    analysis = analyze_rom(program_rom(CRT0))
    assert sorted(analysis.program.functions) == [0x080000C0, 0x080000E4, 0x080000E8, 0x080000F6]
    assert analysis.coverage == Coverage(
        rom_bytes=0x400, code_bytes=54, literal_bytes=8, data_bytes=0xC0
    )


def test_summary_lines():
    lines = summary_lines(analyze_rom(program_rom(CRT0)))
    assert lines[0] == "functions    4 (0 veneers)"
    assert "classified   24.8% of 1024 bytes" in lines
    assert lines[-1] == "issues       0 (none)"


def test_json_document():
    doc = analysis_to_dict(analyze_rom(program_rom(CRT0)))
    assert doc["format"] == "gbaport-analysis/1"
    assert doc["rom"]["game_code"] == "ATST"
    assert doc["functions"][0] == {
        "entry": "0x080000c0",
        "mode": "arm",
        "kind": "seed",
        "blocks": ["0x080000c0"],
        "calls": ["0x080000e8"],
        "tail_calls": [],
    }
    assert doc["blocks"][0] == {
        "start": "0x080000c0",
        "end": "0x080000dc",
        "mode": "arm",
        "successors": ["0x080000c0"],
    }
    assert doc["literals"] == [
        {"addr": "0x080000dc", "size": 4},
        {"addr": "0x080000e0", "size": 4},
    ]
    assert doc["coverage"] == {
        "rom_bytes": 1024, "code_bytes": 54, "literal_bytes": 8, "data_bytes": 192,
    }
    assert json.loads(json.dumps(doc)) == doc


def test_config_entries_and_ram_code():
    patches = {
        0x200: assemble("bx lr", thumb=True, addr=0x08000200),
        0x300: assemble("bx lr", addr=0x03000000),
    }
    rom = program_rom("bx lr", patches=patches)
    config = GameConfig(
        thumb_entries=(0x08000200,),
        ram_code=(RamCode(0x08000300, 0x03000000, 4, Mode.ARM),),
    )
    analysis = analyze_rom(rom, config)
    assert analysis.program.functions[0x08000200].mode is Mode.THUMB
    assert analysis.program.functions[0x03000000].mode is Mode.ARM
    assert analysis.coverage.code_bytes == 4 + 2 + 4


def test_sha1_mismatch_is_rejected():
    with pytest.raises(ConfigError, match="sha1"):
        analyze_rom(program_rom("bx lr"), GameConfig(rom_sha1="0" * 40))


def test_data_range_outside_rom_is_rejected():
    config = GameConfig(data=((0x08100000, 0x08100010),))
    with pytest.raises(ConfigError, match="outside the ROM"):
        analyze_rom(program_rom("bx lr"), config)


def test_data_ranges_count_as_data():
    config = GameConfig(data=((0x08000200, 0x08000300),))
    assert analyze_rom(program_rom("bx lr"), config).coverage.data_bytes == 0xC0 + 0x100
```

Create `tests/test_analyze_cli.py`:

```python
import json

from ksasm import assemble
from progkit import CRT0, program_rom

from gbaport.cli import main


def write(tmp_path, rom):
    path = tmp_path / "game.gba"
    path.write_bytes(rom.data)
    return path


def test_prints_summary_and_writes_json(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "analysis.json"
    assert main(["analyze", str(write(tmp_path, program_rom(CRT0))), "--out", str(out)]) == 0
    assert "functions    4 (0 veneers)" in capsys.readouterr().out
    assert json.loads(out.read_text())["format"] == "gbaport-analysis/1"


def test_lists_issues(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["analyze", str(write(tmp_path, program_rom("ldr r0, [r1]\nbx r0")))]) == 0
    assert "080000c4  unresolved_jump" in capsys.readouterr().out


def test_uses_games_config_by_default(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = program_rom("bx lr", patches={0x200: assemble("bx lr", thumb=True, addr=0x08000200)})
    config = tmp_path / "games" / "ATST" / "game.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[code]\nthumb_entries = [0x08000200]\n")
    assert main(["analyze", str(write(tmp_path, rom))]) == 0
    out = capsys.readouterr().out
    assert "game.toml" in out and "functions    2 (0 veneers)" in out


def test_bad_config_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bad = tmp_path / "bad.toml"
    bad.write_text("[code]\nbogus = 1\n")
    args = ["analyze", str(write(tmp_path, program_rom("bx lr"))), "--config", str(bad)]
    assert main(args) == 1
    assert "unknown key(s): bogus" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_analyze.py tests/test_analyze_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.analyze'`

- [ ] **Step 3: Write `analyze.py`**

Create `src/gbaport/analysis/analyze.py`:

```python
"""Whole-ROM analysis (discovery + blocks + coverage) and its JSON and text views."""

from collections import Counter
from dataclasses import dataclass

from gbaport.analysis.cfg import Program, build_program
from gbaport.analysis.config import ConfigError, GameConfig
from gbaport.analysis.discover import Exploration, Issue, explore
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.rom.image import HEADER_SIZE, ROM_BASE, RomImage
from gbaport.rom.info import RomInfo, inspect_rom

FORMAT = "gbaport-analysis/1"


@dataclass(frozen=True)
class Coverage:
    rom_bytes: int
    code_bytes: int
    literal_bytes: int
    data_bytes: int  # the cartridge header plus [code] data ranges

    @property
    def classified_percent(self) -> float:
        known = self.code_bytes + self.literal_bytes + self.data_bytes
        return 100.0 * known / self.rom_bytes


@dataclass(frozen=True)
class Analysis:
    info: RomInfo
    exploration: Exploration
    program: Program
    coverage: Coverage


def analyze_rom(rom: RomImage, config: GameConfig | None = None) -> Analysis:
    config = config or GameConfig()
    info = inspect_rom(rom)
    if config.rom_sha1 is not None and config.rom_sha1 != info.sha1:
        raise ConfigError(
            f"game.toml is for ROM sha1 {config.rom_sha1}, but this ROM is {info.sha1}"
        )
    space = CodeSpace(rom, config.ram_code)
    for start, end in config.data:
        if not rom.contains(space.canonical(start), end - start):
            raise ConfigError(f"data range [{start:#x}, {end:#x}] is outside the ROM")
    seeds = [(info.header.entry_point or ROM_BASE, Mode.ARM, "seed")]
    seeds += [(addr, Mode.ARM, "seed") for addr in config.entries]
    seeds += [(addr, Mode.THUMB, "seed") for addr in config.thumb_entries]
    seeds += [(blob.ram, blob.mode, "seed") for blob in config.ram_code]
    exploration = explore(space, seeds, config)
    coverage = _coverage(space, exploration, config)
    return Analysis(info, exploration, build_program(exploration), coverage)


def sorted_issues(ex: Exploration) -> list[Issue]:
    return sorted(ex.issues, key=lambda issue: (issue.addr, issue.kind))


def analysis_to_dict(analysis: Analysis) -> dict:
    ex, program, coverage = analysis.exploration, analysis.program, analysis.coverage
    header = analysis.info.header
    return {
        "format": FORMAT,
        "rom": {"title": header.title, "game_code": header.game_code, "sha1": analysis.info.sha1},
        "functions": [
            {
                "entry": _hex(f.entry),
                "mode": f.mode.value,
                "kind": f.kind,
                "blocks": [_hex(b) for b in f.blocks],
                "calls": [_hex(c) for c in f.calls],
                "tail_calls": [_hex(t) for t in f.tail_calls],
            }
            for f in sorted(program.functions.values(), key=lambda f: f.entry)
        ],
        "blocks": [
            {
                "start": _hex(b.start),
                "end": _hex(b.end),
                "mode": b.mode.value,
                "successors": [_hex(s) for s in b.successors],
            }
            for b in sorted(program.blocks.values(), key=lambda b: b.start)
        ],
        "jump_tables": [
            {
                "dispatch": _hex(t.dispatch),
                "table": _hex(t.table),
                "mode": t.mode.value,
                "data": t.data,
                "targets": [_hex(target) for target in t.targets],
            }
            for t in ex.tables
        ],
        "literals": [{"addr": _hex(a), "size": size} for a, size in sorted(ex.literals.items())],
        "issues": [
            {"addr": _hex(i.addr), "kind": i.kind, "detail": i.detail} for i in sorted_issues(ex)
        ],
        "coverage": {
            "rom_bytes": coverage.rom_bytes,
            "code_bytes": coverage.code_bytes,
            "literal_bytes": coverage.literal_bytes,
            "data_bytes": coverage.data_bytes,
        },
    }


def summary_lines(analysis: Analysis) -> list[str]:
    ex, program, coverage = analysis.exploration, analysis.program, analysis.coverage
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
    counts = Counter(issue.kind for issue in ex.issues)
    breakdown = ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items())) or "none"
    rows = [
        ("functions", f"{len(program.functions)} ({veneers} veneers)"),
        ("blocks", str(len(program.blocks))),
        ("jump tables", str(len(ex.tables))),
        ("code", f"{coverage.code_bytes} bytes"),
        ("literals", f"{coverage.literal_bytes} bytes"),
        ("data", f"{coverage.data_bytes} bytes"),
        ("classified", f"{coverage.classified_percent:.1f}% of {coverage.rom_bytes} bytes"),
        ("issues", f"{len(ex.issues)} ({breakdown})"),
    ]
    return [f"{label:<13}{value}" for label, value in rows]


def _hex(value: int) -> str:
    return f"{value:#010x}"


def _coverage(space: CodeSpace, ex: Exploration, config: GameConfig) -> Coverage:
    kinds = bytearray(len(space.rom.data))  # 0 unknown, 1 code, 2 literal, 3 data
    for ins in ex.instructions.values():
        _mark(kinds, space.rom_offset(ins.addr, ins.size), ins.size, 1)
    for addr, size in ex.literals.items():
        _mark(kinds, space.rom_offset(addr, size), size, 2)
    for start, end in [(ROM_BASE, ROM_BASE + HEADER_SIZE), *config.data]:
        offset = space.rom_offset(start, end - start)
        if offset is not None:
            stop = offset + (end - start)
            kinds[offset:stop] = kinds[offset:stop].replace(b"\x00", b"\x03")
    return Coverage(len(kinds), kinds.count(1), kinds.count(2), kinds.count(3))


def _mark(kinds: bytearray, offset: int | None, size: int, kind: int) -> None:
    if offset is None:
        return
    for i in range(offset, offset + size):
        if kinds[i] == 0:
            kinds[i] = kind
```

- [ ] **Step 4: Register the CLI command**

Modify `src/gbaport/cli.py`. Add to the imports (keep them sorted):

```python
from pathlib import Path

from gbaport.analysis.analyze import analysis_to_dict, analyze_rom, sorted_issues, summary_lines
from gbaport.analysis.config import GameConfig, default_config_path, load_config
from gbaport.rom.header import parse_header
```

In `build_parser`, after `_add_disasm_command(commands)` add:

```python
    _add_analyze_command(commands)
```

Add after `_run_disasm`:

```python
def _add_analyze_command(commands) -> None:
    analyze = commands.add_parser("analyze", help="discover functions, blocks and jump tables")
    analyze.add_argument("rom", help="path to a .gba file")
    analyze.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    analyze.add_argument("--out", help="write the full analysis as JSON to this file")
    analyze.add_argument("--issues", type=int, default=20, help="issues to list (default 20)")
    analyze.set_defaults(handler=_run_analyze)


def _run_analyze(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    config_path = args.config or default_config_path(parse_header(rom).game_code)
    config = load_config(config_path) if config_path else GameConfig()
    analysis = analyze_rom(rom, config)
    if config_path:
        print(f"{'config':<13}{config_path}")
    for line in summary_lines(analysis):
        print(line)
    for issue in sorted_issues(analysis.exploration)[: args.issues]:
        print(f"  {issue.addr:08x}  {issue.kind:<16}  {issue.detail}")
    if args.out:
        document = json.dumps(analysis_to_dict(analysis), indent=1)
        Path(args.out).write_text(document, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0
```

Append to the `## Commands` section of `README.md`:

```markdown
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: every test passes (268 from Plan 1 + 108 new = 376); ruff clean.

- [ ] **Step 6: Smoke-test on a real dump (manual)**

If a dump exists in `roms/`, run `uv run gbaport analyze roms/<game>.gba --out build/analysis.json` and record in the ledger: function count, classified percentage and the issue breakdown. These numbers are the input for the trace-import plan and for Plan 3.

- [ ] **Step 7: Commit**

```bash
git add src/gbaport/analysis/analyze.py src/gbaport/cli.py README.md tests/analysis/test_analyze.py tests/test_analyze_cli.py
git commit -m "feat: gbaport analyze with coverage and JSON output"
```

---

## Done criteria for Plan 2

- `uv run pytest` passes and `uv run ruff check src tests` is clean.
- On the synthetic programs, discovery finds exactly the expected entries, blocks, jump tables and literals, with zero issues where none are expected.
- `gbaport analyze` prints a summary, lists issues with actionable hints and writes `analysis.json`.
- On a real dump (when available): the run completes and the classified percentage plus the issue breakdown are recorded for the next plans.
