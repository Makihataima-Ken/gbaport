# Plan 7c: Playing On — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user's game keeps running natively wherever it is played. Discovery finds the functions the game calls through tables of relative offsets and the cases of its halfword switch tables. The window and the phone record what is played, and `gbaport learn` replays a recording natively to learn each address a run stopped at. Rebuilds compile only what changed.

**Architecture:**
- **Discovery.**
  - `tables.py` learns the ARM compiler's Thumb switch through halfword offsets (`adr; adds; ldrh; lsls; add pc`). Dragon Ball GT Transformation (BT4E) has five of them.
  - `discover.py` gets an optional sweep. Where the code found so far ends with no fall-through, the code after it (past literal pools and zero padding) is guessed as an entry, the same state first, then the other. The guess goes through the pointer scan's checks (`drain_candidates`), and every kept guess leads to the code after it. `[code] sweep = true` turns it on per game; BT4E's `game.toml` does.
- **Rebuilds (`lift/program.py`, `native/build.py`).**
  - Generated code goes into one file per 8 KiB of guest code (`gba_code_<address>.c`), each declaring only the functions it uses; `gba_dispatch.c` declares them all, and `gba_program.h` goes.
  - `write_sources` leaves files whose text is the same alone, times included, so the app's CMake compiles only what changed.
  - `compile_native` keeps a key per object: a digest of the flags, the headers and the file.
- **Recording (`host_common.c`).**
  - `--record PATH` writes the keys the game is given as an input file, a line a change, through `host_set_keys`, which every host now calls instead of `gba_set_keys`. The save the game started from goes next to it as `PATH.sav`.
  - Keys that wake the game from Stop are written one frame on, where a replay's `host_script_wake` presses them.
  - The window host, the phone's too, records by default next to its save: `roms/mygame.sav` → `roms/mygame.session.input`.
- **Learning (`gbaport/learn.py`, `gbaport learn`).**
  - It builds the game headless and replays the recording from a copy of its start save. Each "no recompiled code" stop adds the address to `games/<game_code>/learned.toml`, which every command reads with `game.toml`. Then it builds and replays again, until the replay gets through.
  - The runtime's message now says the frame and suggests `gbaport learn`.
  - `--device` takes the recording and its start save from the game's app on the phone (`Device.get_file`).

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime and hosts built with clang; the Android SDK and emulator from Plan 8 for the phone test.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Out of scope, verbatim: "Any runtime interpreter or JIT. Code the recompiler did not find is a build-time error that names the address, fixed by adding it to `game.toml` (or by importing a trace)." `gbaport learn` finds the address at build time, by replaying play; the runtime still stops at missing code.
  - Key decision 4, verbatim: "**No runtime fallback.** Unknown indirect-branch targets abort with the address. Coverage comes from static analysis, recorded traces and per-game overrides."
  - "No ROM-derived bytes in git." `learned.toml` and input files hold addresses and key presses only; recordings' start saves (`*.sav`) and everything under `build/` and `roms/` stay untracked.
  - "Emulators are dev-time test oracles only." The Android emulator runs the phone test.
