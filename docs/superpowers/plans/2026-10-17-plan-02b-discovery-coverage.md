# Plan 2b: Discovery Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise how much of a real game `gbaport analyze` finds. It gains three things: a pointer scan for callbacks, automatic detection of code the game copies into RAM, and execution traces recorded from mGBA through its GDB server and imported back into discovery.

**Architecture:**
- **Pointer scan.** A new `analysis/pointers.py` turns ROM words that point at function prologues into candidate entries. Discovery walks those only after all trusted code is decoded.
- **RAM-copy detection.** Discovery records DMA and CpuSet copies whose operands are constants, and the code addresses it wanted but could not reach. `analyze_rom` adopts a copy as a RAM overlay when it covers such an address, then runs again.
- **Traces.** `analysis/traces.py` defines a line-based trace file (`site target mode`). Discovery uses traces to resolve indirect sites it cannot resolve itself.
- **Recording.** A new `tracing` package holds a small GDB client and a session. The session puts breakpoints on every unresolved indirect site, steps over each hit, records where it went, and re-analyses while the game runs, so breakpoints follow newly reachable code.

**Tech Stack:** Python 3.13 standard library only (`socket`, `array`, `tomllib`), plus pytest, ruff and Keystone for tests, as in Plans 1–2. mGBA 0.10+ is needed only to record traces by hand.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`. This plan delivers the trace import that Plan 2 deferred, and adds roadmap row P2b.

## Global Constraints

- Work on branch `feat/plan-02b-discovery-coverage`, cut from `main`.
- Standard library only at runtime. mGBA is an external dev-time program, reached over TCP, and never imported or bundled.
- Commits are plain, authored as `Ken <ahmadsoud63@gmail.com>`, with no trailer of any kind.
- Never commit ROM-derived bytes. Trace files and `game.toml` hold addresses only. Tests build synthetic ROMs at test time.
- Analysis never raises on ROM content. User input that is wrong raises `ConfigError` / `TraceError` (both `ValueError`) or `GdbError` (`ConnectionError`), which the CLI prints as `error: …` with exit code 1.
- Output stays deterministic: the same ROM, config and traces give byte-identical JSON and trace files.

## Review Focus

1. **mGBA protocol quirks.**
   - Replies can arrive split across reads, and stray `+` acks appear everywhere.
   - A breakpoint stop can read `S05k`.
   - An interrupt sent while the game is already halted gets no reply.
   - Pinned in Task 5 (`test_reply_split_across_reads_with_stray_acks`, `test_stop_replies`) and Task 6 (every session test starts with an unanswered interrupt).
2. **A step that lands on another breakpoint site** must be stepped as well, never resumed from. Pinned in Task 6 (`test_steps_over_a_site_that_lands_on_another_site`).
3. **A malformed trace, or one recorded on another ROM,** must be rejected before analysis, with the file and line named. Pinned in Task 1 (`test_rejects_bad_traces`, `test_errors_name_the_file_and_line`) and Task 2 (`test_trace_of_another_rom_is_an_error`).
4. **Pointer candidates** must never split or claim code found from trusted seeds, and must never land in literal pools. Pinned in Task 3 (`test_candidates_never_split_trusted_code`, `test_candidates_never_land_in_data`).
5. **Copies that should not be adopted:** a copy holding no wanted code, a copy from RAM rather than ROM, or a copy overlapping configured `ram_code`. None of these may become an overlay. Pinned in Task 4 (`test_copies_without_wanted_code_are_not_adopted`, `test_copies_from_ram_are_not_adopted`, `test_detected_copies_never_overlap_configured_ram_code`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/gbaport/analysis/traces.py` (new) | Trace file format: `Hit`, `Trace`, parse/format/load/save, `targets_by_site`, `default_trace_paths`, `TraceError` |
| `src/gbaport/analysis/pointers.py` (new) | `pointer_candidates(space)`: ROM words pointing at plausible function starts |
| `src/gbaport/analysis/discover.py` | Takes `traced=` and `candidates=`; records `traced`, `copies` and `outside`; adds `RamCopy` |
| `src/gbaport/analysis/space.py` | `CodeSpace.decode(addr, mode)`, shared by discovery and the pointer scan |
| `src/gbaport/analysis/effects.py` | Constant tracking also covers ORR/AND/EOR/BIC |
| `src/gbaport/analysis/flow.py` | `writes_pc` made public for the pointer scan |
| `src/gbaport/analysis/config.py` | `[code] scan_pointers` (default true) |
| `src/gbaport/analysis/analyze.py` | Traces, pointer scan, adoption rounds for copied RAM code; `found by` and `ram code` summary rows; `traced` and `ram_code` in the JSON |
| `src/gbaport/analysis/cfg.py` | Traced jumps count as tail calls |
| `src/gbaport/tracing/gdb.py` (new) | GDB remote protocol client: `GdbClient`, `SocketTransport`, `Registers`, `Stop`, `GdbError` |
| `src/gbaport/tracing/session.py` (new) | `breakpoint_sites`, `TraceSession` |
| `src/gbaport/cli.py` | `analyze --trace`, auto-loads `games/<code>/traces/*.trace`; new `trace` command |
| `tests/gdbfake.py` (new) | Scripted fake of mGBA's GDB server, `serve()` behind a real socket, `SESSION_RUN` |
| `tests/progkit.py` | `explore_program(traced=, candidates=)`, plus `DMA_COPY` and `SESSION_PROGRAM` |

---

### Task 1: Trace files

**Files:**
- Create: `src/gbaport/analysis/traces.py`
- Test: `tests/analysis/test_traces.py`

**Interfaces:**
- Consumes: `Mode` (`gbaport.isa.model`).
- Produces:
  - `FORMAT = "gbaport-trace/1"`, `class TraceError(ValueError)`.
  - `@dataclass(frozen=True) Hit(site: int, target: int, mode: Mode)`.
  - `@dataclass Trace(sha1: str, hits: set[Hit] = set())` with `add(hit) -> bool` (True when new) and `merge(other)`.
  - `sorted_hits(hits) -> list[Hit]`, `targets_by_site(traces: list[Trace]) -> dict[int, tuple[tuple[int, Mode], ...]]`.
  - `format_trace(trace) -> str`, `parse_trace(text, source="trace") -> Trace`, `load_trace(path) -> Trace`, `save_trace(trace, path)` (atomic, creates directories).
  - `default_trace_paths(game_code, root=Path(".")) -> list[Path]`.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-02b-discovery-coverage
```

- [ ] **Step 2: Write the failing tests**

Create `tests/analysis/test_traces.py`:
```python
import pytest

from gbaport.analysis.traces import (
    Hit,
    Trace,
    TraceError,
    default_trace_paths,
    format_trace,
    load_trace,
    parse_trace,
    save_trace,
    targets_by_site,
)
from gbaport.isa.model import Mode

SHA1 = "8dd4b6e95dca4554a919bff55128481a9a95b611"


def test_round_trip_is_sorted_and_deduplicated():
    trace = Trace(SHA1)
    assert trace.add(Hit(0x08000200, 0x08001000, Mode.THUMB))
    assert trace.add(Hit(0x08000100, 0x03000000, Mode.ARM))
    assert not trace.add(Hit(0x08000200, 0x08001000, Mode.THUMB))
    text = format_trace(trace)
    assert text == (
        f"gbaport-trace/1 {SHA1}\n"
        "08000100 03000000 arm\n"
        "08000200 08001000 thumb\n"
    )
    assert parse_trace(text) == trace


def test_comments_blank_lines_and_upper_case_are_accepted():
    text = f"# recorded in mGBA\n\ngbaport-trace/1 {SHA1.upper()}\n  # boot\n0800ABCD 08001000 thumb\n"
    trace = parse_trace(text)
    assert trace.sha1 == SHA1
    assert trace.hits == {Hit(0x0800ABCD, 0x08001000, Mode.THUMB)}


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "empty file"),
        ("gbaport-trace/2 " + SHA1, "header"),
        ("gbaport-trace/1 1234", "header"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001000", "expected 'site target mode'"),
        (f"gbaport-trace/1 {SHA1}\n08000100 zz thumb", "not a hex address"),
        (f"gbaport-trace/1 {SHA1}\n08000100 -4 arm", "not a 32-bit address"),
        (f"gbaport-trace/1 {SHA1}\n108000100 08001000 arm", "not a 32-bit address"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001000 thumb2", 'mode must be "arm" or "thumb"'),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001002 arm", "misaligned"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001001 thumb", "misaligned"),
    ],
)
def test_rejects_bad_traces(text, message):
    with pytest.raises(TraceError, match=message):
        parse_trace(text, "run.trace")


def test_errors_name_the_file_and_line():
    with pytest.raises(TraceError, match=r"run\.trace:3:"):
        parse_trace(f"gbaport-trace/1 {SHA1}\n\n08000100 zz arm\n", "run.trace")


def test_merge_requires_the_same_rom():
    trace = Trace(SHA1, {Hit(1 << 27, 1 << 27, Mode.ARM)})
    trace.merge(Trace(SHA1, {Hit(2, 4, Mode.ARM)}))
    assert len(trace.hits) == 2
    with pytest.raises(TraceError, match="cannot merge"):
        trace.merge(Trace("0" * 40))


def test_targets_by_site_combines_traces():
    first = Trace(SHA1, {Hit(0x100, 0x400, Mode.ARM), Hit(0x100, 0x300, Mode.THUMB)})
    second = Trace(SHA1, {Hit(0x100, 0x300, Mode.THUMB), Hit(0x200, 0x500, Mode.ARM)})
    assert targets_by_site([first, second]) == {
        0x100: ((0x300, Mode.THUMB), (0x400, Mode.ARM)),
        0x200: ((0x500, Mode.ARM),),
    }


def test_save_and_load(tmp_path):
    path = tmp_path / "games" / "ATST" / "traces" / "mgba.trace"
    trace = Trace(SHA1, {Hit(0x08000100, 0x08000200, Mode.THUMB)})
    save_trace(trace, path)
    assert load_trace(path) == trace
    assert not path.with_name("mgba.trace.tmp").exists()
    assert default_trace_paths("ATST", tmp_path) == [path]
    assert default_trace_paths("NONE", tmp_path) == []