- **This plan is not in the roadmap.** The user chose it on 2026-10-24 over Plan 9 (iOS: no Mac yet) and Plan 10 (decompilation: no Claude API key yet). They asked to skip the design questions, so these calls are mine:
  - The sweep is opt-in per game (`[code] sweep`). Switched on everywhere, it changed 36 tests' exact function lists, and it can adopt data that decodes like code.
  - Learned addresses go in a file of their own, `learned.toml`, which gbaport writes whole. `game.toml` stays the user's.
  - The window and the phone always record their last play.
  - Code the game copies to EWRAM is left out: with the sweep, nothing in 60000 frames of BT4E needed it (Known limitations).
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Never commit a `.gba` file.
  - Tests never open a window and never play sound (SDL's dummy drivers; the emulator runs `-no-window -no-audio`).
  - Subagents and reviewers never read or print bytes of `roms/` or `build/`.
- **Commands:**
  - Use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher.
  - Run `uv run pytest` and `uv run ruff check src tests` as separate commands.
  - Never run two test runs at once: both would drive the same emulator and app.
  - Write C and Python that holds backslashes with the Edit or Write tools, never a shell heredoc (it turns `\n` into a new line).

## Review Focus

1. **A start save that no longer matches the recording.** The user may replace or delete the save after playing. The host copies the save as it was when the run started, so the pair always matches. Pinned in Task 4 (`test_the_save_the_game_started_from_goes_next_to_the_recording`).
2. **Learning that does not help.** An address the analysis cannot decode (past the ROM's end, in RAM no `[[ram_code]]` covers) stays missing after it is learned. `learn` stops with the address instead of looping. Pinned in Task 5 (`test_learn_stops_when_learning_does_not_help`).
3. **A key pressed while the game is stopped.** It wakes the game in the frame that was going on, so a recording that put it in that frame would press it before the Stop. Pinned in Task 4 (`test_a_key_that_wakes_the_game_from_stop_is_recorded_for_the_wake`).
4. **Data after the last function.** Bytes that decode as instructions up to the ROM's end must not become a function. Pinned in Task 2 (`test_the_sweep_leaves_what_is_not_code_alone`).
5. **A switch table right after its dispatch.** The sweep must not read the table as code. Pinned in Task 2 (`test_the_sweep_never_reads_a_switch_table_as_code`).

## Known limitations (deliberate; later plans)

- **Code copied to RAM at run time**, other than the copies the analysis detects (crt0's), and overlays that put different code at one RAM address. `learn` stops on such an address and says it is still missing; a `[[ram_code]]` entry fixes the first case.
- **Learning needs a recording that reaches the stop.** A round takes about 15 seconds for BT4E (analysis 8 s, 2 files compiled, the replay). The replay runs about 36 times faster than real time, so a recording of an hour adds about 100 seconds a round.
- **The phone keeps its last play only.** Starting the app again before `learn --device` replaces it. A run started with `--install --input` records to `input.session.input`, which `--device` does not take.
- **The sweep can keep data that decodes like a function.** It is never called, so it costs only build time.
- **Replays need the runtime to be deterministic on every processor.** The arm64 app played on the x86_64 emulator, through Android's ARM translation, replayed identically for 3000 frames. Task 7 checks it on the user's phone.

---

### Task 1: Halfword switch tables

The ARM compiler's Thumb switch: `cmp rI, #N; b<hs> default; adr rB, table; adds rA, rB, rI; ldrh rX, [rA, rI]; lsls rX, rX, #1; add pc, rX`. Each entry is a halfword count of halfwords from what the `add pc` reads as pc (its address + 4). BT4E has five, all left unresolved today (`add pc, r3: target unknown`).

**Files:**
- Modify: `src/gbaport/analysis/tables.py`
- Test: `tests/analysis/test_discover.py`, `tests/progkit.py`

**Interfaces:**
- Produces: `tables.HALFWORDS = "halfwords"`, an entry kind whose `JumpTable` has `entry_size=2` (discovery already marks `entry_size`-byte literals for each row).

- [ ] **Step 1: Write the failing test**

In `tests/analysis/test_discover.py`, replace:
```python
    CODE_ADDR,
    CRT0,
    DMA_COPY,
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
```
with:
```python
    CODE_ADDR,
    CRT0,
    DMA_COPY,
    HALFWORD_TABLE,
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
```

In `tests/analysis/test_discover.py`, replace:
```python
    assert ex.issues == []


def test_traced_targets_of_a_pc_relative_jump_are_cases():
    source = "ldr r3, [r1]\nadd pc, r3\nc0: bx lr\nc1: bx lr"
    traced = {0x080000C2: ((0x080000C4, Mode.THUMB), (0x080000C6, Mode.THUMB))}
```
with:
```python
    assert ex.issues == []


def test_halfword_table_rows_are_two_byte_literals():
    ex = explore_program(HALFWORD_TABLE, thumb=True)
    assert ex.successors[0x080000CC] == (0x080000D6, 0x080000D8, 0x080000DA)
    assert [ex.literals.get(a) for a in (0x080000D0, 0x080000D2, 0x080000D4)] == [2, 2, 2]
    assert ex.issues == []


def test_traced_targets_of_a_pc_relative_jump_are_cases():
    source = "ldr r3, [r1]\nadd pc, r3\nc0: bx lr\nc1: bx lr"
    traced = {0x080000C2: ((0x080000C4, Mode.THUMB), (0x080000C6, Mode.THUMB))}
```

In `tests/progkit.py`, replace:
```python
.align 1
c0: bx lr
c1: bx lr
c2: bx lr
dflt: bx lr
"""
```
with:
```python
.align 1
c0: bx lr
c1: bx lr
c2: bx lr
dflt: bx lr
"""

# The ARM compiler's Thumb switch through a table of halfwords: offsets, in halfwords,
# from what the `add pc` reads as pc.
#   cc dispatch (reads pc as d0)   d0 table 3, 4, 5   d6 c0   d8 c1   da c2   dc dflt
HALFWORD_TABLE = """
    cmp r0, #3
    bhs dflt
    adr r3, tbl
    adds r3, r3, r0
    ldrh r3, [r3, r0]
    lsls r3, r3, #1
    add pc, r3
.align 2
tbl: .hword 3, 4, 5
.align 1
c0: bx lr
c1: bx lr
c2: bx lr
dflt: bx lr
"""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/analysis/test_discover.py`
Expected: FAIL: 1 failed, 44 passed. `test_halfword_table_rows_are_two_byte_literals`: `assert () == (134217942, ...)`. The dispatch is unresolved.

- [ ] **Step 3: Recognise the pattern in `tables.py`**

- Add `HALFWORDS = "halfwords"` next to the other kinds, and list the pattern in the module docstring.
- In `_byte_table`, the load before the `lsls` may be an `ldrh rX, [rA, rI]` (register offset, `rA != rI`). Find `rA`'s definition with `_definition`: an `add rA, rB, rI` (register form, no shift) whose other operand `rB` holds a known constant, the table. The bound comes from `_bound(history, k - 1, rI, dispatch)`, with `k` the add's index.
- In `_table`, `HALFWORDS` reads `min(count, MAX_TABLE_ENTRIES)` halfwords (stopping where the ROM ends). Each target is `(dispatch.addr + 4 + 2 * halfword) & ~1`, and `JumpTable(..., data=True, entry_size=2)`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 930 passed (929 + 1).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/analysis/tables.py tests/analysis/test_discover.py tests/progkit.py
git commit -m "feat: discovery follows the Thumb switches through tables of halfword offsets"
```

---

### Task 2: The sweep: the code that follows code

A game reaches many functions through tables of relative offsets (BT4E: `*(base + *(base + 196))`). No walk and no pointer scan follows them. The functions sit right after other functions, so the sweep guesses there.
- **Turning it on.** `explore(..., sweep=True)`, from `[code] sweep = true`.
- **When it runs.** After the trusted seeds, the traces and the pointer candidates.
- **What it keeps.** A guess is kept only when the pointer scan's checks keep it.
- **One more check.** A guessed walk that runs off the end of the ROM is not code: no compiler's code does that, and zeros decode as `movs r0, r0` all the way there.

**Files:**
- Modify: `src/gbaport/analysis/discover.py`, `src/gbaport/analysis/config.py`, `src/gbaport/analysis/analyze.py`
- Modify: `games/BT4E/game.toml` (`sweep = true`)
- Test: `tests/analysis/test_discover.py`, `tests/analysis/test_config.py`, `tests/analysis/test_analyze.py`, `tests/progkit.py`

**Interfaces:**
- Consumes: Task 1's switch tables (their rows are literals, which the sweep skips).
- Produces: `explore(space, seeds, config=None, *, traced=None, candidates=None, sweep=False)`; `GameConfig.sweep: bool = False`; the entry kind `"neighbour"`; `_Explorer.drain_candidates(...) -> list[int]` (the addresses the kept guesses decoded).

- [ ] **Step 1: Write the failing tests**

In `tests/analysis/test_analyze.py`, replace:
```python
    assert 0x080000C8 not in without.program.functions


def copied_code_rom(source: str = DMA_COPY):
    return program_rom(source, patches={0x200: assemble("bx lr\nbx lr", addr=0x03000000)})

```
with:
```python
    assert 0x080000C8 not in without.program.functions


def test_the_sweep_finds_functions_for_games_that_ask_for_it():
    rom = program_rom("bx lr\n.thumb\nnext:\n movs r0, #1\n bx lr")
    assert 0x080000C4 not in analyze_rom(rom).program.functions
    swept = analyze_rom(rom, GameConfig(sweep=True))
    assert swept.program.functions[0x080000C4].kind == "neighbour"
    assert "found by     neighbour 1, seed 1" in summary_lines(swept)


def copied_code_rom(source: str = DMA_COPY):
    return program_rom(source, patches={0x200: assemble("bx lr\nbx lr", addr=0x03000000)})

```

In `tests/analysis/test_config.py`, replace:
```python
    assert parse_config("[code]\nscan_pointers = false").scan_pointers is False


@pytest.mark.parametrize(
    "text,message",
    [
```
with:
```python
    assert parse_config("[code]\nscan_pointers = false").scan_pointers is False


def test_the_sweep_is_for_games_that_ask_for_it():
    assert GameConfig().sweep is False
    assert parse_config("[code]\nsweep = true").sweep is True


@pytest.mark.parametrize(
    "text,message",
    [
```

In `tests/analysis/test_config.py`, replace:
```python
        ("[code]\nentries = 5", "list of addresses"),
        ("[code]\ndata = [[2, 1]]", "is empty"),
        ("[code]\nscan_pointers = 1", "scan_pointers must be true or false"),
        ("[code]\ndata = [[1, 2, 3]]", "[start, end] pairs"),
        ("[code]\njump_tables = [{ at = 1, count = 2 }]", "missing key(s): table"),
        ("[code]\njump_tables = [{ at = 1, table = 2, count = 0 }]", "at least 1"),
```
with:
```python
        ("[code]\nentries = 5", "list of addresses"),
        ("[code]\ndata = [[2, 1]]", "is empty"),
        ("[code]\nscan_pointers = 1", "scan_pointers must be true or false"),
        ("[code]\nsweep = 1", "sweep must be true or false"),
        ("[code]\ndata = [[1, 2, 3]]", "[start, end] pairs"),
        ("[code]\njump_tables = [{ at = 1, count = 2 }]", "missing key(s): table"),
        ("[code]\njump_tables = [{ at = 1, table = 2, count = 0 }]", "at least 1"),
```

In `tests/analysis/test_discover.py`, replace:
```python
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
    explore_program,
)
from romkit import build_rom

```
with:
```python
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
    SWEEP,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
    explore_program,
    program_space,
)
from romkit import build_rom

```

In `tests/analysis/test_discover.py`, replace:
```python
    assert ex.issues == []


def test_a_guess_that_decodes_garbage_is_undone():
    source = "bx lr\ncand:\n push {lr}\n movs r0, r0\n .hword 0xde00\n"
    ex = explore_program(source, thumb=True, candidates=[(0x080000C2, Mode.THUMB, "pointer")])
```
with:
```python
    assert ex.issues == []


def test_the_sweep_finds_code_that_only_code_before_it_leads_to():
    assert explore_program(SWEEP, thumb=True).entry_kinds == {0x080000C0: "seed"}
    ex = explore(program_space(SWEEP, thumb=True), [(0x080000C0, Mode.THUMB, "seed")], sweep=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000CA: "neighbour", 0x080000CE: "neighbour"}
    assert ex.entries[0x080000CA] is Mode.THUMB
    assert ex.calls == {0x080000D0: (0x080000CA,)}
    assert ex.issues == []


def test_the_sweep_tries_thumb_code_after_arm_code():
    space = program_space("bx lr\n.thumb\nnext:\n movs r0, #1\n bx lr")
    ex = explore(space, [(0x080000C0, Mode.ARM, "seed")], sweep=True)
    assert ex.entries == {0x080000C0: Mode.ARM, 0x080000C4: Mode.THUMB}
    assert ex.issues == []


def test_the_sweep_leaves_what_is_not_code_alone():
    space = program_space("bx lr\n.hword 0xde00\n.hword 0xde00", thumb=True)
    ex = explore(space, [(0x080000C0, Mode.THUMB, "seed")], sweep=True)
    assert ex.entries == {0x080000C0: Mode.THUMB}
    assert sorted(ex.instructions) == [0x080000C0]  # and the zeros after it, to the ROM's end
    assert ex.issues == []


def test_the_sweep_never_reads_a_switch_table_as_code():
    ex = explore(program_space(HALFWORD_TABLE, thumb=True), [(0x080000C0, Mode.THUMB, "seed")],
                 sweep=True)
    assert ex.entries == {0x080000C0: Mode.THUMB}
    assert not any(0x080000D0 <= addr < 0x080000D6 for addr in ex.instructions)


def test_a_guess_that_decodes_garbage_is_undone():
    source = "bx lr\ncand:\n push {lr}\n movs r0, r0\n .hword 0xde00\n"
    ex = explore_program(source, thumb=True, candidates=[(0x080000C2, Mode.THUMB, "pointer")])
```

In `tests/progkit.py`, replace:
```python
dflt: bx lr
"""

# The ARM compiler's Thumb switch through a table of halfwords: offsets, in halfwords,
# from what the `add pc` reads as pc.
#   cc dispatch (reads pc as d0)   d0 table 3, 4, 5   d6 c0   d8 c1   da c2   dc dflt
```
with:
```python
dflt: bx lr
"""

# Functions that no call or pointer leads to, only the code before them (a game reaches
# them through tables of relative offsets): one after a literal pool and zero padding, one
# right after a return.
#   c0 main (loads c4)   c4 literal   c8 padding   ca after_pool   ce last (calls after_pool)
SWEEP = """
main:
    ldr r0, lit
    bx lr
.align 2
lit: .word 0x12345678
.hword 0
after_pool:
    movs r0, #1
    bx lr
last:
    push {lr}
    bl after_pool
    pop {pc}
"""

# The ARM compiler's Thumb switch through a table of halfwords: offsets, in halfwords,
# from what the `add pc` reads as pc.
#   cc dispatch (reads pc as d0)   d0 table 3, 4, 5   d6 c0   d8 c1   da c2   dc dflt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/analysis`
Expected: FAIL: 7 failed, 184 passed. Four `TypeError: explore() got an unexpected keyword argument 'sweep'`, `GameConfig.__init__() got an unexpected keyword argument 'sweep'`, `'GameConfig' object has no attribute 'sweep'`, and the unknown-key message where `sweep must be true or false` was expected.

- [ ] **Step 3: The sweep**

- **`config.py`.**
  - `GameConfig.sweep: bool = False`, read with `_flag(code, "sweep", False, source)`.
  - Add `"sweep"` to `[code]`'s keys.
- **`analyze.py`.** Pass `sweep=config.sweep` to `explore`.
- **`discover.py`.**
  - `explore` takes `sweep: bool = False` and, after `drain_candidates`, runs `explorer.drain_neighbours()` when it is set. Document it in the docstring.
  - `drain_candidates` collects `self.trial` of each guess it keeps and returns them, in order.
  - `_take`'s "walked off the end of analysable code" branch also sets `self.suspect` when `self.trial is not None`.
  - The sweep itself, on `_Explorer`, with a docstring that says why (tables of relative offsets):

```python
    def drain_neighbours(self) -> None:
        queue = deque(self._neighbours(self.ex.instructions.values()))
        while queue:
            kept = self.drain_candidates([queue.popleft()])
            queue.extend(self._neighbours([self.ex.instructions[addr] for addr in kept]))

    def _neighbours(self, instructions) -> list[tuple[int, Mode, str]]:
        """The guesses for the code after the last of each run among ``instructions``."""
        found = []
        for ins in instructions:
            after = ins.addr + ins.size
            if after in self.ex.instructions:
                continue
            while True:  # literal pools, then zero padding
                if after in self.ex.literals:
                    after += self.ex.literals[after]
                elif self.space.contains(after, 2) and self.space.read16(after) == 0:
                    after += 2
                else:
                    break
            other = Mode.THUMB if ins.mode is Mode.ARM else Mode.ARM
            for mode in (ins.mode, other):  # the same state first; veneers switch it
                at = (after + 3) & ~3 if mode is Mode.ARM else after
                if at in self.ex.instructions or not self.space.contains(at, 4) or self._is_data(at):
                    continue
                found.append((at, mode, "neighbour"))
        return found
```

- **`games/BT4E/game.toml`.** `sweep = true` first in `[code]`, with a comment: "The game calls most of its functions through tables of relative offsets, so the sweep guesses the code after the code found (it finds more than 1100 functions more)."

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 937 passed (930 + 7).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: The user's game**

```bash
uv run python -m gbaport.cli recompile roms/mygame.gba --out build/BT4E-sweep
```

Expected: `functions    2193`, `lift issues  0`; without the sweep it is 1065 (with Task 1).

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/analysis/discover.py src/gbaport/analysis/config.py src/gbaport/analysis/analyze.py games/BT4E/game.toml tests/analysis tests/progkit.py
git commit -m "feat: the sweep guesses the code that follows code; BT4E turns it on"
```

---

### Task 3: Rebuilds compile only what changed

Today one new function shifts every 256-function chunk after it, and every chunk includes `gba_program.h`, which declares every function. So a rebuild compiles everything: 30 s for BT4E on the PC, minutes for the phone.

**Files:**
- Modify: `src/gbaport/lift/program.py`, `src/gbaport/native/build.py`
- Test: `tests/lift/test_program.py`, `tests/test_native_build.py`, `tests/test_recompile_cli.py`, `tests/test_android.py`

**Interfaces:**
- Produces:
  - `program_files(lifted) -> dict[str, str]` (no `chunk` argument), with `BUCKET = 0x2000`.
  - The file names `gba_code_<8 hex digits>.c` and `gba_dispatch.c`; there is no `gba_program.h` any more.
  - `compile_native(sources, out, name, host="headless", log=print) -> Path`, which logs `compiled N of M files`.

- [ ] **Step 1: Write the failing tests**

In `tests/lift/test_program.py`, replace:
```python
from progkit import CRT0, program_space

from gbaport.analysis.cfg import build_program
from gbaport.analysis.discover import explore
from gbaport.isa.model import Mode
from gbaport.lift import function
from gbaport.lift.program import lift_program, program_files, single_source
```
with:
```python
from ksasm import assemble
from progkit import CRT0, program_rom, program_space

from gbaport.analysis.cfg import build_program
from gbaport.analysis.discover import explore
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.lift import function
from gbaport.lift.program import lift_program, program_files, single_source
```

In `tests/lift/test_program.py`, replace:
```python
    assert "uint32_t c7_f_080000c0(GbaCtx *ctx)" in program.functions[0x080000C0]


def test_program_files_split_the_code():
    program = lifted(TWO_FUNCTIONS, seeds=BOTH)
    files = program_files(program, chunk=1)
    assert sorted(files) == ["gba_code_000.c", "gba_code_001.c", "gba_dispatch.c", "gba_program.h"]
    assert '#include "gba_cpu.h"' in files["gba_program.h"]
    code = [text for name, text in files.items() if name.endswith(".c")]
    assert all(text.startswith('#include "gba_program.h"') for text in code)
    assert single_source(program).startswith('#include "gba_cpu.h"')


def test_an_instruction_c_cannot_express_is_reported(monkeypatch):
```
with:
```python
    assert "uint32_t c7_f_080000c0(GbaCtx *ctx)" in program.functions[0x080000C0]


def test_each_code_file_holds_8_kib_of_code_and_declares_what_it_uses():
    calls_first = assemble("mov r1, #2\nbl 0x080000c0\nb 0x08002000", addr=0x08002000)
    rom = program_rom("mov r0, #1\nbx lr", size=0x4000, patches={0x2000: calls_first})
    ex = explore(CodeSpace(rom), [(0x080000C0, Mode.ARM, "seed"), (0x08002000, Mode.ARM, "seed")])
    files = program_files(lift_program(build_program(ex), ex))
    assert sorted(files) == ["gba_code_08000000.c", "gba_code_08002000.c", "gba_dispatch.c"]
    first, second = files["gba_code_08000000.c"], files["gba_code_08002000.c"]
    assert all(text.startswith('#include "gba_cpu.h"') for text in files.values())
    assert "uint32_t f_080000c0(GbaCtx *ctx);" in first and "f_08002000" not in first
    assert "uint32_t f_080000c0(GbaCtx *ctx);" in second  # it calls the first
    assert "GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);" in second
    for entry in (0x080000C0, 0x08002000):
        assert f"uint32_t f_{entry:08x}(GbaCtx *ctx);" in files["gba_dispatch.c"]
    assert single_source(lifted(TWO_FUNCTIONS, seeds=BOTH)).startswith('#include "gba_cpu.h"')


def test_an_instruction_c_cannot_express_is_reported(monkeypatch):
```

In `tests/test_android.py`, replace:
```python
def generated(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "generated"
    folder.mkdir(exist_ok=True)
    for name in (*names, "gba_program.h"):
        (folder / name).write_text(f"/* {name} */\n", encoding="utf-8")
    return folder

```
with:
```python
def generated(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "generated"
    folder.mkdir(exist_ok=True)
    for name in (*names, "gba_cpu.h"):
        (folder / name).write_text(f"/* {name} */\n", encoding="utf-8")
    return folder

```

In `tests/test_android.py`, replace:
```python
    assert (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").exists()
    assert (main / "java" / "org" / "gbaport" / "game" / "GameActivity.java").exists()
    assert (main / "res" / "mipmap-hdpi" / "ic_launcher.png").exists()
    assert (main / "cpp" / "generated" / "gba_program.h").exists()
    assert (main / "cpp" / "runtime" / "touch.h").exists()
    cmake = (main / "cpp" / "CMakeLists.txt").read_text(encoding="utf-8")
    units = [line.strip() for line in cmake.splitlines() if line.strip().endswith(".c")]
```
with:
```python
    assert (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").exists()
    assert (main / "java" / "org" / "gbaport" / "game" / "GameActivity.java").exists()
    assert (main / "res" / "mipmap-hdpi" / "ic_launcher.png").exists()
    assert (main / "cpp" / "generated" / "gba_cpu.h").exists()
    assert (main / "cpp" / "runtime" / "touch.h").exists()
    cmake = (main / "cpp" / "CMakeLists.txt").read_text(encoding="utf-8")
    units = [line.strip() for line in cmake.splitlines() if line.strip().endswith(".c")]
```

In `tests/test_native_build.py`, replace:
```python
from romtest import build_test_rom

import gbaport.native.build as native
```
with:
```python
import os

from romtest import build_test_rom

import gbaport.native.build as native
```

In `tests/test_native_build.py`, replace:
```python
from gbaport.rom.image import RomImage


def _build(tmp_path, monkeypatch, verdicts: list[bool]):
    """Build the hello ROM while Smart App Control gives ``verdicts``, one per start."""
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    answers, builds = iter(verdicts), []

    def starts(program):
```
with:
```python
from gbaport.rom.image import RomImage


def _sources(tmp_path) -> dict[str, str]:
    """The hello ROM's generated sources, written to tmp_path/generated."""
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    return files


def test_a_rebuild_compiles_only_the_files_that_changed(tmp_path):
    _sources(tmp_path)
    said = []
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    total = int(said[0].split()[3])  # "compiled N of N files"
    assert said == [f"compiled {total} of {total} files"]
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    assert said[-1] == f"compiled 0 of {total} files"
    dispatch = tmp_path / "generated" / "gba_dispatch.c"
    dispatch.write_text(dispatch.read_text(encoding="utf-8") + "/* changed */\n", encoding="utf-8")
    program = native.compile_native(tmp_path / "generated", tmp_path / "build", "game",
                                    log=said.append)
    assert said[-1] == f"compiled 1 of {total} files"
    assert program.exists()


def test_writing_the_same_sources_again_leaves_their_files_alone(tmp_path):
    native.write_sources({"gba_code_08000000.c": "a", "gba_code_08002000.c": "b",
                          "gba_dispatch.c": "c"}, tmp_path)
    for path in tmp_path.iterdir():
        os.utime(path, (1_000_000_000, 1_000_000_000))
    native.write_sources({"gba_code_08000000.c": "a", "gba_dispatch.c": "d"}, tmp_path)
    assert (tmp_path / "gba_code_08000000.c").stat().st_mtime == 1_000_000_000  # the same text
    assert (tmp_path / "gba_dispatch.c").read_text(encoding="utf-8") == "d"
    assert not (tmp_path / "gba_code_08002000.c").exists()  # gone from the program


def _build(tmp_path, monkeypatch, verdicts: list[bool]):
    """Build the hello ROM while Smart App Control gives ``verdicts``, one per start."""
    _sources(tmp_path)
    answers, builds = iter(verdicts), []

    def starts(program):
```

In `tests/test_recompile_cli.py`, replace:
```python
    assert "functions    4" in out and "lift issues  0" in out
    generated = tmp_path / "games" / "ATST" / "generated"
    names = sorted(path.name for path in generated.iterdir())
    assert names == ["gba_code_000.c", "gba_cpu.h", "gba_dispatch.c", "gba_program.h", "gba_rom.c"]
    for source in ("gba_code_000.c", "gba_dispatch.c", "gba_rom.c"):
        command = [clang(), "-std=c11", "-Wall", "-Werror", "-Wno-unused-label", "-c",
                   str(generated / source), "-o", str(tmp_path / f"{source}.o")]
        subprocess.run(command, check=True, capture_output=True)
```
with:
```python
    assert "functions    4" in out and "lift issues  0" in out
    generated = tmp_path / "games" / "ATST" / "generated"
    names = sorted(path.name for path in generated.iterdir())
    assert names == ["gba_code_08000000.c", "gba_cpu.h", "gba_dispatch.c", "gba_rom.c"]
    for source in ("gba_code_08000000.c", "gba_dispatch.c", "gba_rom.c"):
        command = [clang(), "-std=c11", "-Wall", "-Werror", "-Wno-unused-label", "-c",
                   str(generated / source), "-o", str(tmp_path / f"{source}.o")]
        subprocess.run(command, check=True, capture_output=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/lift/test_program.py tests/test_native_build.py tests/test_recompile_cli.py tests/test_android.py`
Expected: FAIL: 4 failed, 22 passed.
- The bucket test and the recompile test: names `gba_code_000.c` and `gba_program.h`.
- `compile_native() got an unexpected keyword argument 'log'`.
- The time assertion: `write_sources` deletes and writes every file.

- [ ] **Step 3: Files by address; keep what did not change**

- **`program.py`, `program_files(lifted)`.**
  - Group the bodies by `addr & ~(BUCKET - 1)` into `gba_code_{start:08x}.c`.
  - Each file starts with `#include "gba_cpu.h"`. Then come the declarations of every `\b{prefix}f_[0-9a-f]{8}\b` name its bodies use, sorted (`uint32_t NAME(GbaCtx *ctx);`), and `GbaFn {prefix}gba_lookup(GbaCtx *ctx, uint32_t addr);`.
  - `gba_dispatch.c` holds `#include "gba_cpu.h"`, `lifted.prototypes` and `lifted.dispatch`.
  - Remove `CHUNK` and `_program_header`.
- **`build.py`, `write_sources`.**
  - Delete only the earlier run's generated files (`gba_code_*.c` and `GENERATED_NAMES`) that are not in `files`. `GENERATED_NAMES` keeps `gba_program.h`, so an old one goes.
  - Write a file only when its bytes differ.
- **`build.py`, `compile_native`.**
  - Hash, once, every `*.h` in `sources` and in `RUNTIME` (name and bytes).
  - Each unit's key is `sha1(headers digest + "\0".join(command) + unit bytes)`, kept in `obj/<stem>.key`. When the object and an equal key exist, the unit is not compiled. Otherwise delete the key, compile, and write the key.
  - After compiling, `log(f"compiled {len(fresh)} of {len(units)} files")`, before the link (and before any salted relink, whose salt unit does not count).

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 939 passed (937 + 2).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: The user's game**

```bash
uv run python -m gbaport.cli build roms/mygame.gba --host headless --out build/BT4E-h
uv run python -m gbaport.cli build roms/mygame.gba --host headless --out build/BT4E-h
```

Expected: `C files      35`, then `compiled 51 of 51 files` (about 30 s) and `compiled 0 of 51 files` (about 10 s, the analysis).

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/lift/program.py src/gbaport/native/build.py tests/lift/test_program.py tests/test_native_build.py tests/test_recompile_cli.py tests/test_android.py
git commit -m "feat: generated code goes into a file per 8 KiB of game code, and rebuilds compile only what changed"
```

---

### Task 4: Recording play

The keys a host gives the game come once a frame (and at a Stop's wake). Recorded as they are given, they replay exactly: the same pictures, frame for frame.

**Files:**
- Modify: `src/gbaport/runtime/host_common.h`, `host_common.c`, `host_headless.c`, `host_sdl.c`
- Test: `tests/runtime/test_record.py`

**Interfaces:**
- Produces:
  - `void host_set_keys(HostOptions *o, GbaRuntime *rt, uint16_t keys, int waking)`.
  - The `HostOptions` fields `char record_path[1024]`, `void *record_file`, `uint16_t recorded`.
  - The option `--record PATH`, the start save `PATH.sav`, and the window's default `<save path without .sav>.session.input`.

- [ ] **Step 1: Write the failing tests**

Create `tests/runtime/test_record.py`:
```python
"""Recording play (host_common.c's --record): the keys the game was given, frame by frame,
as an input file, and the save it started from next to it, so the same play can be
replayed (gbaport learn)."""

from romtest import build_test_rom, run_rom, run_test

from gbaport.inputs import format_input, load_input

PRESSES = ("--press", "30:A", "--press", "40:none", "--press", "60:RIGHT+B", "--press", "75:none")


def presses(path):
    return [line for line in format_input(load_input(path)).splitlines() if line]


def test_a_recording_replays_as_the_run_it_records(tmp_path):
    record = tmp_path / "play.input"
    first = run_test("keys_log", frames=100,
                     args=(*PRESSES, "--record", str(record), "--hashes", str(tmp_path / "1")))
    assert record.read_text(encoding="utf-8").startswith("# recorded by gbaport")
    assert presses(record) == ["30 A", "40 none", "60 B+RIGHT", "75 none"]
    replay = run_test("keys_log", frames=100,
                      args=("--input", str(record), "--hashes", str(tmp_path / "2")))
    assert replay.lines == first.lines
    assert first.lines[1:] == ("KEYS A", "KEYS none", "KEYS B+RIGHT", "KEYS none")
    assert (tmp_path / "1").read_bytes() == (tmp_path / "2").read_bytes()


def test_a_key_that_wakes_the_game_from_stop_is_recorded_for_the_wake(tmp_path):
    record = tmp_path / "play.input"
    run_test("stop_wake", args=("--press", "30:START", "--record", str(record))).assert_passed()
    assert presses(record) == ["1 START"]  # after the frame it stopped in, which no frame ends
    replay = run_test("stop_wake", args=("--input", str(record)))
    replay.assert_passed()
    assert replay.lines[:2] == ("stopping", "woke")


def test_the_save_the_game_started_from_goes_next_to_the_recording(tmp_path):
    rom = build_test_rom("save_sram")
    save, record = tmp_path / "game.sav", tmp_path / "play.input"
    run_rom(rom, save=save, args=("--record", str(record)))
    assert not (tmp_path / "play.input.sav").exists()  # it started blank
    started = save.read_bytes()
    run_rom(rom, save=save, args=("--record", str(record)))
    assert (tmp_path / "play.input.sav").read_bytes() == started
    save.unlink()
    run_rom(rom, save=save, args=("--record", str(record)))
    assert not (tmp_path / "play.input.sav").exists()  # not an older one


def test_the_window_records_next_to_its_save_and_headless_only_when_asked(tmp_path):
    rom = build_test_rom("hello")
    run_rom(rom, host="sdl", frames=60, save=tmp_path / "game.sav")
    assert (tmp_path / "game.session.input").read_text(encoding="utf-8").startswith("# recorded")
    run_rom(rom, frames=60, save=tmp_path / "other.sav")
    assert not (tmp_path / "other.session.input").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_record.py`
Expected: FAIL: 4 failed. `--record` is not an option yet: `FileNotFoundError` for the recordings, and the Stop test's `exit status 2: usage: ...`.

- [ ] **Step 3: `--record` and `host_set_keys`**

- **`host_parse`.**
  - Takes `--record PATH`, which also goes into the usage line, after `[--hashes PATH]`.
  - After `default_save_path`, a window host (`o->window`, the phone's too) with no `--record` records to its save path, with a final `.sav` removed and `.session.input` added.
- **`host_open`.** After the save is loaded, and before it is freed, `start_recording(o, save, save_size)`. A failure returns 2. The function:
  - opens `record_path` (`open_file`, `"wb"`) and writes `# recorded by gbaport: the keys the game was given (gbaport/inputs.py)\n`, flushed;
  - writes the save it started from to `record_path + ".sav"`, or removes that file (`remove_file`) when the game starts with no save file;
  - prints `error: cannot write PATH` for either file it cannot write.
- **`host_set_keys`.**
  - When `keys` differ from `o->recorded`, it writes `"%lu KEYS\n"` with the frame `rt->frames + (waking ? 1 : 0)`. KEYS are the `KEY_NAMES` joined with `+` in bit order, or `none`. It flushes the line, since the app may be killed at any time.
  - It always calls `gba_set_keys`.
  - The `+ 1` matters: a replay's `host_frame` takes the presses due by the frame that ended, before the Stop, and `host_script_wake` takes the next one.
- **`host_finish`.** Closes the recording (warning `cannot finish PATH`).
- **The callers.** `host_open`'s frame-0 keys and the hosts' `gba_set_keys` calls become `host_set_keys`:
  - `waking = 0` in `on_frame`;
  - `waking = 1` in `on_stopped`, for the script's wake and for the window's own key wake.
- **The header comments.**
  - `host_headless.c` lists `[--record PATH]` and explains it.
  - `host_sdl.c` lists it on the `[--scale N] [--fast]` line, and says the window records next to its save file by default (`game.sav`'s recording is `game.session.input`, and the save it started from `game.session.input.sav`).

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 943 passed (939 + 4).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/host_common.h src/gbaport/runtime/host_common.c src/gbaport/runtime/host_headless.c src/gbaport/runtime/host_sdl.c tests/runtime/test_record.py
git commit -m "feat: the hosts record the play, and the window and the phone always do"
```

---

### Task 5: gbaport learn

**Files:**
- Create: `src/gbaport/learn.py`
- Modify: `src/gbaport/analysis/config.py`, `src/gbaport/cli.py`, `src/gbaport/runtime/runtime.c`
- Test: `tests/test_learn.py`, `tests/runtime/test_core.py`

**Interfaces:**
- Consumes:
  - Task 3's `compile_native(..., log=...)` and `write_sources`.
  - Task 4's recordings: the window's default path and `PATH.sav`.
- Produces:
  - **`config.py`:** `LEARNED = "learned.toml"`, `learned_path(game_code, root=Path(".")) -> Path`, `load_learned(path, sha1) -> tuple[tuple[int, ...], tuple[int, ...]]` (ARM, Thumb), `write_learned(path, sha1, entries, thumb_entries)`, and `GameConfig.with_entries(entries, thumb_entries) -> GameConfig`.
  - **`learn.py`:** `MISS`, `LearnError(ValueError)`, `Learned(addr, mode, frame)`, and `learn(rom_path, rom, config, traces, learned, recording, start_save, frames, work, log=print) -> list[Learned]`.
  - **`cli.py`:** `_config(args, rom) -> GameConfig` and `_traces(args, rom) -> tuple[Trace, ...]`.

- [ ] **Step 1: Write the failing tests**

In `tests/runtime/test_core.py`, replace:
```python
    run = run_test("err_missing")
    assert run.status == 3
    assert "no recompiled code at 0x08100000 (Thumb state" in run.stderr
    assert "thumb_entries" in run.stderr


```
with:
```python
    run = run_test("err_missing")
    assert run.status == 3
    assert "no recompiled code at 0x08100000 (Thumb state" in run.stderr
    assert ", frame 0): gbaport learn finds it" in run.stderr  # from a recording of the play
    assert "thumb_entries" in run.stderr


```

Create `tests/test_learn.py`:
```python
"""gbaport learn: a recorded run that stopped at code the recompiler did not find is played
again natively, and each address it stops at is learned (games/<game_code>/learned.toml),
until the replay gets through."""

import os
import re

from romtest import build_test_rom, run_program, run_rom

from gbaport.analysis.config import learned_path, load_learned, write_learned
from gbaport.cli import main
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom


def game(tmp_path, monkeypatch, name: str = "calls"):
    """A test ROM as game.gba with its game.toml in games/ATST; tmp_path is the working folder."""
    monkeypatch.chdir(tmp_path)
    rom = build_test_rom(name)
    (tmp_path / "game.gba").write_bytes(rom.data)
    (tmp_path / "games" / "ATST").mkdir(parents=True)
    (tmp_path / "games" / "ATST" / "game.toml").write_text(rom.config, encoding="utf-8")
    return rom


RECORDING = "game.session.input"  # where the window records game.gba's play


def built(tmp_path) -> str:
    """gbaport build --host headless's program for game.gba (learned.toml goes in too)."""
    assert main(["build", "game.gba", "--host", "headless"]) == 0
    return str(tmp_path / "games" / "ATST" / "build" / ("ATST-headless" + (".exe" if os.name == "nt" else "")))


def learned_lines(out: str) -> list[tuple[int, str, int]]:
    found = re.findall(r"learned (0x[0-9a-f]{8}) \((Thumb|ARM)\), missing at frame (\d+)", out)
    return [(int(addr, 16), mode, int(frame)) for addr, mode, frame in found]


def test_play_learn_build_and_play_on(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch)
    thumb, arm, pressed = (rom.symbols[name] for name in ("hidden_thumb", "hidden_arm", "hidden_pressed"))
    stopped = run_rom(rom, frames=30, args=("--press", "5:A", "--record", RECORDING)).stderr
    assert re.search(rf"no recompiled code at 0x{thumb:08x} \(Thumb state, lr = 0x[0-9a-f]{{8}}, "
                     r"frame 0\): gbaport learn", stopped)  # at once: the A press never came
    assert main(["learn", "game.gba"]) == 0
    out = capsys.readouterr().out
    assert learned_lines(out) == [(thumb, "Thumb", 0), (arm, "ARM", 0)]
    assert f"2 addresses learned into {learned_path('ATST')}" in out
    played = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30",
                          "--record", RECORDING])
    assert f"no recompiled code at 0x{pressed:08x}" in played.stderr  # further this time
    capsys.readouterr()
    assert main(["learn", "game.gba"]) == 0
    (addr, mode, frame), = learned_lines(capsys.readouterr().out)
    assert (addr, mode) == (pressed, "Thumb") and frame >= 5
    sha1 = inspect_rom(RomImage(rom.data)).sha1
    assert load_learned(learned_path("ATST"), sha1) == ((arm,), (thumb, pressed))
    run = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30"])
    assert run.stdout.splitlines()[-1] == "DONE 3 passed, 0 failed"


def test_learn_says_when_the_replay_stops_at_nothing(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "hello")
    run_rom(rom, frames=30, args=("--record", RECORDING))
    assert main(["learn", "game.gba"]) == 0
    assert "the replay played to its end: nothing to learn" in capsys.readouterr().out
    assert not learned_path("ATST").exists()


def test_learn_needs_a_recording(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    assert main(["learn", "game.gba"]) == 1
    assert "no recording game.session.input: play the game in the window first" in \
        capsys.readouterr().err


def test_learned_addresses_belong_to_the_rom_they_were_learned_from(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    write_learned(learned_path("ATST"), "0" * 40, (), (0x08000100,))
    assert main(["recompile", "game.gba"]) == 1
    assert f"learned.toml is for ROM sha1 {'0' * 40}" in capsys.readouterr().err


def test_learn_stops_when_learning_does_not_help(tmp_path, monkeypatch, capsys):
    rom = game(tmp_path, monkeypatch, "err_missing")  # jumps past the end of the ROM
    run_rom(rom, frames=30, args=("--record", RECORDING))
    assert main(["learn", "game.gba"]) == 1
    captured = capsys.readouterr()
    assert "learned 0x08100000 (Thumb)" in captured.out
    assert "has 0x08100000 already, but it is still missing" in captured.err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_learn.py tests/runtime/test_core.py`
Expected: FAIL: 1 error during collection, `ImportError: cannot import name 'learned_path' from 'gbaport.analysis.config'`, which interrupts the run.

- [ ] **Step 3: Learned entries, the message, the loop and the command**

- **`runtime.c`, `gba_missing`.** The message becomes:
  - `no recompiled code at 0x%08x (%s state, lr = 0x%08x, frame %lu): gbaport learn finds it from a recording of play, or add it to game.toml [code] %s`;
  - the frame is `gba_rt(ctx)->frames`.
- **`config.py`.**
  - `learned_path` is `root / "games" / game_code / LEARNED`.
  - `load_learned` loads it with `load_config`. When its `rom_sha1` is not `sha1` it raises `ConfigError(f"{path} is for ROM sha1 {learned.rom_sha1}, but this ROM is {sha1}")`; otherwise it returns `(entries, thumb_entries)`.
  - `write_learned` writes the whole file:
    - two comment lines ("Code gbaport learn found by replaying recorded play natively, read together with game.toml. Written by gbaport learn; addresses only, no ROM bytes.");
    - `[rom] sha1`;
    - `[code]` `entries` and `thumb_entries`, sorted, one `0x%08x,` per line.
  - `GameConfig.with_entries` appends to both lists without repeats (`dataclasses.replace`).
- **`learn.py`.** The module docstring explains the round trip.
  - `MISS` matches `gba_missing`'s message: address, `Thumb|ARM` and frame.
  - **Each round:**
    - Analyse with `config.with_entries(*learned so far)`, lift, `write_sources` into `work/generated`, and `compile_native(..., "learn", log=lambda _: None)` into `work/build`.
    - Run the program with `rom_path --input recording --save COPY --frames N`. COPY is a temporary copy of `start_save`, or a blank save when there is none. The timeout is 3600 s.
  - **How a round ends:**
    - Exit status 3 with a `MISS` line: learn it. If it was learned already, raise `LearnError(f"{learned} has 0x{addr:08x} already, but it is still missing: {message}")`. Otherwise append it, `write_learned`, and log `learned 0x%08x (Thumb|ARM), missing at frame N`.
    - Any other status-3 error: `LearnError(f"the replay stopped: {message}")`.
    - Status 0 or 4: return what was learned.
  - **Giving up.** After 500 learned addresses: `LearnError(f"gave up after learning 500 addresses in one run")`.
- **`cli.py`.**
  - **`_config`.** `game.toml`, as `_analyse` read it, printing `config` as now. Then, when `learned_path(game_code or "game")` exists, `config.with_entries(*load_learned(...))`, printing `learned      PATH`.
  - **`_traces`.** The default and `--trace` traces, printing `trace` as now.
  - **The callers.** `_analyse` becomes `analyze_rom(rom, _config(args, rom), _traces(args, rom))`; `_run_trace` uses `_config`.
  - **`gbaport learn ROM [--input FILE] [--save FILE] [--frames N] [--config] [--trace]`.**
    - **The recording.** `--input`, or the ROM's path `.with_suffix(".session.input")`. When it is missing: `ValueError(f"no recording {recording}: play the game in the window first (it records the play), or give --input FILE")`.
    - **The start save.** `--save` (which must exist: `no save PATH`), or the recording's `.sav` if there is one.
    - **Frames.** `--frames`, or the last press's frame + 1800.
    - **Where.** It learns into `learned_path(game_code)` with `work = games/<game_code>/build/learn`.
    - **What it prints.** `{n} addresses learned into {path}; build the game again to play on`, or `the replay played to its end: nothing to learn`.
    - **Registration.** It goes after `verify` in `build_parser`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 948 passed (943 + 5).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/learn.py src/gbaport/analysis/config.py src/gbaport/cli.py src/gbaport/runtime/runtime.c tests/test_learn.py tests/runtime/test_core.py
git commit -m "feat: gbaport learn replays recorded play and learns the code it stopped at"
```

---

### Task 6: Learning from the phone

The app records like the window (Task 4: `files/game.session.input` in its own storage). `gbaport learn ROM --device` copies that recording and its start save from the phone, and learns from them on the PC.

**Files:**
- Modify: `src/gbaport/native/device.py`, `src/gbaport/cli.py`
- Test: `tests/test_learn.py`, `tests/test_android_device.py`

**Interfaces:**
- Consumes: Task 5's `learn` and `_run_learn`; Plan 8's `the_device`, `Device`, `application_id`.
- Produces: `device.adb_program() -> Path`; `Device.get_file(app, name) -> bytes | None`; `gbaport learn ... --device`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_android_device.py`, replace:
```python
    phone.start(APP)
    assert int(phone.wait_for(r"^SAVED (\d+)$").group(1)) == kept
    phone.stop(APP)
```
with:
```python
    phone.start(APP)
    assert int(phone.wait_for(r"^SAVED (\d+)$").group(1)) == kept
    phone.stop(APP)


def test_learn_takes_the_play_the_phone_recorded(phone, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # learned.toml goes into games/ATST here
    hidden = build_test_rom("calls").symbols["hidden_thumb"]
    build_and_install(phone, tmp_path, monkeypatch, "calls")
    phone.wait_for(rf"^error: no recompiled code at 0x{hidden:08x} ")  # the app records its play
    phone.stop(APP)
    capsys.readouterr()
    assert main(["learn", "game.gba", "--config", "game.toml", "--device"]) == 0
    out = capsys.readouterr().out
    assert f"took the play recorded on {phone.serial}" in out
    assert "2 addresses learned into" in out
    build_and_install(phone, tmp_path, monkeypatch, "calls")
    phone.wait_for(r"^DONE 2 passed, 0 failed$")
    phone.stop(APP)
```

In `tests/test_learn.py`, replace:
```python
    write_learned(learned_path("ATST"), "0" * 40, (), (0x08000100,))
    assert main(["recompile", "game.gba"]) == 1
    assert f"learned.toml is for ROM sha1 {'0' * 40}" in capsys.readouterr().err
```
with:
```python
    write_learned(learned_path("ATST"), "0" * 40, (), (0x08000100,))
    assert main(["recompile", "game.gba"]) == 1
    assert f"learned.toml is for ROM sha1 {'0' * 40}" in capsys.readouterr().err


def test_device_is_instead_of_input_and_save(tmp_path, monkeypatch, capsys):
    game(tmp_path, monkeypatch)
    assert main(["learn", "game.gba", "--device", "--input", "x.input"]) == 1
    assert "--device takes the recording from the phone" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_learn.py tests/test_android_device.py -k "device_is_instead or phone_recorded"`
Expected: FAIL: 2 failed, 16 deselected, both with `SystemExit: 2` (`unrecognized arguments: --device`). The emulator boots for the second.

- [ ] **Step 3: `get_file` and `--device`**

- **`device.py`.**
  - `adb_program()` is the SDK's `platform-tools/adb(.exe)`; `adb()` uses it.
  - `Device.get_file(app, name)`:
    - returns None when `run-as APP ls files/NAME` lists nothing;
    - otherwise runs `[adb, "-s", serial, "exec-out", "run-as", app, "cat", "files/NAME"]` as bytes (timeout 120: `DeviceError` "reading NAME from APP took more than 120 s");
    - a non-zero status is `DeviceError(f"cannot read {name} from {app}: ...")`.
- **`cli.py`.**
  - `--device` (`store_true`, help: "take the recording from the game's app on the connected phone: its last play").
  - With `--input` or `--save` it is `ValueError("--device takes the recording from the phone: give no --input or --save with it")`.
  - Otherwise `_recording_from_device(application_id(game_code), work / "device")`:
    - it gets `game.session.input` from `the_device()`; none is `ValueError(f"{app} on {serial} has recorded no play yet: play it first")`;
    - it writes it there, with `game.session.input.sav` beside it, or removes a stale one;
    - it prints `took the play recorded on {serial}` and returns the recording, whose `.sav` `_run_learn` then finds as usual.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 950 passed (948 + 2). The emulator boots, runs the tests and shuts down.

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/native/device.py src/gbaport/cli.py tests/test_learn.py tests/test_android_device.py
git commit -m "feat: gbaport learn --device learns from the play recorded on the phone"
```

---

### Task 7: The user's game, the README and the spec

**Files:**
- Create: `games/BT4E/walk-right.input`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

- [ ] **Step 1: The input file**

Create `build/walk_right.py` (build/ is not tracked), then run it with `uv run python build/walk_right.py`. It writes `games/BT4E/walk-right.input`: `first-fight.input` with a header of its own, then a change of keys every 10 to 20 frames from frame 4300 to 60000.

```python
from pathlib import Path

first = Path("games/BT4E/first-fight.input").read_text(encoding="utf-8").split("\n")
header = [
    "# Dragon Ball GT Transformation (BT4E): first-fight.input, then from frame 4300 walking",
    "# right and attacking, a change every 10 to 20 frames, until the game is over and back at",
    "# its title by frame 60000. Frames count from power-on (gbaport/inputs.py). The native",
    "# build plays all of it with no missing code (README).",
]
moves = ["RIGHT+A", "RIGHT", "RIGHT+B", "RIGHT", "A", "RIGHT", "START", "none", "A", "RIGHT"]
lines = header + first[3:-1]  # first-fight.input without its three header lines
for i, frame in enumerate(range(4300, 60000, 30)):
    lines += [f"{frame} {moves[i % len(moves)]}", f"{frame + 10} RIGHT"]
Path("games/BT4E/walk-right.input").write_text("\n".join(lines) + "\n", encoding="utf-8",
                                               newline="\n")
```

Expected: `games/BT4E/walk-right.input` has 3803 lines; its last press is `59990 RIGHT`.

- [ ] **Step 2: The README and the spec**

In `README.md`, replace:
```markdown
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport build roms/mygame.gba --host android [--abi x86_64] [--install [--input FILE]]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]

If Windows Application Control blocks the `gbaport.exe` launcher, run the same commands
as `uv run python -m gbaport.cli ...`.
```
with:
```markdown
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport build roms/mygame.gba --host android [--abi x86_64] [--install [--input FILE]]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]
    uv run gbaport learn roms/mygame.gba [--input FILE] [--save FILE] [--device]

If Windows Application Control blocks the `gbaport.exe` launcher, run the same commands
as `uv run python -m gbaport.cli ...`.
```

In `README.md`, replace:
```markdown
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second);
- `--hashes PATH`: write a hash of each frame's picture, a line a frame (`gbaport verify`
  compares them with mGBA's).

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
```
with:
```markdown
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second);
- `--hashes PATH`: write a hash of each frame's picture, a line a frame (`gbaport verify`
  compares them with mGBA's);
- `--record PATH`: record the play: the keys the game is given, as an input file, and the
  save it started from as `PATH.sav`. The window records by default, next to its save
  file (`roms/mygame.session.input` for `roms/mygame.sav`), each run over the last.

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
```

In `README.md`, replace:
```markdown

The most common runtime error is code the recompiler did not find:

    error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3): add it to
    game.toml [code] thumb_entries, or record a trace

Add the address to `games/<game_code>/game.toml` (`thumb_entries` or `entries`, as the
message says) and build again, or record a trace with mGBA (below).
`games/BT4E/game.toml` is an example: the entries Dragon Ball GT Transformation needs to
boot and play its first minute. With `games/BT4E/traces/mgba.trace`, recorded from
`games/BT4E/first-fight.input`, it plays on into its first fight.

Some games switch between tasks, each on its own stack: a task "returns" into another one,
where that one last switched away, past the calls the first task made since. The runtime
```
with:
```markdown

The most common runtime error is code the recompiler did not find:

    error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3, frame 4296):
    gbaport learn finds it from a recording of play, or add it to game.toml [code]
    thumb_entries

The window recorded the play that led there, so

    uv run python -m gbaport.cli learn roms/mygame.gba

plays it again natively from the save it started from. The replay does exactly what the
play did, so it stops at the same place; `learn` adds the address to the game's learned
entries (`games/<game_code>/learned.toml`, read together with `game.toml`), builds again
and replays again, until the replay gets through. Each round takes about 15 seconds for
Dragon Ball GT Transformation: a rebuild compiles only the code files that changed (code
goes into files by address, 8 KiB of game code each). Then build the game again and play
on; `learned.toml` holds addresses only and can be committed. `--input` and `--save` name
another recording and the save it started from; `--device` takes the recording from the
phone (below).

Discovery cannot follow the tables of relative offsets many games call their functions
through, so for those `game.toml`'s `[code] sweep = true` turns on the sweep: where code
found so far ends (a return, a jump), the code after it, past literal pools and padding,
is tried as a function too, and kept only when it decodes as code a compiler emits.
Addresses can also go into `game.toml` by hand (`thumb_entries` or `entries`, as the
message says), or come from a trace recorded with mGBA (below).

`games/BT4E/game.toml` is an example: Dragon Ball GT Transformation with the sweep, about
2200 functions. `games/BT4E/walk-right.input` plays it into its first fight, then walks
right attacking until the game is over and back at the title, 60000 frames, with no
missing code.

Some games switch between tasks, each on its own stack: a task "returns" into another one,
where that one last switched away, past the calls the first task made since. The runtime
```

In `README.md`, replace:
```markdown
A runtime error, or one that stops the game from starting (a save file of the wrong
size), shows its message on the screen; the app ends when it is closed.

## Checking a game against mGBA

`gbaport verify` builds a headless program for the game (into `build/<game_code>-verify`)
```
with:
```markdown
A runtime error, or one that stops the game from starting (a save file of the wrong
size), shows its message on the screen; the app ends when it is closed.

The app records its play as the window does, in its own storage. When it stops at code
the recompiler did not find, with the phone still connected:

    uv run python -m gbaport.cli learn roms/mygame.gba --device
    uv run python -m gbaport.cli build roms/mygame.gba --host android --install

The first takes the recording of the app's last play (and the save it started from)
from the phone and learns from it on the PC, which plays it exactly as the phone did;
the second puts the game back on the phone, its save kept, to play on from the last time
the game saved.

## Checking a game against mGBA

`gbaport verify` builds a headless program for the game (into `build/<game_code>-verify`)
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- Matching (byte-identical) decompilation.
- Zero-input support for every ROM. Each game is expected to need a small `game.toml`.
- Any runtime interpreter or JIT. Code the recompiler did not find is a build-time error
  that names the address, fixed by adding it to `game.toml` (or by importing a trace).

## Key decisions

```
with:
```markdown
- Matching (byte-identical) decompilation.
- Zero-input support for every ROM. Each game is expected to need a small `game.toml`.
- Any runtime interpreter or JIT. Code the recompiler did not find is a build-time error
  that names the address, fixed by adding it to `game.toml`, by importing a trace, or by
  `gbaport learn`, which replays recorded play natively to find it (Plan 7c).

## Key decisions

```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
   arm64 reserves the whole low 4 GB (`__PAGEZERO`), so GBA addresses cannot be mapped 1:1.
   Readable decompiled functions use the same accessors until their data is symbolized.
4. **No runtime fallback.** Unknown indirect-branch targets abort with the address. Coverage
   comes from static analysis, recorded traces and per-game overrides.
5. **Emulators are dev-time test oracles only.** Unicorn (CPU semantics) and mGBA
   (whole-game lockstep) are used by tests and tools, never linked into a shipped app.
6. **Python tooling, C11 runtime, clang everywhere.** Analysis and code generation are
```
with:
```markdown
   arm64 reserves the whole low 4 GB (`__PAGEZERO`), so GBA addresses cannot be mapped 1:1.
   Readable decompiled functions use the same accessors until their data is symbolized.
4. **No runtime fallback.** Unknown indirect-branch targets abort with the address. Coverage
   comes from static analysis (with an optional sweep of the code that follows code),
   recorded traces, per-game overrides, and addresses learned by replaying recorded play
   natively (`gbaport learn`, Plan 7c).
5. **Emulators are dev-time test oracles only.** Unicorn (CPU semantics) and mGBA
   (whole-game lockstep) are used by tests and tools, never linked into a shipped app.
6. **Python tooling, C11 runtime, clang everywhere.** Analysis and code generation are
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
| Runtime (Plans 4–6) | Self-built test ROMs (clang `--target=armv4t-none-eabi` + `ld.lld`) and public GBA test suites (licence checked before vendoring) | Expected outputs and reference images |
| Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
| Android (Plan 8) | Test ROMs on the Android emulator (dev only) | The app runs them; drawn buttons press keys; saves survive the app being killed; the frame rate holds |
| Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |

## Roadmap
```
with:
```markdown
| Runtime (Plans 4–6) | Self-built test ROMs (clang `--target=armv4t-none-eabi` + `ld.lld`) and public GBA test suites (licence checked before vendoring) | Expected outputs and reference images |
| Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
| Android (Plan 8) | Test ROMs on the Android emulator (dev only) | The app runs them; drawn buttons press keys; saves survive the app being killed; the frame rate holds |
| Coverage (Plan 7c) | The native build itself | A recording of play replays with the same picture each frame, also one recorded on a phone; `gbaport learn` turns a run that stopped at missing code into one that gets through |
| Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |

## Roadmap
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4c |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6 |
| P8 Android | Gradle/NDK project generated per game, touch overlay, controller, lifecycle, saves | APK runs on device at 60 fps; save survives app kill | P7 |
| P9 iOS | Xcode project via CMake generator, signing, same features as Android | IPA runs on device at 60 fps | P7, needs macOS |
| P10 Decomp loop | Override mechanism, Ghidra headless export, Claude agent loop, function-level differential tester | Functions replaced with tests passing; game still verifies | P7 |
| P11 Symbolized data (optional) | ROM tables → C structs, GBA pointers → native symbols in decompiled code | Decompiled modules no longer use raw GBA addresses | P10 |
```
with:
```markdown
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4c |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6 |
| P8 Android | Gradle/NDK project generated per game, touch overlay, controller, lifecycle, saves | APK runs on device at 60 fps; save survives app kill | P7 |
| P7c Playing on | Halfword switch tables, the sweep, rebuilds of what changed, recorded play, `gbaport learn` (also from a phone) | The first game plays a 60000-frame script natively with no missing code; a phone's recorded play replays on the PC | P8 |
| P9 iOS | Xcode project via CMake generator, signing, same features as Android | IPA runs on device at 60 fps | P7, needs macOS |
| P10 Decomp loop | Override mechanism, Ghidra headless export, Claude agent loop, function-level differential tester | Functions replaced with tests passing; game still verifies | P7 |
| P11 Symbolized data (optional) | ROM tables → C structs, GBA pointers → native symbols in decompiled code | Decompiled modules no longer use raw GBA addresses | P10 |
```

- [ ] **Step 3: Run the whole suite**

Run: `uv run pytest`
Expected: 951 passed (950 + 1: `tests/test_games.py` checks every `games/*/*.input`, the new one too).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 4: The user's game on the PC**

```bash
uv run python -m gbaport.cli learn roms/mygame.gba --input games/BT4E/walk-right.input
uv run python -m gbaport.cli verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input
```

Expected:
- `the replay played to its end: nothing to learn` (61790 frames, about a minute; `games/BT4E/build/learn` holds the build);
- `verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart`, as before this plan.

- [ ] **Step 5: The user's game on the user's phone**

This step needs the user's phone over USB (USB debugging on, this computer allowed). If no phone is available, ledger that and carry on: the user does this step later.

```bash
uv run python -m gbaport.cli build roms/mygame.gba --host android --install --input games/BT4E/first-fight.input --out build/BT4E-android
```

Expected:
- `built build\BT4E-android\build\BT4E.apk (arm64-v8a)` (about two minutes the first time).
- After 80 seconds, `adb logcat -d -s gbaport` shows the frame-rate lines at 59.5 to 60.0 frames a second, and no `no recompiled code` line: the game plays on past the input file's end, in the fight.

Then check that play recorded on the phone replays on the PC with the same pictures. Create `build/phone_check.py`:

```python
"""The app plays first-fight.input for 3000 frames, writing its pictures' hashes; the PC
replays the app's recording of that play and must draw the same pictures."""
import subprocess
from pathlib import Path

from gbaport.inputs import format_input, load_input
from gbaport.native.device import the_device

APP = "org.gbaport.bt4e"
FILES = f"/data/user/0/{APP}/files"
device = the_device()
device.stop(APP)
device.shell("run-as", APP, "rm", "-f", "files/check.sav")
presses = Path("build/check.input")
presses.write_text(format_input(load_input("games/BT4E/first-fight.input")), encoding="utf-8")
played = device.put_file(APP, presses)
device.clear_log()
device.start(APP, f"--input {played} --save {FILES}/check.sav --hashes {FILES}/check.hashes "
                  "--frames 3000")
device.wait_for("stopped after 3000 frames", timeout=240)
Path("build/phone.hashes").write_bytes(device.get_file(APP, "check.hashes"))
Path("build/phone.input").write_bytes(device.get_file(APP, "check.session.input"))
Path("build/pc.sav").unlink(missing_ok=True)
program = next(Path("build/BT4E-h/build").glob("BT4E-headless*"))
subprocess.run([str(program), "roms/mygame.gba", "--input", "build/phone.input", "--save",
                "build/pc.sav", "--frames", "3000", "--hashes", "build/pc.hashes"], check=False)
same = Path("build/phone.hashes").read_bytes() == Path("build/pc.hashes").read_bytes()
print("the same 3000 pictures" if same else "different pictures")
```

Run `uv run python -m gbaport.cli build roms/mygame.gba --host headless --out build/BT4E-h`, then `uv run python build/phone_check.py`.
Expected: `the same 3000 pictures`. Record the frame-rate lines and this result in the ledger.

- [ ] **Step 6: Commit**

```bash
git add games/BT4E/walk-right.input README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: playing on: the sweep, recorded play and gbaport learn; BT4E walks right to its title"
```

---

## Done criteria for Plan 7c

- `uv run pytest` passes 951 tests and `uv run ruff check src tests` is clean.
- **Discovery:**
  - It follows halfword switch tables.
  - With `[code] sweep = true` it finds the code that follows code. BT4E recompiles to 2193 functions with 0 lift issues.
- **Rebuilds:** they compile only the files that changed. BT4E's no-change rebuild compiles 0 of 51 files.
- **Recording:** the window and the phone record their play; a recording replays with the same picture every frame, and so does a key that wakes the game from Stop.
- **`gbaport learn`:**
  - It turns a recorded run that stopped at missing code into learned addresses (`learned.toml`) with which the game gets through, also from the phone's recording (`--device`).
  - It stops with the address when learning does not help.
- **BT4E:** `walk-right.input` plays all 60000 frames natively with no missing code, and `verify` over 3600 frames is unchanged.