def test_non_utf8_file_names_the_file(tmp_path):
    path = tmp_path / "bad.trace"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(TraceError, match="bad.trace"):
        load_trace(path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_traces.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.traces'`

- [ ] **Step 4: Write the trace module**

Create `src/gbaport/analysis/traces.py`:
```python
"""Execution traces: where indirect branches and calls went while the game ran.

A trace is a text file with one observation per line, so runs merge by
concatenation and diffs stay readable::

    gbaport-trace/1 8dd4b6e95dca4554a919bff55128481a9a95b611
    # comments and blank lines are ignored
    080359de 0800a1c4 thumb

The header names the sha1 of the ROM the trace was recorded on. Each line is
``site target mode``: the indirect branch or call at ``site`` went to
``target``, running in ``mode``. Traces hold addresses only, never ROM bytes.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from gbaport.isa.model import Mode

FORMAT = "gbaport-trace/1"


class TraceError(ValueError):
    """A trace file is malformed or was recorded on a different ROM."""


@dataclass(frozen=True)
class Hit:
    site: int  # the indirect branch or call instruction
    target: int  # where it went
    mode: Mode  # the state the target ran in


@dataclass
class Trace:
    sha1: str
    hits: set[Hit] = field(default_factory=set)

    def add(self, hit: Hit) -> bool:
        """Record ``hit``; True when it was not seen before."""
        if hit in self.hits:
            return False
        self.hits.add(hit)
        return True

    def merge(self, other: "Trace") -> None:
        if other.sha1 != self.sha1:
            raise TraceError(f"cannot merge a trace of ROM {other.sha1} into one of {self.sha1}")
        self.hits |= other.hits


def sorted_hits(hits: set[Hit]) -> list[Hit]:
    return sorted(hits, key=lambda hit: (hit.site, hit.target, hit.mode.value))


def targets_by_site(traces: list[Trace]) -> dict[int, tuple[tuple[int, Mode], ...]]:
    """Every traced target of each site, in a stable order."""
    sites: dict[int, list[tuple[int, Mode]]] = {}
    for hit in sorted_hits({hit for trace in traces for hit in trace.hits}):
        sites.setdefault(hit.site, []).append((hit.target, hit.mode))
    return {site: tuple(targets) for site, targets in sites.items()}


def format_trace(trace: Trace) -> str:
    lines = [f"{FORMAT} {trace.sha1}"]
    lines += [f"{h.site:08x} {h.target:08x} {h.mode.value}" for h in sorted_hits(trace.hits)]
    return "\n".join(lines) + "\n"


def parse_trace(text: str, source: str = "trace") -> Trace:
    rows = [
        (number, line.split())
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rows:
        raise TraceError(f"{source}: empty file, expected a '{FORMAT} <sha1>' header")
    number, header = rows[0]
    if len(header) != 2 or header[0] != FORMAT or not _is_sha1(header[1]):
        raise TraceError(f"{source}:{number}: expected a '{FORMAT} <sha1>' header")
    trace = Trace(header[1].lower())
    for number, fields in rows[1:]:
        trace.add(_hit(fields, f"{source}:{number}"))
    return trace


def load_trace(path: str | Path) -> Trace:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise TraceError(f"{path}: not a UTF-8 text file") from None
    return parse_trace(text, str(path))


def save_trace(trace: Trace, path: str | Path) -> None:
    """Write ``trace`` to ``path`` atomically, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(format_trace(trace), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def default_trace_paths(game_code: str, root: Path = Path(".")) -> list[Path]:
    """``games/<game_code>/traces/*.trace`` under ``root``, sorted."""
    return sorted((root / "games" / game_code / "traces").glob("*.trace"))


def _is_sha1(text: str) -> bool:
    return len(text) == 40 and all(c in "0123456789abcdefABCDEF" for c in text)


def _hit(fields: list[str], where: str) -> Hit:
    if len(fields) != 3:
        raise TraceError(f"{where}: expected 'site target mode', got {' '.join(fields)!r}")
    site, target = (_address(text, where) for text in fields[:2])
    if fields[2] not in ("arm", "thumb"):
        raise TraceError(f'{where}: mode must be "arm" or "thumb", got {fields[2]!r}')
    mode = Mode(fields[2])
    if target % (2 if mode is Mode.THUMB else 4):
        raise TraceError(f"{where}: {mode.value} target {target:#010x} is misaligned")
    return Hit(site, target, mode)


def _address(text: str, where: str) -> int:
    try:
        value = int(text, 16)
    except ValueError:
        raise TraceError(f"{where}: {text!r} is not a hex address") from None
    if not 0 <= value <= 0xFFFFFFFF:
        raise TraceError(f"{where}: {text!r} is not a 32-bit address")
    return value
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/analysis/test_traces.py -v && uv run ruff check src tests`
Expected: 17 passed; ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/analysis/traces.py tests/analysis/test_traces.py
git commit -m "feat: trace file format"
```

---

### Task 2: Import traces into discovery

**Files:**
- Modify: `src/gbaport/analysis/discover.py`, `src/gbaport/analysis/cfg.py`, `src/gbaport/analysis/analyze.py`, `src/gbaport/cli.py`
- Test: `tests/progkit.py`, `tests/analysis/test_discover.py`, `tests/analysis/test_analyze.py`, `tests/test_analyze_cli.py`

**Interfaces:**
- Consumes: `Trace`, `TraceError`, `targets_by_site`, `default_trace_paths`, `load_trace` (Task 1).
- Produces:
  - `Traced = dict[int, tuple[tuple[int, Mode], ...]]` in `discover`.
  - `explore(space, seeds, config=None, *, traced: Traced | None = None)`.
  - `Exploration.traced: dict[int, tuple[int, ...]]`: an indirect site resolved from traces, mapped to its callees, switch cases or the entries it leaves for.
  - Entry kind `"trace"`.
  - `analyze_rom(rom, config=None, traces: tuple[Trace, ...] = ())`, which raises `TraceError` on a sha1 mismatch.
  - JSON key `"traced"`.
  - Summary row `found by` (function kinds with counts, alphabetical).
  - `gbaport analyze --trace FILE` (repeatable), which also reads `games/<game_code>/traces/*.trace`.
  - `tests/progkit.py` `explore_program(..., traced=None)`.
- Behaviour:
  - An unresolved call or indirect jump takes its targets from `traced` and raises no issue. Calls fill `calls[site]`, and every resolved site goes into `traced[site]`.
  - At a jump table with no bound, traced targets become cases (successors). At any other indirect jump they become entries, and so tail calls.
  - The targets of traced sites that no walk reaches become entries anyway.

- [ ] **Step 1: Write the failing tests**

In `tests/progkit.py`, replace:
```python
from gbaport.analysis.discover import Exploration, explore
```
with:
```python
from gbaport.analysis.discover import Exploration, Traced, explore
```

In `tests/progkit.py`, replace:
```python
    config: GameConfig | None = None,
    size: int = 0x400,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    return explore(space, seeds or [(CODE_ADDR, mode, "seed")], config)
```
with:
```python
    config: GameConfig | None = None,
    size: int = 0x400,
    traced: Traced | None = None,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    return explore(space, seeds or [(CODE_ADDR, mode, "seed")], config, traced=traced)
```

Append to `tests/analysis/test_discover.py`:
```python
# A call through a veneer whose register comes from memory.
#   c0 main   c4 bl via_r3   cc via_r3   d0 target (never reached statically)
UNKNOWN_VENEER = """
main:
    push {lr}
    ldr r3, [r0]
    bl via_r3
    pop {r0}
    bx r0
via_r3:
    bx r3
    mov r8, r8
target:
    bx lr
"""


def test_trace_resolves_a_call_through_a_veneer():
    assert (0x080000C4, "unresolved_call") in kinds(explore_program(UNKNOWN_VENEER, thumb=True))
    traced = {0x080000C4: ((0x080000D0, Mode.THUMB),)}
    ex = explore_program(UNKNOWN_VENEER, thumb=True, traced=traced)
    assert ex.calls[0x080000C4] == (0x080000D0,)
    assert ex.traced == {0x080000C4: (0x080000D0,)}
    assert ex.entry_kinds[0x080000D0] == "trace"
    assert ex.issues == []


def test_trace_resolves_an_indirect_jump_to_entries():
    source = "ldr r0, [r1]\nbx r0\nt1: bx lr\nt2: bx lr"
    traced = {0x080000C4: ((0x080000CC, Mode.ARM), (0x080000C8, Mode.ARM))}
    ex = explore_program(source, traced=traced)
    assert ex.traced == {0x080000C4: (0x080000C8, 0x080000CC)}
    assert ex.entry_kinds[0x080000C8] == ex.entry_kinds[0x080000CC] == "trace"
    assert ex.successors[0x080000C4] == ()
    assert ex.issues == []


def test_trace_gives_an_unbounded_switch_its_cases():
    traced = {0x080000C8: ((0x080000D8, Mode.THUMB), (0x080000DA, Mode.THUMB))}
    ex = explore_program(UNBOUNDED_TABLE, thumb=True, traced=traced)
    assert ex.successors[0x080000C8] == (0x080000D8, 0x080000DA)
    assert 0x080000D8 not in ex.entries
    assert ex.issues == []


def test_targets_of_unreached_traced_sites_become_entries():
    ex = explore_program("bx lr\nt: bx lr", traced={0x08000300: ((0x080000C4, Mode.ARM),)})
    assert ex.entry_kinds[0x080000C4] == "trace"
```

In `tests/analysis/test_analyze.py`, replace:
```python
from gbaport.analysis.analyze import Coverage, analysis_to_dict, analyze_rom, summary_lines
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.isa.model import Mode
```
with:
```python
from gbaport.analysis.analyze import Coverage, analysis_to_dict, analyze_rom, summary_lines
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.analysis.traces import Hit, Trace, TraceError
from gbaport.isa.model import Mode
from gbaport.rom.info import inspect_rom
```

In `tests/analysis/test_analyze.py`, replace:
```python
    assert lines[0] == "functions    4 (0 veneers)"
```
with:
```python
    assert lines[0] == "functions    4 (0 veneers)"
    assert lines[1] == "found by     call 2, irq 1, seed 1"
```

Append to `tests/analysis/test_analyze.py`:
```python
def test_traces_must_match_the_rom():
    with pytest.raises(TraceError, match="sha1"):
        analyze_rom(program_rom("bx lr"), traces=(Trace("0" * 40),))


def test_trace_targets_become_functions():
    rom = program_rom("ldr r0, [r1]\nbx r0\nt: bx lr")
    trace = Trace(inspect_rom(rom).sha1, {Hit(0x080000C4, 0x080000C8, Mode.ARM)})
    analysis = analyze_rom(rom, traces=(trace,))
    assert analysis.program.functions[0x080000C8].kind == "trace"
    assert analysis.program.functions[0x080000C0].tail_calls == (0x080000C8,)
    assert analysis_to_dict(analysis)["traced"] == [
        {"site": "0x080000c4", "targets": ["0x080000c8"]}
    ]
    assert "found by     seed 1, trace 1" in summary_lines(analysis)
```

In `tests/test_analyze_cli.py`, replace:
```python
import json

from ksasm import assemble
from progkit import CRT0, program_rom
```
with:
```python
import hashlib
import json

from ksasm import assemble
from progkit import CRT0, program_rom
```

Append to `tests/test_analyze_cli.py`:
```python
def test_trace_option_and_traces_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = program_rom("ldr r0, [r1]\nbx r0\nt: bx lr")
    path = write(tmp_path, rom)
    text = f"gbaport-trace/1 {hashlib.sha1(rom.data).hexdigest()}\n080000c4 080000c8 arm\n"
    (tmp_path / "run.trace").write_text(text)
    assert main(["analyze", str(path), "--trace", "run.trace"]) == 0
    assert "seed 1, trace 1" in capsys.readouterr().out
    folder = tmp_path / "games" / "ATST" / "traces"
    folder.mkdir(parents=True)
    (folder / "mgba.trace").write_text(text)
    assert main(["analyze", str(path)]) == 0
    out = capsys.readouterr().out
    assert "mgba.trace" in out and "seed 1, trace 1" in out


def test_trace_of_another_rom_is_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "other.trace").write_text("gbaport-trace/1 " + "0" * 40 + "\n")
    args = ["analyze", str(write(tmp_path, program_rom("bx lr"))), "--trace", "other.trace"]
    assert main(args) == 1
    assert "sha1" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis/test_discover.py tests/analysis/test_analyze.py tests/test_analyze_cli.py -v`
Expected: FAIL — `ImportError: cannot import name 'Traced' from 'gbaport.analysis.discover'` (raised while importing `progkit`)

- [ ] **Step 3: Implement trace import**

In `src/gbaport/analysis/discover.py`, replace:
```python
becomes an entry too. Anything the walk cannot follow becomes an ``Issue``;
nothing in the ROM can make it raise.
"""
```
with:
```python
becomes an entry too. Indirect transfers the walk cannot resolve take their
targets from recorded traces when there are any. Anything else the walk
cannot follow becomes an ``Issue``; nothing in the ROM can make it raise.
"""
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    tables: list[JumpTable] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def explore(
    space: CodeSpace, seeds: list[tuple[int, Mode, str]], config: GameConfig | None = None
) -> Exploration:
```
with:
```python
    tables: list[JumpTable] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # Indirect site -> targets taken from traces: callees, switch cases, or functions it leaves for.
    traced: dict[int, tuple[int, ...]] = field(default_factory=dict)


Traced = dict[int, tuple[tuple[int, Mode], ...]]  # site -> (target, mode) seen in traces


def explore(
    space: CodeSpace,
    seeds: list[tuple[int, Mode, str]],
    config: GameConfig | None = None,
    *,
    traced: Traced | None = None,
) -> Exploration:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    finds no new one (the set only grows, so this ends).
    """
    config = config or GameConfig()
    leaders: frozenset[int] = frozenset()
    while True:
        explorer = _Explorer(space, config, leaders)
        for addr, mode, kind in seeds:
            explorer.add_entry(addr, mode, kind, origin=addr)
        explorer.drain()
        if explorer.targets <= leaders:
```
with:
```python
    finds no new one (the set only grows, so this ends).

    ``traced`` resolves the indirect sites a walk reaches; targets of traced
    sites no walk reaches become entries of their own.
    """
    config = config or GameConfig()
    traced = {space.canonical(site): hits for site, hits in (traced or {}).items()}
    leaders: frozenset[int] = frozenset()
    while True:
        explorer = _Explorer(space, config, leaders, traced)
        for addr, mode, kind in seeds:
            explorer.add_entry(addr, mode, kind, origin=addr)
        explorer.drain()
        explorer.drain_traces()
        if explorer.targets <= leaders:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    def __init__(self, space: CodeSpace, config: GameConfig, leaders: frozenset[int]) -> None:
        self.space = space
```
with:
```python
    def __init__(
        self, space: CodeSpace, config: GameConfig, leaders: frozenset[int], traced: Traced
    ) -> None:
        self.space = space
        self.traced = traced
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    def drain(self) -> None:
        while self.work:
            self.walk(*self.work.popleft())
```
with:
```python
    def drain(self) -> None:
        while self.work:
            self.walk(*self.work.popleft())

    def drain_traces(self) -> None:
        """Targets of traced sites no walk reached become entries themselves."""
        done: set[int] = set()
        while True:
            pending = [
                site
                for site in sorted(self.traced)
                if site not in done and site not in self.ex.instructions
            ]
            if not pending:
                return
            for site in pending:
                done.add(site)
                for target, mode in self.traced[site]:
                    self.add_entry(target, mode, "trace", origin=site)
            self.drain()
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    def _call(self, ins: Instruction, flow: Flow, state: RegState) -> None:
        if flow.target is None:
            self.issue(ins.addr, "unresolved_call", f"{format_instruction(ins)}: target unknown")
            return
```
with:
```python
    def _call(self, ins: Instruction, flow: Flow, state: RegState) -> None:
        if flow.target is None:
            if not self._traced_call(ins):
                self.issue(
                    ins.addr, "unresolved_call", f"{format_instruction(ins)}: target unknown"
                )
            return
```

In `src/gbaport/analysis/discover.py`, replace:
```python
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
```
with:
```python
        value = state.value(register, ins)
        if value is None:
            if not self._traced_call(ins):
                self.issue(
                    ins.addr,
                    "unresolved_call",
                    f"call through a bx r{register} veneer with r{register} unknown",
                )
            return None
        target, mode = interwork_target(value)
        return self.add_entry(target, mode, "call", origin=ins.addr)

    def _traced_call(self, ins: Instruction) -> bool:
        """Take an unknown call's callees from the traces; False when no trace saw it."""
        added = [
            self.add_entry(target, mode, "trace", origin=ins.addr)
            for target, mode in self.traced.get(ins.addr, ())
        ]
        callees = tuple(sorted({entry for entry in added if entry is not None}))
        if callees:
            self.ex.calls[ins.addr] = callees
            self.ex.traced[ins.addr] = callees
        return bool(callees)
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        match = find_jump_table(ins, history, self.space, self.overrides)
        if match is None:
```
with:
```python
        match = find_jump_table(ins, history, self.space, self.overrides)
        hits = self.traced.get(ins.addr, ())
        if hits and (match is None or match.table is None):
            return self._traced_jump(ins, hits, switch=match is not None)
        if match is None:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        targets = (self.add_branch(t, table.mode, origin=ins.addr) for t in table.targets)
        return tuple(t for t in targets if t is not None)
```
with:
```python
        targets = (self.add_branch(t, table.mode, origin=ins.addr) for t in table.targets)
        return tuple(t for t in targets if t is not None)

    def _traced_jump(
        self, ins: Instruction, hits: tuple[tuple[int, Mode], ...], switch: bool
    ) -> tuple[int, ...]:
        """Traced targets of an indirect jump: cases of a ``switch``, or entries it leaves for.

        Returns the successors inside the function (none when the jump leaves it).
        """
        if switch:
            found = [self.add_branch(target, mode, origin=ins.addr) for target, mode in hits]
        else:
            found = [
                self.add_entry(target, mode, "trace", origin=ins.addr) for target, mode in hits
            ]
        targets = tuple(sorted({t for t in found if t is not None}))
        self.ex.traced[ins.addr] = targets
        return targets if switch else ()
```

In `src/gbaport/analysis/cfg.py`, replace:
```python
    tails |= {ex.jumps[addr] for addr in addrs if addr in ex.jumps}
```
with:
```python
    tails |= {ex.jumps[addr] for addr in addrs if addr in ex.jumps}
    jumped = [addr for addr in addrs if addr in ex.traced and addr not in ex.calls]
    tails |= {t for addr in jumped for t in ex.traced[addr] if t in ex.entries}
```

In `src/gbaport/analysis/cfg.py`, replace:
```python
    kind: str  # how it was found: seed, call, veneer, jump, irq or return
```
with:
```python
    kind: str  # how it was found: seed, call, veneer, jump, irq, return or trace
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
```
with:
```python
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.traces import Trace, TraceError, targets_by_site
from gbaport.isa.model import Mode
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
def analyze_rom(rom: RomImage, config: GameConfig | None = None) -> Analysis:
    config = config or GameConfig()
    info = inspect_rom(rom)
    if config.rom_sha1 is not None and config.rom_sha1 != info.sha1:
        raise ConfigError(
            f"game.toml is for ROM sha1 {config.rom_sha1}, but this ROM is {info.sha1}"
        )
```
with:
```python
def analyze_rom(
    rom: RomImage, config: GameConfig | None = None, traces: tuple[Trace, ...] = ()
) -> Analysis:
    config = config or GameConfig()
    info = inspect_rom(rom)
    if config.rom_sha1 is not None and config.rom_sha1 != info.sha1:
        raise ConfigError(
            f"game.toml is for ROM sha1 {config.rom_sha1}, but this ROM is {info.sha1}"
        )
    for trace in traces:
        if trace.sha1 != info.sha1:
            raise TraceError(f"trace is for ROM sha1 {trace.sha1}, but this ROM is {info.sha1}")
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    exploration = explore(space, seeds, config)
```
with:
```python
    exploration = explore(space, seeds, config, traced=targets_by_site(list(traces)))
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
        "literals": [{"addr": _hex(a), "size": size} for a, size in sorted(ex.literals.items())],
```
with:
```python
        "literals": [{"addr": _hex(a), "size": size} for a, size in sorted(ex.literals.items())],
        "traced": [
            {"site": _hex(site), "targets": [_hex(t) for t in targets]}
            for site, targets in sorted(ex.traced.items())
        ],
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
    counts = Counter(issue.kind for issue in ex.issues)
    breakdown = ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items())) or "none"
    rows = [
        ("functions", f"{len(program.functions)} ({veneers} veneers)"),
```
with:
```python
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
    rows = [
        ("functions", f"{len(program.functions)} ({veneers} veneers)"),
        ("found by", _breakdown(f.kind for f in program.functions.values())),
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
        ("issues", f"{len(ex.issues)} ({breakdown})"),
    ]
    return [f"{label:<13}{value}" for label, value in rows]
```
with:
```python
        ("issues", f"{len(ex.issues)} ({_breakdown(issue.kind for issue in ex.issues)})"),
    ]
    return [f"{label:<13}{value}" for label, value in rows]


def _breakdown(kinds) -> str:
    counts = Counter(kinds)
    return ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items())) or "none"
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.analysis.config import GameConfig, default_config_path, load_config
```
with:
```python
from gbaport.analysis.config import GameConfig, default_config_path, load_config
from gbaport.analysis.traces import default_trace_paths, load_trace
```

In `src/gbaport/cli.py`, replace:
```python
    analyze.add_argument("--issues", type=int, default=20, help="issues to list (default 20)")
    analyze.set_defaults(handler=_run_analyze)


def _run_analyze(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    config_path = args.config or default_config_path(parse_header(rom).game_code)
    config = load_config(config_path) if config_path else GameConfig()
    analysis = analyze_rom(rom, config)
    if config_path:
        print(f"{'config':<13}{config_path}")
```
with:
```python
    analyze.add_argument("--issues", type=int, default=20, help="issues to list (default 20)")
    analyze.add_argument(
        "--trace",
        action="append",
        default=[],
        help="trace file to import (repeatable; games/<game_code>/traces/*.trace are read too)",
    )
    analyze.set_defaults(handler=_run_analyze)


def _run_analyze(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code
    config_path = args.config or default_config_path(game_code)
    config = load_config(config_path) if config_path else GameConfig()
    trace_paths = [*default_trace_paths(game_code), *map(Path, args.trace)]
    analysis = analyze_rom(rom, config, tuple(load_trace(path) for path in trace_paths))
    if config_path:
        print(f"{'config':<13}{config_path}")
    for path in trace_paths:
        print(f"{'trace':<13}{path}")
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 421 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis src/gbaport/cli.py tests
git commit -m "feat: import traces into discovery and analyze"
```

---

### Task 3: Pointer scan

**Files:**
- Create: `src/gbaport/analysis/pointers.py`
- Modify: `src/gbaport/analysis/flow.py`, `src/gbaport/analysis/space.py`, `src/gbaport/analysis/discover.py`, `src/gbaport/analysis/config.py`, `src/gbaport/analysis/analyze.py`
- Test: `tests/progkit.py`, `tests/analysis/test_space.py`, `tests/analysis/test_pointers.py`, `tests/analysis/test_discover.py`, `tests/analysis/test_config.py`, `tests/analysis/test_analyze.py`

**Interfaces:**
- Consumes: `CodeSpace` (Plan 2), `explore(..., traced=)` (Task 2).
- Produces:
  - `CodeSpace.decode(addr, mode) -> Instruction | None`.
  - `flow.writes_pc(ins) -> bool` (renamed from `_writes_pc`).
  - `pointer_candidates(space) -> list[tuple[int, Mode, str]]`, with kind `"pointer"`, sorted by address.
  - `explore(..., candidates: list[tuple[int, Mode, str]] | None = None)`.
  - `GameConfig.scan_pointers: bool = True` and `[code] scan_pointers`.
  - `tests/progkit.py` `explore_program(..., candidates=None)`.
- Behaviour: candidates are walked one at a time after seeds and traces. A candidate is skipped when it lands on a decoded instruction, inside a 4-byte instruction, or in data.

- [ ] **Step 1: Write the failing tests**

In `tests/progkit.py`, replace:
```python
    traced: Traced | None = None,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    return explore(space, seeds or [(CODE_ADDR, mode, "seed")], config, traced=traced)
```
with:
```python
    traced: Traced | None = None,
    candidates: list[tuple[int, Mode, str]] | None = None,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    seeds = seeds or [(CODE_ADDR, mode, "seed")]
    return explore(space, seeds, config, traced=traced, candidates=candidates or [])
```

Append to `tests/analysis/test_space.py`:
```python
def test_decode_in_either_mode():
    code = bytes.fromhex("1eff2fe1") + bytes.fromhex("00f000f8")  # bx lr; Thumb bl
    space = CodeSpace(RomImage(build_rom(code=code)))
    assert space.decode(0x080000C0, Mode.ARM).op.value == "bx"
    bl = space.decode(0x080000C4, Mode.THUMB)
    assert (bl.op.value, bl.size) == ("bl", 4)
    assert space.decode(0x09000000, Mode.ARM) is None
```

Create `tests/analysis/test_pointers.py`:
```python
from ksasm import assemble
from progkit import program_rom, program_space

from gbaport.analysis.config import RamCode
from gbaport.analysis.pointers import pointer_candidates
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode

# A table of code pointers next to functions of every shape.
#   c4..d8 the table   dc arm_cb   e4 apcs_cb   ec cb (Thumb)   f2 plain   f4 garbage
POINTERS = """
main:
    bx lr
callbacks:
    .word cb+1
    .word plain+1
    .word garbage+1
    .word arm_cb
    .word apcs_cb
    .word main+2
arm_cb:
    push {r4, lr}
    pop {r4, pc}
apcs_cb:
    mov r12, sp
    bx lr
.thumb
cb:
    push {lr}
    pop {r0}
    bx r0
plain:
    bx lr
garbage:
    push {lr}
    .hword 0xde00
"""


def test_pointers_to_prologues_that_decode_cleanly():
    assert pointer_candidates(program_space(POINTERS)) == [
        (0x080000DC, Mode.ARM, "pointer"),
        (0x080000E4, Mode.ARM, "pointer"),
        (0x080000EC, Mode.THUMB, "pointer"),
    ]


def test_pointers_into_ram_code():
    blob = assemble("push {r4, lr}\npop {r4, pc}", addr=0x03000000)
    rom = program_rom(".word 0x03000000", patches={0x200: blob})
    space = CodeSpace(rom, (RamCode(0x08000200, 0x03000000, len(blob), Mode.ARM),))
    assert pointer_candidates(space) == [(0x03000000, Mode.ARM, "pointer")]


def test_no_pointers_no_candidates():
    assert pointer_candidates(program_space("bx lr")) == []
```

Append to `tests/analysis/test_discover.py`:
```python
# Thumb main calls helper; extra is reachable only through a pointer.
#   c0 main   c2 bl helper (4 bytes)   ca helper   d0 extra
WITH_EXTRA = """
main:
    push {lr}
    bl helper
    pop {r0}
    bx r0
helper:
    push {lr}
    pop {r0}
    bx r0
extra:
    push {lr}
    pop {r0}
    bx r0
"""


def test_candidates_never_split_trusted_code():
    candidates = [
        (0x080000C4, Mode.THUMB, "pointer"),  # second half of the bl
        (0x080000CC, Mode.THUMB, "pointer"),  # inside helper
        (0x080000D0, Mode.THUMB, "pointer"),
    ]
    ex = explore_program(WITH_EXTRA, thumb=True, candidates=candidates)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000CA: "call", 0x080000D0: "pointer"}
    assert ex.issues == []


def test_candidates_never_land_in_data():
    source = "ldr r0, lit\nbx lr\nlit: .word 0"
    ex = explore_program(source, candidates=[(0x080000C8, Mode.ARM, "pointer")])
    assert 0x080000C8 not in ex.entries
```

In `tests/analysis/test_config.py`, replace:
```python
def test_empty_config_has_defaults():
    assert parse_config("") == GameConfig()
```
with:
```python
def test_empty_config_has_defaults():
    assert parse_config("") == GameConfig()
    assert GameConfig().scan_pointers is True


def test_pointer_scan_can_be_turned_off():
    assert parse_config("[code]\nscan_pointers = false").scan_pointers is False
```

In `tests/analysis/test_config.py`, replace:
```python
        ("[code]\ndata = [[2, 1]]", "is empty"),
```
with:
```python
        ("[code]\ndata = [[2, 1]]", "is empty"),
        ("[code]\nscan_pointers = 1", "scan_pointers must be true or false"),
```

Append to `tests/analysis/test_analyze.py`:
```python
def test_pointer_scan_finds_callbacks():
    rom = program_rom("bx lr\n.word cb+1\n.thumb\ncb:\n push {lr}\n pop {r0}\n bx r0")
    assert analyze_rom(rom).program.functions[0x080000C8].kind == "pointer"
    without = analyze_rom(rom, GameConfig(scan_pointers=False))
    assert 0x080000C8 not in without.program.functions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.analysis.pointers'`

- [ ] **Step 3: Implement the pointer scan**

Create `src/gbaport/analysis/pointers.py`:
```python
"""Function-pointer candidates: ROM words that point at a plausible function start.

Callbacks and state-machine tables are reached only through pointers the game
loads at run time, so recursive descent never sees them. A word holding a code
address is a candidate when its target starts with a frame-saving prologue
(Thumb ``push {..., lr}``, ARM ``stmdb sp!, {..., lr}`` or ``mov r12, sp``)
and decodes cleanly up to its first unconditional transfer. Discovery walks
candidates only after everything reachable from trusted seeds is decoded, so a
wrong guess cannot claim real code first.
"""

import sys
from array import array

from gbaport.analysis.flow import writes_pc
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Cond, Mode, Op
from gbaport.rom.image import ROM_BASE

MAX_PROBE = 256  # instructions decoded before a candidate is given up on
_SUSPECT = frozenset({Op.UNDEFINED, Op.BL_HI, Op.BL_LO})


def pointer_candidates(space: CodeSpace) -> list[tuple[int, Mode, str]]:
    """(address, mode, "pointer") for each plausible function some aligned ROM word points at."""
    data = space.rom.data
    words = array("I")
    words.frombytes(data[: len(data) - len(data) % 4])
    if sys.byteorder == "big":
        words.byteswap()
    rom_end = ROM_BASE + len(data)
    pointers = {word for word in words if ROM_BASE <= word < rom_end}
    for blob in space.overlays:
        pointers |= {word for word in words if blob.ram <= word < blob.ram + blob.size}
    found = []
    for word in sorted(pointers):
        if word & 1:
            addr, mode = word - 1, Mode.THUMB
        elif word & 2 == 0:
            addr, mode = word, Mode.ARM
        else:
            continue
        if _has_prologue(space, addr, mode) and _decodes_cleanly(space, addr, mode):
            found.append((addr, mode, "pointer"))
    return found


def _has_prologue(space: CodeSpace, addr: int, mode: Mode) -> bool:
    if mode is Mode.THUMB:
        return space.contains(addr, 2) and space.read16(addr) >> 8 == 0xB5  # push {..., lr}
    if not space.contains(addr, 4):
        return False
    word = space.read32(addr)
    return (word & 0xFFFF4000) == 0xE92D4000 or word == 0xE1A0C00D  # stmdb sp!, {..lr} / mov ip, sp


def _decodes_cleanly(space: CodeSpace, addr: int, mode: Mode) -> bool:
    """Decode straight on up to the first unconditional transfer; False on anything odd."""
    for _ in range(MAX_PROBE):
        ins = space.decode(addr, mode)
        if ins is None or ins.op in _SUSPECT:
            return False
        if ins.cond is Cond.AL and (ins.op is Op.B or writes_pc(ins)):
            return True
        addr += ins.size
    return False
```

In `src/gbaport/analysis/flow.py`, replace:
```python
    if not _writes_pc(ins):
        return Flow(FlowKind.NEXT)
```
with:
```python
    if not writes_pc(ins):
        return Flow(FlowKind.NEXT)
```

In `src/gbaport/analysis/flow.py`, replace:
```python
def _writes_pc(ins: Instruction) -> bool:
```
with:
```python
def writes_pc(ins: Instruction) -> bool:
    """True when ``ins`` may write r15 (``bx`` included)."""
```

In `src/gbaport/analysis/space.py`, replace:
```python
from gbaport.analysis.config import ConfigError, RamCode
from gbaport.rom.image import ROM_BASE, RomError, RomImage
```
with:
```python
from gbaport.analysis.config import ConfigError, RamCode
from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Instruction, Mode
from gbaport.isa.thumb import decode_thumb
from gbaport.rom.image import ROM_BASE, RomError, RomImage
```

In `src/gbaport/analysis/space.py`, replace:
```python
    def read16(self, addr: int) -> int:
```
with:
```python
    def decode(self, addr: int, mode: Mode) -> Instruction | None:
        """The instruction at ``addr`` in ``mode``, or None outside analysable code."""
        if mode is Mode.ARM:
            if not self.contains(addr, 4):
                return None
            return decode_arm(self.read32(addr), addr)
        if not self.contains(addr, 2):
            return None
        following = self.read16(addr + 2) if self.contains(addr + 2, 2) else None
        return decode_thumb(self.read16(addr), addr, following)

    def read16(self, addr: int) -> int:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Cond, Instruction, Mode, Op
from gbaport.isa.thumb import decode_thumb
```
with:
```python
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Cond, Instruction, Mode, Op
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    *,
    traced: Traced | None = None,
) -> Exploration:
```
with:
```python
    *,
    traced: Traced | None = None,
    candidates: list[tuple[int, Mode, str]] | None = None,
) -> Exploration:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    ``traced`` resolves the indirect sites a walk reaches; targets of traced
    sites no walk reaches become entries of their own.
    """
```
with:
```python
    ``traced`` resolves the indirect sites a walk reaches; targets of traced
    sites no walk reaches become entries of their own. ``candidates`` are
    guessed entries (pointer scan), walked one by one after all of that, and
    skipped when they land in code or data already found.
    """
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        explorer.drain()
        explorer.drain_traces()
        if explorer.targets <= leaders:
```
with:
```python
        explorer.drain()
        explorer.drain_traces()
        explorer.drain_candidates(candidates or [])
        if explorer.targets <= leaders:
```

In `src/gbaport/analysis/discover.py`, replace:
```python
                for target, mode in self.traced[site]:
                    self.add_entry(target, mode, "trace", origin=site)
            self.drain()
```
with:
```python
                for target, mode in self.traced[site]:
                    self.add_entry(target, mode, "trace", origin=site)
            self.drain()

    def drain_candidates(self, candidates: list[tuple[int, Mode, str]]) -> None:
        """Walk each guessed entry on its own, unless it lands in code or data already found."""
        for addr, mode, kind in candidates:
            addr = self.space.canonical(addr)
            covering = self.ex.instructions.get(addr - 2)
            if (
                addr in self.ex.instructions
                or (covering is not None and covering.size == 4)
                or self._is_data(addr)
            ):
                continue
            self.add_entry(addr, mode, kind, origin=addr)
            self.drain()
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        ins = self._decode(addr, mode)
        if ins is None:
            self.issue(addr, "outside_code", "walked off the end of analysable code")
```
with:
```python
        ins = self.space.decode(addr, mode)
        if ins is None:
            self.issue(addr, "outside_code", "walked off the end of analysable code")
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    def _decode(self, addr: int, mode: Mode) -> Instruction | None:
        if mode is Mode.ARM:
            if not self.space.contains(addr, 4):
                return None
            return decode_arm(self.space.read32(addr), addr)
        if not self.space.contains(addr, 2):
            return None
        following = self.space.read16(addr + 2) if self.space.contains(addr + 2, 2) else None
        return decode_thumb(self.space.read16(addr), addr, following)

```
with:
```python
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        ins = self._decode(self.space.canonical(target), mode)
```
with:
```python
        ins = self.space.decode(self.space.canonical(target), mode)
```

In `src/gbaport/analysis/config.py`, replace:
```python
    ram_code: tuple[RamCode, ...] = ()
    timing_model: str = "block"


_SECTIONS = {
    "rom": {"sha1", "save"},
    "code": {"entries", "thumb_entries", "data", "jump_tables"},
```
with:
```python
    ram_code: tuple[RamCode, ...] = ()
    timing_model: str = "block"
    scan_pointers: bool = True  # guess entries from ROM words that point at function starts


_SECTIONS = {
    "rom": {"sha1", "save"},
    "code": {"entries", "thumb_entries", "data", "jump_tables", "scan_pointers"},
```

In `src/gbaport/analysis/config.py`, replace:
```python
        timing_model=_timing(timing, source),
    )
```
with:
```python
        timing_model=_timing(timing, source),
        scan_pointers=_flag(code, "scan_pointers", True, source),
    )
```

In `src/gbaport/analysis/config.py`, replace:
```python
def _addresses(table: dict, key: str, source: str) -> tuple[int, ...]:
```
with:
```python
def _flag(table: dict, key: str, default: bool, source: str) -> bool:
    value = table.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{source}: {key} must be true or false, got {value!r}")
    return value


def _addresses(table: dict, key: str, source: str) -> tuple[int, ...]:
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
from gbaport.analysis.discover import Exploration, Issue, explore
```
with:
```python
from gbaport.analysis.discover import Exploration, Issue, explore
from gbaport.analysis.pointers import pointer_candidates
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    exploration = explore(space, seeds, config, traced=targets_by_site(list(traces)))
```
with:
```python
    candidates = pointer_candidates(space) if config.scan_pointers else []
    traced = targets_by_site(list(traces))
    exploration = explore(space, seeds, config, traced=traced, candidates=candidates)
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 430 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis tests
git commit -m "feat: pointer scan for function-pointer targets"
```

---

### Task 4: Detect code copied into RAM

**Files:**
- Modify: `src/gbaport/analysis/discover.py`, `src/gbaport/analysis/effects.py`, `src/gbaport/analysis/analyze.py`
- Test: `tests/progkit.py`, `tests/analysis/test_discover.py`, `tests/analysis/test_effects.py`, `tests/analysis/test_analyze.py`

**Interfaces:**
- Consumes: `explore(..., traced=, candidates=)` (Tasks 2–3), `pointer_candidates` (Task 3), `RamCode`, `CodeSpace` (Plan 2).
- Produces:
  - `@dataclass(frozen=True) RamCopy(site: int, src: int, dst: int, size: int)`.
  - `Exploration.copies: list[RamCopy]`, `Exploration.outside: dict[int, Mode]` (code targets outside the code space).
  - `Analysis.ram_code` (configured, then detected) and `Analysis.detected`.
  - JSON key `"ram_code"`, entries `{rom, ram, size, mode, detected}`.
  - Summary row `ram code     N configured, M detected`.
  - `tests/progkit.py` `DMA_COPY`.
- Behaviour:
  - A copy is recorded when all its operands are known constants. That covers stores to DMA registers (`str`, `strh` or `stmia`, conditional ones included) that start an immediate +1/+1 transfer, and `swi 0x0B/0x0C` that is not a fill.
  - A copy becomes an overlay when it lies entirely in EWRAM or IWRAM, contains an `outside` address, comes from the ROM, and overlaps no overlay already in use. Discovery then runs again until no copy is adopted.
  - Constant tracking gains ORR/AND/EOR/BIC, because start-up code builds DMA control words with `orr`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/progkit.py`:
```python
# ARM DMA3 copy of two words from ROM 0x08000200 to IWRAM 0x03000000, then a jump into the copy.
#   d8 the CNT store that starts the copy   e8 cnt   ec entry
DMA_COPY = """
    mov r0, #0x04000000
    ldr r1, src
    str r1, [r0, #0xd4]
    ldr r1, dst
    str r1, [r0, #0xd8]
    ldr r1, cnt
    str r1, [r0, #0xdc]
    ldr pc, entry
src: .word 0x08000200
dst: .word 0x03000000
cnt: .word 0x84000002
entry: .word 0x03000004
"""
```

In `tests/analysis/test_discover.py`, replace:
```python
import random

from progkit import (
    ARM_TABLES,
    CODE_ADDR,
    CRT0,
```
with:
```python
import random

import pytest
from progkit import (
    ARM_TABLES,
    CODE_ADDR,
    CRT0,
    DMA_COPY,
```

In `tests/analysis/test_discover.py`, replace:
```python
from gbaport.analysis.discover import explore
```
with:
```python
from gbaport.analysis.discover import RamCopy, explore
```

Append to `tests/analysis/test_discover.py`:
```python
@pytest.mark.parametrize(
    "control,size",
    [
        ("0x84000002", 8),  # 2 words, 32-bit units
        ("0x80000004", 8),  # 4 halfwords
        ("0x85000002", None),  # fixed source: a fill, not a copy
        ("0x94000002", None),  # starts at VBlank, not now
        ("0x04000002", None),  # not enabled
    ],
)
def test_dma_copies_with_known_operands(control, size):
    ex = explore_program(DMA_COPY.replace("0x84000002", control))
    expected = [] if size is None else [RamCopy(0x080000D8, 0x08000200, 0x03000000, size)]
    assert ex.copies == expected
    assert ex.outside == {0x03000004: Mode.ARM}


def test_dma_registers_written_with_stmia():
    source = """
        ldr r0, regs
        ldr r1, src
        ldr r2, dst
        ldr r3, cnt
        stmia r0!, {r1, r2, r3}
        bx lr
    .align 2
    regs: .word 0x040000d4
    src: .word 0x08000200
    dst: .word 0x02000000
    cnt: .word 0x84000010
    """
    ex = explore_program(source, thumb=True)
    assert ex.copies == [RamCopy(0x080000C8, 0x08000200, 0x02000000, 64)]


@pytest.mark.parametrize(
    "swi,control,size",
    [
        ("0xb", "0x04000010", 64),  # CpuSet, 16 words
        ("0xb", "0x00000010", 32),  # CpuSet, 16 halfwords
        ("0xc", "0x00000009", 64),  # CpuFastSet rounds up to 8-word blocks
        ("0xb", "0x05000010", None),  # CpuSet fill
    ],
)
def test_bios_copies_with_known_operands(swi, control, size):
    source = f"""
        ldr r0, src
        ldr r1, dst
        ldr r2, ctl
        svc #{swi}
        bx lr
    .align 2
    src: .word 0x08000200
    dst: .word 0x02000000
    ctl: .word {control}
    """
    ex = explore_program(source, thumb=True)
    expected = [] if size is None else [RamCopy(0x080000C6, 0x08000200, 0x02000000, size)]
    assert ex.copies == expected
```

In `tests/analysis/test_analyze.py`, replace:
```python
from progkit import CRT0, program_rom
```
with:
```python
from progkit import CRT0, DMA_COPY, program_rom
```

Append to `tests/analysis/test_analyze.py`:
```python
def copied_code_rom(source: str = DMA_COPY):
    return program_rom(source, patches={0x200: assemble("bx lr\nbx lr", addr=0x03000000)})


def test_copied_ram_code_is_detected():
    analysis = analyze_rom(copied_code_rom())
    blob = RamCode(0x08000200, 0x03000000, 8, Mode.ARM)
    assert analysis.detected == (blob,)
    assert analysis.ram_code == (blob,)
    assert analysis.program.functions[0x03000004].kind == "jump"
    assert analysis.exploration.issues == []
    assert "ram code     0 configured, 1 detected" in summary_lines(analysis)
    assert analysis_to_dict(analysis)["ram_code"] == [
        {"rom": "0x08000200", "ram": "0x03000000", "size": 8, "mode": "arm", "detected": True}
    ]


def test_copies_without_wanted_code_are_not_adopted():
    analysis = analyze_rom(copied_code_rom(DMA_COPY.replace("0x03000004", "0x03000100")))
    assert analysis.detected == ()
    assert [i.kind for i in analysis.exploration.issues] == ["outside_code"]


def test_copies_from_ram_are_not_adopted():
    analysis = analyze_rom(copied_code_rom(DMA_COPY.replace("0x08000200", "0x02000000")))
    assert analysis.detected == ()


def test_detected_copies_never_overlap_configured_ram_code():
    configured = RamCode(0x08000300, 0x03000000, 4, Mode.ARM)  # overlaps the copy, not the target
    analysis = analyze_rom(copied_code_rom(), GameConfig(ram_code=(configured,)))
    assert analysis.detected == ()
    assert analysis.ram_code == (configured,)
```

Append to `tests/analysis/test_effects.py`:
```python
def test_bitwise_operations_with_known_operands():
    source = (
        "mov r0, #0x1f\norr r1, r0, #0x84000000\nand r2, r1, #0xff\n"
        "eor r3, r2, #1\nbic r4, r1, r0\nbx lr"
    )
    assert run_states(source, 5).consts == {
        0: 0x1F, 1: 0x8400001F, 2: 0x1F, 3: 0x1E, 4: 0x84000000,
    }
```

In `tests/analysis/test_discover.py`, replace:
```python
def test_dma_registers_written_with_stmia():
```
with:
```python
def test_dma_control_built_with_orr_and_a_conditional_store():
    # The start-up code shape of real games: count >> 2 | flags, stored if the count is not 0.
    source = DMA_COPY.replace(
        "    ldr r1, cnt\n    str r1, [r0, #0xdc]\n",
        "    ldr r1, cnt\n    movs r1, r1, lsr #2\n    orr r1, r1, #0x84000000\n"
        "    strne r1, [r0, #0xdc]\n",
    ).replace("0x84000002", "8")
    ex = explore_program(source)
    assert ex.copies == [RamCopy(0x080000E0, 0x08000200, 0x03000000, 8)]


def test_dma_registers_written_with_stmia():
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/analysis -v`
Expected: FAIL — `ImportError: cannot import name 'RamCopy' from 'gbaport.analysis.discover'`

- [ ] **Step 3: Implement copy detection and adoption**

In `src/gbaport/analysis/discover.py`, replace:
```python
targets from recorded traces when there are any. Anything else the walk
cannot follow becomes an ``Issue``; nothing in the ROM can make it raise.
"""
```
with:
```python
targets from recorded traces when there are any. Anything else the walk
cannot follow becomes an ``Issue``; nothing in the ROM can make it raise.

Walks also record copies the game makes with constant operands (DMA register
writes, BIOS CpuSet/CpuFastSet) and the code addresses they wanted to reach
outside analysable code, so the analysis can recognise code copied into RAM.
"""
```

In `src/gbaport/analysis/discover.py`, replace:
```python
IRQ_VECTOR = 0x03007FFC  # the BIOS enters the IRQ handler stored here, in ARM state
```
with:
```python
IRQ_VECTOR = 0x03007FFC  # the BIOS enters the IRQ handler stored here, in ARM state
DMA_BASE = 0x040000B0  # DMA0SAD; each of the 4 channels is SAD, DAD, CNT_L, CNT_H (12 bytes)
DMA_END = DMA_BASE + 4 * 12
_DMA_NOT_A_PLAIN_COPY = 0x31E0  # CNT_H: start timing, or a source/destination that is not +1
CPU_SET, CPU_FAST_SET = 0x0B, 0x0C
```

In `src/gbaport/analysis/discover.py`, replace:
```python
@dataclass(frozen=True)
class Issue:
    addr: int
    kind: str
    detail: str
```
with:
```python
@dataclass(frozen=True)
class Issue:
    addr: int
    kind: str
    detail: str


@dataclass(frozen=True)
class RamCopy:
    site: int  # the store or SWI that starts the copy
    src: int
    dst: int
    size: int  # bytes
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    # Indirect site -> targets taken from traces: callees, switch cases, or functions it leaves for.
    traced: dict[int, tuple[int, ...]] = field(default_factory=dict)
```
with:
```python
    # Indirect site -> targets taken from traces: callees, switch cases, or functions it leaves for.
    traced: dict[int, tuple[int, ...]] = field(default_factory=dict)
    copies: list[RamCopy] = field(default_factory=list)
    outside: dict[int, Mode] = field(default_factory=dict)  # code wanted outside the code space
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.issue(
                origin,
                "outside_code",
```
with:
```python
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.ex.outside.setdefault(addr, mode)
            self.issue(
                origin,
                "outside_code",
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        if not self.space.contains(addr, 2):
            self.issue(origin, "outside_code", f"branch target {addr:#010x} is outside the ROM")
            return None
```
with:
```python
        if not self.space.contains(addr, 2):
            self.ex.outside.setdefault(addr, mode)
            self.issue(origin, "outside_code", f"branch target {addr:#010x} is outside the ROM")
            return None
```

In `src/gbaport/analysis/discover.py`, replace:
```python
        lr_set = False  # LR holds a constant this walk wrote and nothing has read since
        while True:
            if addr != start and addr in self.leaders:
                state, history, prev, lr_set = RegState(), [], None, False
            ins = self._take(addr, mode)
            if ins is None:
                return
            self._note_literal(ins)
            self._note_irq_vector(ins, state)
```
with:
```python
        lr_set = False  # LR holds a constant this walk wrote and nothing has read since
        dma: dict[int, int] = {}  # DMA register halfwords this walk wrote with constants
        while True:
            if addr != start and addr in self.leaders:
                state, history, prev, lr_set, dma = RegState(), [], None, False, {}
            ins = self._take(addr, mode)
            if ins is None:
                return
            self._note_literal(ins)
            self._note_irq_vector(ins, state)
            self._note_copy(ins, state, dma)
```

In `src/gbaport/analysis/discover.py`, replace:
```python
    def _note_return_site(self, ins: Instruction, state: RegState) -> None:
```
with:
```python
    def _note_copy(self, ins: Instruction, state: RegState, dma: dict[int, int]) -> None:
        """Record copies started by DMA register writes or CpuSet/CpuFastSet with known operands.

        Conditional stores count as made: start-up code guards the DMA start with
        ``strne`` on the count, and adoption still needs code wanted inside the copy.
        """
        if ins.op is Op.SWI:
            if ins.cond is Cond.AL:
                self._note_cpu_set(ins, state)
            return
        started = []
        for addr, value, size in _stores(ins, state):
            for offset in range(0, size, 2):
                half = addr + offset
                if not DMA_BASE <= half < DMA_END:
                    continue
                if value is None:
                    dma.pop(half, None)
                else:
                    dma[half] = (value >> (8 * offset)) & 0xFFFF
                if (half - DMA_BASE) % 12 == 10:  # CNT_H: this write may start the channel
                    started.append(half - 10)
        for base in started:
            self._note_dma(ins, base, dma)

    def _note_dma(self, ins: Instruction, base: int, dma: dict[int, int]) -> None:
        """Record the transfer of the channel at ``base`` if every register is a known constant."""
        halves = [dma.get(base + offset) for offset in range(0, 12, 2)]
        if None in halves:
            return
        sad_lo, sad_hi, dad_lo, dad_hi, count, control = halves
        if not control & 0x8000 or control & _DMA_NOT_A_PLAIN_COPY:
            return
        limit = 0x10000 if base == DMA_BASE + 3 * 12 else 0x4000  # DMA3 has a 16-bit count
        count = count & (limit - 1) or limit
        unit = 4 if control & 0x0400 else 2
        src, dst = sad_lo | sad_hi << 16, dad_lo | dad_hi << 16
        self.ex.copies.append(RamCopy(ins.addr, src, dst, count * unit))

    def _note_cpu_set(self, ins: Instruction, state: RegState) -> None:
        number = ins.imm >> 16 if ins.mode is Mode.ARM else ins.imm
        if number not in (CPU_SET, CPU_FAST_SET):
            return
        src, dst, control = (state.value(reg, ins) for reg in (0, 1, 2))
        if src is None or dst is None or control is None or control & 0x01000000:
            return  # unknown operands, or a fill
        count = control & 0x1FFFFF
        if number == CPU_FAST_SET:
            size = -(-count // 8) * 32  # whole blocks of eight words
        else:
            size = count * (4 if control & 0x04000000 else 2)
        if size:
            self.ex.copies.append(RamCopy(ins.addr, src, dst, size))

    def _note_return_site(self, ins: Instruction, state: RegState) -> None:
```

Append to `src/gbaport/analysis/discover.py`:
```python
def _stores(ins: Instruction, state: RegState) -> list[tuple[int, int | None, int]]:
    """(address, value or None, size) for each word or halfword store at a known address."""
    if ins.op in (Op.STR, Op.STRH) and ins.rm is None:
        base = state.value(ins.rn, ins)
        if base is None:
            return []
        offset = ins.imm if ins.up else -ins.imm
        size = 4 if ins.op is Op.STR else 2
        value = state.value(ins.rd, ins)
        if value is not None and size == 2:
            value &= 0xFFFF
        return [((base + offset if ins.pre else base) & MASK & -size, value, size)]
    if ins.op is Op.STM and not ins.pre and ins.up:  # stmia
        base = state.value(ins.rn, ins)
        if base is None:
            return []
        return [((base + 4 * i) & MASK, state.value(r, ins), 4) for i, r in enumerate(ins.reglist)]
    return []
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
from gbaport.analysis.config import ConfigError, GameConfig
```
with:
```python
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
FORMAT = "gbaport-analysis/1"
```
with:
```python
FORMAT = "gbaport-analysis/1"
RAM_REGIONS = ((0x02000000, 0x02040000), (0x03000000, 0x03008000))  # EWRAM, IWRAM
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    program: Program
    coverage: Coverage
```
with:
```python
    program: Program
    coverage: Coverage
    ram_code: tuple[RamCode, ...] = ()  # every overlay used: configured, then detected
    detected: tuple[RamCode, ...] = ()  # copies the analysis found and adopted itself
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    space = CodeSpace(rom, config.ram_code)
    for start, end in config.data:
        if not rom.contains(space.canonical(start), end - start):
            raise ConfigError(f"data range [{start:#x}, {end:#x}] is outside the ROM")
    seeds = [(info.header.entry_point or ROM_BASE, Mode.ARM, "seed")]
    seeds += [(addr, Mode.ARM, "seed") for addr in config.entries]
    seeds += [(addr, Mode.THUMB, "seed") for addr in config.thumb_entries]
    seeds += [(blob.ram, blob.mode, "seed") for blob in config.ram_code]
    candidates = pointer_candidates(space) if config.scan_pointers else []
    traced = targets_by_site(list(traces))
    exploration = explore(space, seeds, config, traced=traced, candidates=candidates)
    coverage = _coverage(space, exploration, config)
    return Analysis(info, exploration, build_program(exploration), coverage)
```
with:
```python
    space = CodeSpace(rom, config.ram_code)
    for start, end in config.data:
        if not rom.contains(space.canonical(start), end - start):
            raise ConfigError(f"data range [{start:#x}, {end:#x}] is outside the ROM")
    seeds = [(info.header.entry_point or ROM_BASE, Mode.ARM, "seed")]
    seeds += [(addr, Mode.ARM, "seed") for addr in config.entries]
    seeds += [(addr, Mode.THUMB, "seed") for addr in config.thumb_entries]
    seeds += [(blob.ram, blob.mode, "seed") for blob in config.ram_code]
    traced = targets_by_site(list(traces))
    detected: tuple[RamCode, ...] = ()
    while True:  # each round adopts copies that hold code the last round could not reach
        space = CodeSpace(rom, config.ram_code + detected)
        candidates = pointer_candidates(space) if config.scan_pointers else []
        exploration = explore(space, seeds, config, traced=traced, candidates=candidates)
        found = _copied_code(exploration, space, config.ram_code + detected)
        if not found:
            break
        detected += found
    coverage = _coverage(space, exploration, config)
    program = build_program(exploration)
    return Analysis(info, exploration, program, coverage, config.ram_code + detected, detected)


def _copied_code(
    ex: Exploration, space: CodeSpace, known: tuple[RamCode, ...]
) -> tuple[RamCode, ...]:
    """Copies from ROM into RAM that cover code the walk wanted to reach, as new overlays."""
    found: list[RamCode] = []
    for copy in sorted(ex.copies, key=lambda c: (c.site, c.dst)):
        end = copy.dst + copy.size
        wanted = sorted(addr for addr in ex.outside if copy.dst <= addr < end)
        if not wanted or not any(lo <= copy.dst and end <= hi for lo, hi in RAM_REGIONS):
            continue
        blob = RamCode(space.canonical(copy.src), copy.dst, copy.size, ex.outside[wanted[0]])
        try:
            CodeSpace(space.rom, (*known, *found, blob))
        except ConfigError:
            continue  # not a ROM source, or overlapping an overlay already in use
        found.append(blob)
    return tuple(found)
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
        "traced": [
            {"site": _hex(site), "targets": [_hex(t) for t in targets]}
            for site, targets in sorted(ex.traced.items())
        ],
```
with:
```python
        "traced": [
            {"site": _hex(site), "targets": [_hex(t) for t in targets]}
            for site, targets in sorted(ex.traced.items())
        ],
        "ram_code": [
            {
                "rom": _hex(blob.rom),
                "ram": _hex(blob.ram),
                "size": blob.size,
                "mode": blob.mode.value,
                "detected": blob in analysis.detected,
            }
            for blob in analysis.ram_code
        ],
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
```
with:
```python
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
    configured = len(analysis.ram_code) - len(analysis.detected)
```

In `src/gbaport/analysis/analyze.py`, replace:
```python
        ("jump tables", str(len(ex.tables))),
```
with:
```python
        ("jump tables", str(len(ex.tables))),
        ("ram code", f"{configured} configured, {len(analysis.detected)} detected"),
```

In `src/gbaport/analysis/effects.py`, replace:
```python
from dataclasses import dataclass, field
```
with:
```python
import operator
from dataclasses import dataclass, field
```

In `src/gbaport/analysis/effects.py`, replace:
```python
_SINGLE_DEST = frozenset({Op.MUL, Op.MLA, Op.SWP, Op.SWPB, Op.MRS}) | _LOADS
```
with:
```python
_SINGLE_DEST = frozenset({Op.MUL, Op.MLA, Op.SWP, Op.SWPB, Op.MRS}) | _LOADS
_BINARY = {
    Op.ADD: operator.add,
    Op.SUB: operator.sub,
    Op.ORR: operator.or_,
    Op.AND: operator.and_,
    Op.EOR: operator.xor,
    Op.BIC: lambda a, b: a & ~b,
}
```

In `src/gbaport/analysis/effects.py`, replace:
```python
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
```
with:
```python
    Covers literal loads, and MOV/MVN/ADD/SUB/ORR/AND/EOR/BIC with immediate or
    known-register operands (immediate shifts included). The condition code is
    not checked.
    """
    op = ins.op
    if op is Op.LDR:
        if ins.rn == PC and ins.target is not None and space.contains(ins.target, 4):
            return space.read32(ins.target)
        return None
    if op not in _BINARY and op not in (Op.MOV, Op.MVN):
        return None
```

In `src/gbaport/analysis/effects.py`, replace:
```python
    base = state.value(ins.rn, ins)
    if base is None:
        return None
    return (base + operand) & MASK if op is Op.ADD else (base - operand) & MASK
```
with:
```python
    base = state.value(ins.rn, ins)
    if base is None:
        return None
    return _BINARY[op](base, operand) & MASK
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 446 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis tests
git commit -m "feat: detect and adopt code copied into RAM"
```

---

### Task 5: GDB remote protocol client

**Files:**
- Create: `src/gbaport/tracing/__init__.py`, `src/gbaport/tracing/gdb.py`
- Test: `tests/tracing/test_gdb.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class GdbError(ConnectionError)` and `REPLY_TIMEOUT = 5.0`.
  - `Transport` protocol: `send(bytes)`, `recv(timeout) -> bytes` (`b""` on timeout), `close()`.
  - `SocketTransport.connect(host, port, timeout=REPLY_TIMEOUT)`.
  - `@dataclass(frozen=True) Stop(signal: int, exited: bool = False)`.
  - `@dataclass(frozen=True) Registers(r: tuple[int, ...], cpsr: int)` with `pc`, `lr`, `thumb`.
  - `packet(payload) -> bytes`.
  - `GdbClient(transport)` with `handshake()`, `request(payload, timeout) -> str`, `registers()`, `set_breakpoint(addr, size)`, `clear_breakpoint(addr, size)`, `cont()`, `step(timeout) -> Stop | None`, `interrupt()`, `wait_stop(timeout) -> Stop | None` and `close()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tracing/test_gdb.py`:
```python
import socket

import pytest

from gbaport.tracing.gdb import (
    GdbClient,
    GdbError,
    Registers,
    SocketTransport,
    Stop,
    packet,
)


class Wire:
    """A transport that hands out canned chunks and records what the client sent."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)
        self.sent = bytearray()

    def send(self, data: bytes) -> None:
        self.sent += data

    def recv(self, timeout: float) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        pass


def reply(payload: str) -> bytes:
    return b"+" + packet(payload)


def test_packet_checksum():
    assert packet("g") == b"$g#67"
    assert packet("OK") == b"$OK#9a"


def test_reply_split_across_reads_with_stray_acks():
    whole = reply("OK")
    wire = Wire(b"++" + whole[:3], whole[3:])
    GdbClient(wire).set_breakpoint(0x08000100, 2)
    assert wire.sent == packet("Z0,8000100,2") + b"+"


def test_error_reply_raises():
    with pytest.raises(GdbError, match="failed: 'E07'"):
        GdbClient(Wire(reply("E07"))).clear_breakpoint(0x08000100, 4)


def test_bad_checksum_is_refused():
    wire = Wire(b"$OK#00")
    with pytest.raises(GdbError, match="bad checksum"):
        GdbClient(wire).request("g")
    assert wire.sent.endswith(b"-")


def test_no_reply_times_out():
    with pytest.raises(GdbError, match="no reply"):
        GdbClient(Wire()).request("g", timeout=0.01)


def test_registers_are_little_endian_words():
    words = list(range(15)) + [0x08000123, 0x6000003F]
    text = "".join(word.to_bytes(4, "little").hex() for word in words)
    regs = GdbClient(Wire(reply(text))).registers()
    assert regs == Registers(tuple(words[:16]), 0x6000003F)
    assert (regs.pc, regs.lr, regs.thumb) == (0x08000123, 14, True)


def test_short_register_reply_is_an_error():
    with pytest.raises(GdbError, match="unexpected register reply"):
        GdbClient(Wire(reply("E01"))).registers()


@pytest.mark.parametrize(
    "payload,stop",
    [
        ("S05k", Stop(5)),  # what mGBA sends for a breakpoint without swbreak support
        ("T05swbreak:;", Stop(5)),
        ("S02", Stop(2)),
        ("W00", Stop(0, exited=True)),
        ("X09", Stop(9, exited=True)),
    ],
)
def test_stop_replies(payload, stop):
    assert GdbClient(Wire(reply(payload))).wait_stop(0.01) == stop


def test_running_game_gives_no_stop():
    assert GdbClient(Wire()).wait_stop(0.01) is None


def test_unexpected_stop_reply_is_an_error():
    with pytest.raises(GdbError, match="unexpected stop reply"):
        GdbClient(Wire(reply("OK"))).wait_stop(0.01)


def test_escaped_bytes_are_decoded():
    escaped = b"a}" + bytes([ord("}") ^ 0x20]) + b"b"
    raw = b"$" + escaped + b"#" + f"{sum(escaped) & 0xFF:02x}".encode()
    assert GdbClient(Wire(raw)).request("qX") == "a}b"


def test_cont_step_and_interrupt_bytes():
    wire = Wire(reply("S05"))
    client = GdbClient(wire)
    client.cont()
    client.interrupt()
    assert client.step(0.01) == Stop(5)
    assert wire.sent == packet("c") + b"\x03" + packet("s") + b"+"


def test_socket_transport():
    near, far = socket.socketpair()
    transport = SocketTransport(near)
    far.sendall(reply("OK"))
    assert transport.recv(1.0) == reply("OK")
    assert transport.recv(0.01) == b""
    far.close()
    with pytest.raises(GdbError, match="closed the connection"):
        transport.recv(1.0)
    transport.close()


def test_connect_failure_says_how_to_start_the_server():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(GdbError, match="Start GDB server"):
        SocketTransport.connect("127.0.0.1", port, timeout=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tracing/test_gdb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.tracing'`

- [ ] **Step 3: Write the client**

Create `src/gbaport/tracing/__init__.py`:
```python
"""Recording execution traces from a game running in an emulator (a dev-time tool)."""
```

Create `src/gbaport/tracing/gdb.py`:
```python
"""A small GDB remote serial protocol client, enough to drive mGBA's GDB server.

mGBA (Tools > Start GDB server, default port 2345) speaks a subset of the
protocol: ``g`` returns r0-r15 and the CPSR, ``Z0``/``z0`` set and clear
breakpoints, ``c`` and ``s`` continue and step, and a raw 0x03 byte stops a
running game. It acknowledges every packet with ``+`` (even in no-ack mode),
so the client skips stray ``+`` bytes, and it may answer a breakpoint with
``S05k``, so stop replies are read by their first three characters only.
"""

import socket
from dataclasses import dataclass
from typing import Protocol

REPLY_TIMEOUT = 5.0  # seconds to wait for the answer to a request


class GdbError(ConnectionError):
    """The GDB server went away, timed out or answered something unexpected."""


class Transport(Protocol):
    def send(self, data: bytes) -> None: ...

    def recv(self, timeout: float) -> bytes:
        """Bytes that arrived within ``timeout`` seconds (b"" if none); raises when closed."""
        ...

    def close(self) -> None: ...


class SocketTransport:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    @classmethod
    def connect(cls, host: str, port: int, timeout: float = REPLY_TIMEOUT) -> "SocketTransport":
        try:
            return cls(socket.create_connection((host, port), timeout=timeout))
        except OSError as exc:
            raise GdbError(
                f"cannot connect to a GDB server at {host}:{port} ({exc}); "
                "in mGBA use Tools > Start GDB server"
            ) from None

    def send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise GdbError(f"connection lost: {exc}") from None

    def recv(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except TimeoutError:
            return b""
        except OSError as exc:
            raise GdbError(f"connection lost: {exc}") from None
        if not data:
            raise GdbError("the GDB server closed the connection")
        return data

    def close(self) -> None:
        self.sock.close()


@dataclass(frozen=True)
class Stop:
    signal: int  # 5 = trap (breakpoint or step), 2 = interrupt
    exited: bool = False  # the game (or emulator core) ended


@dataclass(frozen=True)
class Registers:
    r: tuple[int, ...]  # r0-r15; r15 is the address of the next instruction to run
    cpsr: int

    @property
    def pc(self) -> int:
        return self.r[15]

    @property
    def lr(self) -> int:
        return self.r[14]

    @property
    def thumb(self) -> bool:
        return bool(self.cpsr & 0x20)


def packet(payload: str) -> bytes:
    data = payload.encode("ascii")
    return b"$" + data + b"#" + f"{sum(data) & 0xFF:02x}".encode("ascii")


class GdbClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.buffer = bytearray()

    def handshake(self) -> None:
        self.request("qSupported:swbreak+;hwbreak+")

    def request(self, payload: str, timeout: float = REPLY_TIMEOUT) -> str:
        self.transport.send(packet(payload))
        reply = self._receive(timeout)
        if reply is None:
            raise GdbError(f"no reply to {payload!r} within {timeout:g}s")
        return reply

    def registers(self) -> Registers:
        reply = self.request("g")
        if len(reply) < 17 * 8:
            raise GdbError(f"unexpected register reply {reply[:20]!r}")
        words = [int.from_bytes(bytes.fromhex(reply[i : i + 8]), "little") for i in range(0, 136, 8)]
        return Registers(tuple(words[:16]), words[16])

    def set_breakpoint(self, addr: int, size: int) -> None:
        self._expect_ok(f"Z0,{addr:x},{size}")

    def clear_breakpoint(self, addr: int, size: int) -> None:
        self._expect_ok(f"z0,{addr:x},{size}")

    def cont(self) -> None:
        """Resume; the stop reply comes later through ``wait_stop``."""
        self.transport.send(packet("c"))

    def step(self, timeout: float = REPLY_TIMEOUT) -> Stop | None:
        self.transport.send(packet("s"))
        return self.wait_stop(timeout)

    def interrupt(self) -> None:
        self.transport.send(b"\x03")

    def wait_stop(self, timeout: float) -> Stop | None:
        """The next stop reply, or None if the game is still running after ``timeout``."""
        reply = self._receive(timeout)
        if reply is None:
            return None
        if reply[:1] in ("W", "X"):
            return Stop(int(reply[1:3] or "0", 16), exited=True)
        if reply[:1] in ("S", "T") and len(reply) >= 3:
            return Stop(int(reply[1:3], 16))
        raise GdbError(f"unexpected stop reply {reply!r}")

    def close(self) -> None:
        self.transport.close()

    def _expect_ok(self, payload: str) -> None:
        reply = self.request(payload)
        if reply != "OK":
            raise GdbError(f"{payload!r} failed: {reply!r}")

    def _receive(self, timeout: float) -> str | None:
        """The payload of the next packet (acknowledged), or None if none arrives in time."""
        while True:
            parsed = self._take_packet()
            if parsed is not None:
                return parsed
            data = self.transport.recv(timeout)
            if not data:
                return None
            self.buffer += data

    def _take_packet(self) -> str | None:
        start = self.buffer.find(b"$")
        if start < 0:
            self.buffer.clear()  # only acks (or noise) so far
            return None
        end = self.buffer.find(b"#", start)
        if end < 0 or len(self.buffer) < end + 3:
            del self.buffer[:start]
            return None
        body = bytes(self.buffer[start + 1 : end])
        checksum = bytes(self.buffer[end + 1 : end + 3])
        del self.buffer[: end + 3]
        if f"{sum(body) & 0xFF:02x}".encode("ascii") != checksum.lower():
            self.transport.send(b"-")
            raise GdbError(f"bad checksum on packet {body[:20]!r}")
        self.transport.send(b"+")
        return _unescape(body).decode("ascii", errors="replace")


def _unescape(body: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for byte in body:
        if escaped:
            out.append(byte ^ 0x20)
            escaped = False
        elif byte == 0x7D:  # '}'
            escaped = True
        else:
            out.append(byte)
    return bytes(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tracing/test_gdb.py -v && uv run ruff check src tests`
Expected: 18 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/tracing tests/tracing/test_gdb.py
git commit -m "feat: GDB remote protocol client for mGBA"
```

---

### Task 6: Trace session

**Files:**
- Create: `src/gbaport/tracing/session.py`, `tests/gdbfake.py`
- Modify: `tests/progkit.py` (append `SESSION_PROGRAM`)
- Test: `tests/tracing/test_session.py`

**Interfaces:**
- Consumes:
  - `GdbClient`, `GdbError` (Task 5).
  - `Hit`, `Trace` (Task 1).
  - `Exploration` with `entry_kinds`, `issues`, `traced`, `instructions` (Tasks 2–4).
  - `analyze_rom(rom, traces=)` (Task 2).
- Produces:
  - `MAX_BREAKPOINTS = 256`.
  - `@dataclass(frozen=True) Site(addr, mode, veneer)` with `size`.
  - `breakpoint_sites(ex) -> list[Site]`.
  - `TraceSession(client, analyze, trace, *, save, report, reanalyze_every=5.0, clock=time.monotonic)` with `run(seconds=None)`.
  - `tests/gdbfake.py`: `State`, `FakeGdbServer(states, *, endless=False, lose_at=None)`, `serve(server) -> port`, `SESSION_RUN`.
- Behaviour:
  - The trace is saved at every refresh and when the session ends, even when the connection is lost.
  - After a time limit or Ctrl+C, breakpoints are cleared and the game resumes.
  - When the game exits, nothing is sent.

- [ ] **Step 1: Write the failing tests**

Create `tests/gdbfake.py`:
```python
"""A scripted stand-in for mGBA's GDB server, used as a transport in tests.

The fake "runs" a fixed list of CPU states, each the address of the next
instruction with its mode and LR. ``c`` moves to the next state whose address
has a breakpoint, ``s`` moves one state, and running off the end exits the
game (or, with ``endless``, keeps it running until interrupted). Replies
imitate mGBA, including its ``+`` acks, ``S05k`` stops and ``E07`` errors.
"""

import socket
import threading
from dataclasses import dataclass

from gbaport.tracing.gdb import GdbError, packet


@dataclass(frozen=True)
class State:
    pc: int
    thumb: bool = True
    lr: int = 0


class FakeGdbServer:
    def __init__(
        self, states: list[State], *, endless: bool = False, lose_at: int | None = None
    ) -> None:
        self.states = states
        self.index = 0
        self.endless = endless
        self.lose_at = lose_at  # index whose arrival drops the connection
        self.breakpoints: dict[int, int] = {}
        self.running = False
        self.lost = False
        self.pending = bytearray()
        self.out = bytearray()

    def send(self, data: bytes) -> None:
        if self.lost:
            raise GdbError("connection lost")
        self.pending += data
        while self.pending:
            first = self.pending[0]
            if first in b"+-":
                del self.pending[:1]
            elif first == 0x03:
                del self.pending[:1]
                if self.running:
                    self.running = False
                    self._reply("S02")
            else:
                end = self.pending.index(b"#")
                payload = self.pending[1:end].decode()
                del self.pending[: end + 3]
                self.out += b"+"
                self._handle(payload)

    def recv(self, timeout: float) -> bytes:
        if self.running:
            self._run()
        if self.lost:
            raise GdbError("connection lost")
        data = bytes(self.out)
        self.out.clear()
        return data

    def close(self) -> None:
        pass

    def _reply(self, payload: str) -> None:
        self.out += packet(payload)

    def _handle(self, payload: str) -> None:
        if payload.startswith("qSupported"):
            self._reply("PacketSize=1000;swbreak+;hwbreak+")
        elif payload == "g":
            state = self.states[min(self.index, len(self.states) - 1)]
            words = [0] * 14 + [state.lr, state.pc, 0x3F if state.thumb else 0x1F]
            self._reply("".join(word.to_bytes(4, "little").hex() for word in words))
        elif payload[:3] in ("Z0,", "z0,"):
            _, addr, size = payload.split(",")
            if payload[0] == "Z":
                self.breakpoints[int(addr, 16)] = int(size)
            else:
                del self.breakpoints[int(addr, 16)]
            self._reply("OK")
        elif payload == "c":
            self.running = True
        elif payload == "s":
            self.index += 1
            self._reply("S05" if self.index < len(self.states) else "W00")
        else:
            self._reply("E07")

    def _run(self) -> None:
        if self.index >= len(self.states):
            return  # endless: still running past the last scripted state
        self.index += 1
        while self.index < len(self.states) and self.states[self.index].pc not in self.breakpoints:
            if self.index == self.lose_at:
                self.lost = True
                return
            self.index += 1
        if self.index == self.lose_at:
            self.lost = True
        elif self.index < len(self.states):
            self.running = False
            self._reply("S05k")
        elif not self.endless:
            self.running = False
            self._reply("W00")


def serve(server: FakeGdbServer) -> int:
    """Put ``server`` behind a real TCP socket on a free local port and return the port."""
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def bridge() -> None:
        connection, _ = listener.accept()
        listener.close()
        connection.settimeout(0.02)
        with connection:
            while True:
                try:
                    data = connection.recv(4096)
                    if not data:
                        return
                    server.send(data)
                except TimeoutError:
                    pass
                except OSError:
                    return
                out = server.recv(0)
                if out:
                    connection.sendall(out)

    threading.Thread(target=bridge, daemon=True).start()
    return port


# What the game does: reach the veneer from the bl, run target, reach its bx r0, go to second.
SESSION_RUN = [
    State(0x080000C0, thumb=False),
    State(0x080000D4, thumb=False, lr=0x080000CC),
    State(0x080000D8, thumb=False, lr=0x080000CC),
    State(0x080000DC, thumb=False),
    State(0x080000E0, thumb=False),
    State(0x080000E4, thumb=False, lr=0x080000E8),
    State(0x080000F0, thumb=False, lr=0x080000E8),
    State(0x080000E8, thumb=False),
]
```

Create `tests/tracing/test_session.py`:
```python
import itertools

import pytest
from gdbfake import SESSION_RUN, FakeGdbServer, State
from progkit import SESSION_PROGRAM, program_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, GdbError
from gbaport.tracing.session import Site, TraceSession, breakpoint_sites

ROM = program_rom(SESSION_PROGRAM)
SHA1 = inspect_rom(ROM).sha1

def analyze(trace):
    return analyze_rom(ROM, traces=(trace,)).exploration


def session(server, trace=None, **options):
    saved = []
    options.setdefault("reanalyze_every", 0)
    traced = TraceSession(
        GdbClient(server), analyze, trace or Trace(SHA1), save=saved.append, **options
    )
    return traced, saved


def test_breakpoint_sites():
    assert breakpoint_sites(analyze(Trace(SHA1))) == [Site(0x080000D4, Mode.ARM, True)]
    after = analyze(Trace(SHA1, {Hit(0x080000C8, 0x080000D8, Mode.ARM)}))
    assert breakpoint_sites(after) == [
        Site(0x080000D4, Mode.ARM, True),
        Site(0x080000E4, Mode.ARM, False),
    ]


def test_records_calls_and_follows_new_code():
    server = FakeGdbServer(SESSION_RUN)
    traced, saved = session(server)
    traced.run()
    assert traced.trace.hits == {
        Hit(0x080000C8, 0x080000D8, Mode.ARM),  # recorded at the bl, not the veneer
        Hit(0x080000E4, 0x080000F0, Mode.ARM),  # a site that only existed after re-analysis
    }
    assert saved[-1] is traced.trace
    assert server.breakpoints == {0x080000D4: 4, 0x080000E4: 4}  # the game exited


def test_steps_over_a_site_that_lands_on_another_site():
    known = Trace(SHA1, {Hit(0x080000C8, 0x080000D8, Mode.ARM)})
    run = [
        State(0x080000C0, thumb=False),
        State(0x080000D4, thumb=False, lr=0x080000CC),
        State(0x080000E4, thumb=False, lr=0x080000E8),
        State(0x080000F0, thumb=False),
    ]
    traced, _ = session(FakeGdbServer(run), known)
    traced.run()
    assert Hit(0x080000C8, 0x080000E4, Mode.ARM) in traced.trace.hits
    assert Hit(0x080000E4, 0x080000F0, Mode.ARM) in traced.trace.hits


def test_time_limit_stops_and_releases_the_game():
    server = FakeGdbServer([State(0x080000C0, thumb=False)], endless=True)
    ticks = itertools.count()
    traced, saved = session(server, clock=lambda: float(next(ticks)))
    traced.run(seconds=3)
    assert server.breakpoints == {}
    assert server.running  # left running in mGBA
    assert saved


def test_lost_connection_still_saves_the_trace():
    server = FakeGdbServer(SESSION_RUN, lose_at=3)
    traced, saved = session(server, reanalyze_every=1000)
    with pytest.raises(GdbError, match="connection lost"):
        traced.run()
    assert saved[-1].hits == {Hit(0x080000C8, 0x080000D8, Mode.ARM)}


def test_progress_is_reported():
    lines = []
    traced, _ = session(FakeGdbServer(SESSION_RUN), report=lines.append)
    traced.run()
    assert lines[0] == "0 hits (+0), 1 breakpoints"
    assert lines[-1].endswith("2 breakpoints")
```

Append to `tests/progkit.py`:
```python
# ARM: main calls an unknown function pointer through a veneer; the function
# it reaches (target) makes a second unknown call with the `mov lr, pc` idiom.
#   c8 bl via_r3   d4 via_r3   d8 target   e4 its bx r0   f0 second
SESSION_PROGRAM = """
main:
    push {lr}
    ldr r3, [r0]
    bl via_r3
    pop {lr}
    bx lr
via_r3:
    bx r3
target:
    push {lr}
    ldr r0, [r1]
    mov lr, pc
    bx r0
    pop {lr}
    bx lr
second:
    bx lr
"""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/tracing/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gbaport.tracing.session'`

- [ ] **Step 3: Write the session**

Create `src/gbaport/tracing/session.py`:
```python
"""Record where indirect branches and calls go while the game runs in mGBA.

Breakpoints go on every indirect site the analysis could not resolve: each
``bx rN`` call veneer, each unresolved ``bx``/``mov pc``/``ldr pc``, and each
jump table without a bound. When the game stops on one, the session steps that
single instruction and records where it went. A call through a veneer is
recorded at the ``bl`` that called the veneer (found from LR), so it resolves
per call site. While the game runs, new targets are fed back into the
analysis and the breakpoints follow the code that becomes reachable.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from gbaport.analysis.discover import Exploration
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode, Op
from gbaport.tracing.gdb import GdbClient

MAX_BREAKPOINTS = 256  # mGBA checks every instruction against them; keep the game fast
STEP_TIMEOUT = 1.0
POLL = 0.25  # seconds between checks for the end of the session while the game runs
_SITE_ISSUES = ("unresolved_jump", "unbounded_table", "unresolved_call")


@dataclass(frozen=True)
class Site:
    addr: int
    mode: Mode
    veneer: bool  # a shared ``bx rN`` veneer: record the calling ``bl`` instead

    @property
    def size(self) -> int:
        return 2 if self.mode is Mode.THUMB else 4


def breakpoint_sites(ex: Exploration) -> list[Site]:
    """Indirect sites worth a breakpoint: veneers first, then the rest by address."""
    veneers = sorted(addr for addr, kind in ex.entry_kinds.items() if kind == "veneer")
    others = {issue.addr for issue in ex.issues if issue.kind in _SITE_ISSUES}
    others |= set(ex.traced)  # a traced site may still go somewhere not seen yet
    others = {
        addr
        for addr in others - set(veneers)
        if addr in ex.instructions and ex.instructions[addr].op is not Op.BL
    }
    sites = [Site(a, ex.instructions[a].mode, True) for a in veneers if a in ex.instructions]
    sites += [Site(a, ex.instructions[a].mode, False) for a in sorted(others)]
    return sites[:MAX_BREAKPOINTS]


class TraceSession:
    def __init__(
        self,
        client: GdbClient,
        analyze: Callable[[Trace], Exploration],
        trace: Trace,
        *,
        save: Callable[[Trace], None] = lambda trace: None,
        report: Callable[[str], None] = lambda line: None,
        reanalyze_every: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.analyze = analyze  # analysis with the traces recorded so far
        self.trace = trace
        self.save = save
        self.report = report
        self.reanalyze_every = reanalyze_every
        self.clock = clock
        self.sites: dict[int, Site] = {}
        self.ex = Exploration()
        self.new_hits = 0
        self.last_refresh = 0.0

    def run(self, seconds: float | None = None) -> None:
        """Trace until ``seconds`` pass, the game exits, or Ctrl+C; the trace is always saved."""
        deadline = None if seconds is None else self.clock() + seconds
        running = exited = False
        try:
            self.client.handshake()
            self.client.interrupt()  # mGBA may be running already; stop it to set breakpoints
            self.client.wait_stop(STEP_TIMEOUT)
            self._refresh()
            while True:
                self.client.cont()
                running = True
                stop = self._wait(deadline)
                running = False
                if stop is None or stop.exited:
                    exited = stop is not None
                    break
                self._handle_stop()
                if self.new_hits and self.clock() - self.last_refresh >= self.reanalyze_every:
                    self._refresh()
        except KeyboardInterrupt:
            if running:
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
        finally:
            self.save(self.trace)
        if not exited:
            self._release()

    def _wait(self, deadline: float | None):
        """The next stop, or None once the deadline passes (the game is then stopped)."""
        while True:
            stop = self.client.wait_stop(POLL)
            if stop is not None:
                return stop
            if deadline is not None and self.clock() >= deadline:
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
                return None

    def _handle_stop(self) -> None:
        regs = self.client.registers()
        for _ in range(64):  # never resume from a breakpoint: step over each one first
            site = self.sites.get(regs.pc)
            if site is None:
                return
            origin = self._call_site(site, regs.lr)
            if self.client.step(STEP_TIMEOUT) is None:  # stepped into a BIOS call
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
            regs = self.client.registers()
            mode = Mode.THUMB if regs.thumb else Mode.ARM
            if self.trace.add(Hit(origin, regs.pc, mode)):
                self.new_hits += 1
            if regs.pc == site.addr:
                return

    def _call_site(self, site: Site, lr: int) -> int:
        """The ``bl`` that called a veneer, or the site itself."""
        if site.veneer:
            caller = (lr & ~1) - 4
            ins = self.ex.instructions.get(caller)
            if ins is not None and ins.op is Op.BL:
                return caller
        return site.addr

    def _refresh(self) -> None:
        """Re-analyse with the hits so far and move the breakpoints to the new sites."""
        self.ex = self.analyze(self.trace)
        wanted = {site.addr: site for site in breakpoint_sites(self.ex)}
        for addr in sorted(self.sites.keys() - wanted.keys()):
            self.client.clear_breakpoint(addr, self.sites[addr].size)
        for addr in sorted(wanted.keys() - self.sites.keys()):
            self.client.set_breakpoint(addr, wanted[addr].size)
        self.sites = wanted
        self.report(f"{len(self.trace.hits)} hits (+{self.new_hits}), {len(wanted)} breakpoints")
        self.new_hits = 0
        self.last_refresh = self.clock()
        self.save(self.trace)

    def _release(self) -> None:
        """Clear the breakpoints and let the game run on."""
        for addr, site in sorted(self.sites.items()):
            self.client.clear_breakpoint(addr, site.size)
        self.sites = {}
        self.client.cont()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/tracing -v && uv run ruff check src tests`
Expected: 24 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/tracing/session.py tests/gdbfake.py tests/progkit.py tests/tracing/test_session.py
git commit -m "feat: trace session with live re-analysis"
```

---

### Task 7: `gbaport trace`, README and spec

**Files:**
- Modify: `src/gbaport/cli.py`, `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`
- Test: `tests/test_trace_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `gbaport trace ROM [--config PATH] [--out PATH] [--trace PATH]... [--host H] [--port N] [--seconds S] [--reanalyze-every S]`.
  - `--out` defaults to `games/<game_code>/traces/mgba.trace`, and an existing file is extended.
  - Other trace files are passed to the analysis unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trace_cli.py`:
```python
from gdbfake import SESSION_RUN, FakeGdbServer, serve
from progkit import SESSION_PROGRAM, program_rom

from gbaport.analysis.traces import Hit, load_trace
from gbaport.cli import main
from gbaport.isa.model import Mode


def test_trace_records_into_the_games_folder_and_feeds_analyze(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(program_rom(SESSION_PROGRAM).data)
    port = serve(FakeGdbServer(SESSION_RUN))
    args = ["trace", str(rom), "--port", str(port), "--seconds", "30", "--reanalyze-every", "0"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"connected to 127.0.0.1:{port}" in out
    assert "wrote games" in out and "(2 hits)" in out
    trace = load_trace(tmp_path / "games" / "ATST" / "traces" / "mgba.trace")
    assert trace.hits == {
        Hit(0x080000C8, 0x080000D8, Mode.ARM),
        Hit(0x080000E4, 0x080000F0, Mode.ARM),
    }
    assert main(["analyze", str(rom)]) == 0
    assert "seed 1, trace 2, veneer 1" in capsys.readouterr().out


def test_trace_resumes_an_existing_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(program_rom(SESSION_PROGRAM).data)
    out = tmp_path / "run.trace"
    for _ in range(2):
        port = serve(FakeGdbServer(SESSION_RUN))
        args = ["trace", str(rom), "--port", str(port), "--out", str(out), "--reanalyze-every", "0"]
        assert main(args) == 0
    assert len(load_trace(out).hits) == 2
    assert "(2 hits)" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trace_cli.py -v`
Expected: FAIL — `SystemExit: 2` (argparse: invalid choice 'trace')

- [ ] **Step 3: Add the command and the docs**

In `src/gbaport/cli.py`, replace:
```python
from gbaport.analysis.traces import default_trace_paths, load_trace
```
with:
```python
from gbaport.analysis.traces import Trace, default_trace_paths, load_trace, save_trace
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.rom.info import inspect_rom
```
with:
```python
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, SocketTransport
from gbaport.tracing.session import TraceSession
```

In `src/gbaport/cli.py`, replace:
```python
    _add_analyze_command(commands)
```
with:
```python
    _add_analyze_command(commands)
    _add_trace_command(commands)
```

In `src/gbaport/cli.py`, replace:
```python
def main(argv: list[str] | None = None) -> int:
```
with:
```python
def _add_trace_command(commands) -> None:
    trace = commands.add_parser(
        "trace", help="record indirect branch targets from a game running in mGBA"
    )
    trace.add_argument("rom", help="path to the .gba file loaded in mGBA")
    trace.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    trace.add_argument(
        "--out", help="trace file to extend (default: games/<game_code>/traces/mgba.trace)"
    )
    trace.add_argument(
        "--trace",
        action="append",
        default=[],
        help="other trace files to import (games/<game_code>/traces/*.trace are read too)",
    )
    trace.add_argument("--host", default="127.0.0.1", help="GDB server host (default 127.0.0.1)")
    trace.add_argument("--port", type=int, default=2345, help="GDB server port (default 2345)")
    trace.add_argument("--seconds", type=float, help="stop after this long (default: Ctrl+C)")
    trace.add_argument(
        "--reanalyze-every",
        type=float,
        default=5.0,
        help="seconds between re-analyses that move breakpoints to new code (default 5)",
    )
    trace.set_defaults(handler=_run_trace)


def _run_trace(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code
    config_path = args.config or default_config_path(game_code)
    config = load_config(config_path) if config_path else GameConfig()
    out = Path(args.out) if args.out else Path("games") / game_code / "traces" / "mgba.trace"
    recorded = load_trace(out) if out.exists() else Trace(inspect_rom(rom).sha1)
    others = [*default_trace_paths(game_code), *map(Path, args.trace)]
    fixed = tuple(load_trace(path) for path in others if path.resolve() != out.resolve())

    def analyze(trace: Trace):
        return analyze_rom(rom, config, (*fixed, trace)).exploration

    client = GdbClient(SocketTransport.connect(args.host, args.port))
    print(f"connected to {args.host}:{args.port}; play the game, press Ctrl+C to stop")
    session = TraceSession(
        client,
        analyze,
        recorded,
        save=lambda trace: save_trace(trace, out),
        report=print,
        reanalyze_every=args.reanalyze_every,
    )
    try:
        session.run(args.seconds)
    finally:
        client.close()
    print(f"wrote {out} ({len(recorded.hits)} hits)")
    return 0


def main(argv: list[str] | None = None) -> int:
```

In `README.md`, replace:
```markdown
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
```
with:
```markdown
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA (0.10 or newer, dev machine only) and records where its indirect calls
and jumps go:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
2. Run `uv run gbaport trace roms/mygame.gba` and play: menus, levels, cutscenes.
   Breakpoints follow newly found code every few seconds.
3. Press Ctrl+C. The trace is saved to `games/<game_code>/traces/mgba.trace`
   (addresses only, safe to commit) and `gbaport analyze` reads it automatically.
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
```
with:
```markdown
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
scan_pointers = true           # guess entries from ROM words pointing at function starts
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
````markdown
[timing]
model = "block"                # "block" (default) or "frame"
```
````
with:
````markdown
[timing]
model = "block"                # "block" (default) or "frame"
```

Traces recorded with `gbaport trace` live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
CpuSet is detected and needs a `[[ram_code]]` entry only when detection misses it.
````

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
| P2 Code discovery | `gbaport analyze` → `analysis.json` (functions, blocks, modes, jump tables, literal pools, RAM-copied code); `game.toml` loader; trace import | Synthetic programs give exact expected CFGs; coverage report on a real dump | P1 |
```
with:
```markdown
| P2 Code discovery | `gbaport analyze` → `analysis.json` (functions, blocks, modes, jump tables, literal pools, RAM-copied code); `game.toml` loader | Synthetic programs give exact expected CFGs; coverage report on a real dump | P1 |
| P2b Discovery coverage | Pointer scan, RAM-copy detection, trace files and their import, `gbaport trace` through mGBA's GDB server | Synthetic programs and a fake GDB server give exact results; dump coverage report before and after | P2 |
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
```
with:
```markdown
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 472 passed (396 from Plans 1–2 plus 76 new); ruff clean.

- [ ] **Step 5: Smoke-test on the real dump**

Run: `uv run gbaport analyze roms/mygame.gba --issues 0 --out build/analysis.json`

Expected for BT4E (validated before this plan was approved):
- About 470 functions.
- `found by` includes `pointer` (about 185) and `irq 1`.
- `ram code     0 configured, 1 detected`, with `build/analysis.json` showing `{"rom": "0x087fd298", "ram": "0x03000000", "size": 6484, "mode": "arm", "detected": true}`.
- No `outside_code` issues.

Record the numbers in the ledger.

If mGBA is installed:
1. Open the ROM and choose Tools > Start GDB server.
2. Run `uv run gbaport trace roms/mygame.gba`, play for a few minutes, then press Ctrl+C.
3. Run `analyze` again and record the function count and the `trace` count.

If mGBA is not installed, record that the manual trace step was skipped.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/cli.py README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md tests/test_trace_cli.py
git commit -m "feat: gbaport trace records indirect targets from mGBA"
```

---

## Done criteria for Plan 2b

- `uv run pytest` passes 472 tests and `uv run ruff check src tests` is clean.
- With no config, `gbaport analyze` on BT4E finds the pointer-only callbacks and the IWRAM block the start-up code copies, and leaves no `outside_code` issues.
- `gbaport trace` records hits through mGBA's GDB server into `games/<game_code>/traces/mgba.trace`, and `gbaport analyze` picks them up automatically.
- The spec roadmap has row P2b, and P2 no longer lists trace import.
