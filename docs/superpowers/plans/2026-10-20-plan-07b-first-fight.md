# Plan 7b: The User's Game into Its First Fight — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The user's game, Dragon Ball GT Transformation (BT4E), plays natively from power-on into its first fight, following an input file, with every picture within a frame of mGBA's through the menus and the fight's first seconds. Its trace comes from gbaport's own mGBA playing that input file, and the runtime follows the game when it switches between tasks.

**Architecture:**
- **Traces from gbaport's own mGBA.** `gbaport-mgba --trace PATH` runs the game an instruction at a time and writes each indirect transfer once: site, target, state and LR.
  - It follows calls on a shadow stack. A transfer to the latest call's return address is an ordinary return. A transfer to an outer call's return address skips the calls in between, which the runtime unwinds (below). Neither is recorded.
  - Everything else is: calls through registers, jumps through registers, and returns that go somewhere no call in progress came from.
- **`gbaport trace --frames N [--input FILE]`** plays the game that way and turns the transfers into the game's trace, `games/<game_code>/traces/mgba.trace`.
  - It keeps the transfers whose site the analysis decodes as an instruction that writes the PC. It repeats this as the traced targets lead the analysis to more code, until nothing new turns up.
  - A transfer through a shared `bx rN` veneer is recorded at the `bl` that called the veneer, found from LR, as the GDB recorder does. The GDB recorder stays, for playing the game in mGBA's window.
- **Returns that go elsewhere.** Discovery now takes a traced return's targets as entries. A task switcher returns into another task, where that task last called it.
- **Unwinding.**
  - Each running `gba_call` keeps its return address in `ctx->rets[depth]`.
  - When a lookup misses on the return address of a call further out, `gba_missing` sets `ctx->unwind_depth` to that call's depth.
  - Every chain in between ends, and every function in between returns (`GBA_UNWOUND()` after each call). That call then carries on after its return address, and the calls are as deep as before.
  - In the user's game, the prototype without this stops at frame 2744: `no recompiled code at 0x08015256 (Thumb state, lr = 0x080086f3)`, a return into the caller of a task.
- **The user's game.**
  - `games/BT4E/first-fight.input` plays from power-on through the menus into the first fight.
  - Its trace is recorded with `gbaport trace` and committed. Like `games/BT4E/game.toml`, it holds addresses only.
  - `gbaport verify` keeps every picture of its first 3600 frames within a frame of mGBA's.

**Tech Stack:** Python 3.13 (uv), pytest, ruff; the C11 runtime built with clang 23; mGBA 0.10.5 (MPL-2.0), built from source with CMake and Ninja as Plans 5 to 7a did.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

## Global Constraints

- **From the spec:**
  - Roadmap row P7, verbatim: "P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6". Plan 7a delivered `gbaport verify`. This plan delivers the gameplay and the replay, N = 3600 frames with a frame of slack.
  - "Emulators are dev-time test oracles only." mGBA is built by gbaport for tracing, verifying and the tests, and is never linked into a game.
  - "No ROM-derived bytes in git." The committed trace and input file hold addresses, key names and frame numbers, as `games/BT4E/game.toml` already does. Test ROMs are built at test time.
- **The user's rules:**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer.
  - Never commit a `.gba` file: the user's ROMs stay untracked.
  - Tests never open a window and never play sound.
- **Commands:**
  - Use `uv run python -m gbaport.cli ...` where Windows Application Control blocks the `gbaport.exe` launcher.
  - Run `uv run pytest` and `uv run ruff check src tests` as separate commands.
  - mGBA's program is built again after Task 1 (its source changes), which takes a minute or two. Every test program is built again after Task 3 (the lifter and runtime change), which can take several minutes.

## Review Focus

1. **Calls that never return.** A game that uses `bl` as a jump in a loop piles up calls in progress. The tracer's shadow stack forgets the oldest half and goes on, instead of overflowing. Pinned in Task 1 (`test_mgba_traces_calls_that_never_return`).
2. **A trace file named outside the ANSI code page.** mGBA's program writes the transfers to any path, as it reads any ROM path. Pinned in Task 1 (`test_mgba_writes_the_transfers_to_any_file_name`).
3. **A trace of another ROM in the way.** `gbaport trace --frames` stops before playing, names the file, and leaves it as it was. Pinned in Task 2 (`test_trace_checks_its_file_before_playing`).
4. **An input file saved by a Windows editor.** `gbaport trace --input` reads a UTF-8 byte order mark and CRLF line ends like any other file. Pinned in Task 2 (`test_trace_plays_an_input_file`).
5. **Interrupts while tasks take turns.** An interrupt inside the second task's calls, which run inside the first task's call, returns where it came in, and the switches still unwind. Pinned in Task 3 (`test_two_thousand_switches_leave_the_calls_as_deep_as_before`).

## Known limitations (deliberate; later plans)

- **The fight parts from mGBA at frame 3627.**
  - Where the native build has come a frame early (an interrupt comes in at a loop or a return: Plan 7a's slack), a press reaches the game a frame later in its own time. The fighter the press moves is then one step behind the rest of the picture, and by frame 3837 the fight goes its own way.
  - An input file names frames from power-on, so a replay matches only while every picture comes on the same frame. That takes timing exact to the cycle, including BIOS calls and interrupt delivery.
- **Coverage is what was played.** The trace holds the paths `first-fight.input` takes. Playing other ways in the window may reach code no trace saw (`no recompiled code at ...`). More input files, traced the same way, or the GDB recorder add to it.
- **A return to the continuation of a call that has already returned** (a `longjmp` to an old `setjmp`) runs that code as a new function, inside the calls it skips. Done every frame, these would pile up to `GBA_MAX_CALL_DEPTH`. The user's game does not do it.
- **An interrupt handler that leaves other than by returning to the BIOS** (into the code it interrupted, or past it) is not supported.
- **Several calls in progress with the same return address** (recursion): a return there goes to the innermost, in the tracer and the runtime alike.
- **The tracer runs mGBA an instruction at a time.** The user's 4200 frames take about 2 seconds, and the analysis rounds about 10 more.

---

### Task 1: mGBA's program records the game's indirect transfers

`gbaport-mgba --trace PATH` runs each frame an instruction at a time (`ARMRun`) and records every indirect transfer the game takes outside the BIOS once, as `SITE TARGET MODE LR` lines. It follows the calls on a shadow stack of their return addresses:
- **A call** is a transfer that leaves LR pointing just after it: a `bl`, or a `bx` after `mov lr, pc`. A call through a register is recorded too.
- **A return** is an indirect transfer to a return address on the shadow stack. The latest is an ordinary return; one further out skips the calls in between. Neither is recorded, and both drop the calls they leave.
- **Everything else** is recorded: jumps through registers, and returns to an address no call in progress came from (a task switcher returning into another task).
- **Calls that never return** fill the shadow stack: it then forgets the oldest half.

`gbaport/tracing/transfers.py` reads the lines. Test ROMs now know their ELF symbols (`TestRom.symbols`), so the tests can name the code they expect. Their `game.toml` lists only ELF functions, so labels in top-level assembly stay hidden from discovery.

**Files:**
- Modify: `src/gbaport/native/mgba_oracle/mgba.c` (`--trace`), `src/gbaport/native/mgba.py` (`run_mgba(..., trace=)`)
- Create: `src/gbaport/tracing/transfers.py`
- Modify: `tests/romtest.py` (`TestRom.symbols`)
- Create: `tests/gbaroms/calls.c`, `tests/gbaroms/tasks.c`, `tests/gbaroms/bl_loop.c`
- Test: `tests/tracing/test_transfers.py`

**Interfaces:**
- Consumes: Plan 7a's `gbaport.native.mgba.run_mgba` and `mgba_program`; `romtest.build_test_rom`, `elf_symbols`; testlib's `expect`, `check`, `irq_init`, `irq_count`, `wait_vcount`.
- **Produces:**
  - **`gbaport-mgba ROM --frames N ... [--trace PATH]`:** one line per distinct transfer, `%08x %08x arm|thumb %08x`.
  - **`run_mgba(rom, frames, *, input=None, picture=None, sound=None, hashes=None, trace=None, log=print)`.**
  - **`gbaport/tracing/transfers.py`:** `TransferError(ValueError)`, `Transfer(site: int, target: int, mode: Mode, lr: int)`, `parse_transfers(text, source="transfers") -> set[Transfer]`, `load_transfers(path) -> set[Transfer]`.
  - **`TestRom.symbols: dict[str, int]`:** every named ELF symbol's value (Thumb functions have bit 0 set).
  - **`calls.c`:** `hidden_thumb` (r0 × 3), `hidden_arm` (r0 + 100), `hidden_pressed` (r0 + 1, called only while A is held), each called through a function pointer kept in RAM. It prints 2 checks, or 3 when A is pressed within 20 frames.
  - **`tasks.c`:** `switch_task`, `run_a_once`, `a_resumes`, `task_b`, `task_b_resumes`, `yield_b`, `yield_b_resumes`. It runs `TURNS` turns (5 by default, set by `testdata.h`), one check each, plus one about interrupts when `TURNS` ≥ 1000.
  - **`bl_loop.c`:** `spin_calls`, a `bl` to itself.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-07b-first-fight
```

- [ ] **Step 2: Write the failing tests and the test ROMs**

Create `tests/gbaroms/bl_loop.c`:
```c
/* A bl used as a jump in a loop: calls that never return, as some games make. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global spin_calls\n"
    "    .thumb_func\n"
    "    .type spin_calls, %function\n"
    "spin_calls:\n"
    "    bl spin_calls\n");

void spin_calls(void);

int main(void)
{
    spin_calls();
    return 0;
}
```

Create `tests/gbaroms/calls.c`:
```c
/* Calls discovery cannot follow: through a function pointer kept in RAM, to code the test
 * ROM's game.toml does not list (labels in top-level assembly are not ELF functions), in
 * Thumb and in ARM state, and one only a press of A leads to. Clang calls a pointer
 * through a `bx rN` veneer. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global hidden_thumb\n"
    "hidden_thumb:\n"            /* r0 * 3 */
    "    lsls r1, r0, #1\n"
    "    adds r0, r0, r1\n"
    "    bx lr\n"
    "    .global hidden_pressed\n"
    "hidden_pressed:\n"          /* r0 + 1 */
    "    adds r0, r0, #1\n"
    "    bx lr\n"
    "    .arm\n"
    "    .align 2\n"
    "    .global hidden_arm\n"
    "hidden_arm:\n"              /* r0 + 100 */
    "    add r0, r0, #100\n"
    "    bx lr\n"
    "    .thumb\n");

extern char hidden_thumb[], hidden_pressed[], hidden_arm[];
static int (*volatile hook)(int);

int main(void)
{
    hook = (int (*)(int))((uintptr_t)hidden_thumb | 1);
    expect("thumb code through a pointer", hook(5), 15);
    hook = (int (*)(int))(uintptr_t)hidden_arm;
    expect("arm code through a pointer", hook(5), 105);
    for (int frame = 0; frame < 20; frame++) {
        wait_vcount(160);
        if (~REG_KEYINPUT & 1) {  /* A */
            hook = (int (*)(int))((uintptr_t)hidden_pressed | 1);
            expect("code a press of A leads to", hook(5), 6);
            break;
        }
        wait_vcount(161);
    }
    test_end();
    return 0;
}
```

Create `tests/gbaroms/tasks.c`:
```c
/* Two tasks taking turns on their own stacks, as games' task systems do. switch_task keeps
 * the running task's registers and stack pointer and returns into the other task, where it
 * last called switch_task: at its start the first time. So a switch back to the first task
 * returns past the calls the second task made, and the second task goes on at places only
 * such returns reach (task_b_resumes and yield_b_resumes are labels, not ELF functions). */
#include "testlib.h"
#include "testdata.h"

#ifndef TURNS
#define TURNS 5
#endif

uint32_t a_sp, b_sp, b_count;
static uint32_t b_stack[64];

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global switch_task\n"
    "    .thumb_func\n"
    "    .type switch_task, %function\n"
    "switch_task:\n"             /* r0: where to keep this task's sp; r1: the other's sp */
    "    push {r4-r7, lr}\n"
    "    mov r2, sp\n"
    "    str r2, [r0]\n"
    "    mov sp, r1\n"
    "    pop {r4-r7, pc}\n"
    "    .global run_a_once\n"
    "    .thumb_func\n"
    "    .type run_a_once, %function\n"
    "run_a_once:\n"              /* the first task: lets the second run once */
    "    push {lr}\n"
    "    ldr r0, =a_sp\n"
    "    ldr r1, =b_sp\n"
    "    ldr r1, [r1]\n"
    "    bl switch_task\n"
    "    .global a_resumes\n"
    "a_resumes:\n"
    "    pop {r0}\n"
    "    bx r0\n"
    "    .global task_b\n"
    "    .thumb_func\n"
    "    .type task_b, %function\n"
    "task_b:\n"                  /* the second task: counts by 2, then yields, forever */
    "    ldr r0, =b_count\n"
    "    ldr r1, [r0]\n"
    "    adds r1, r1, #2\n"
    "    str r1, [r0]\n"
    "    bl yield_b\n"
    "    .global task_b_resumes\n"
    "task_b_resumes:\n"
    "    b task_b\n"
    "    .global yield_b\n"
    "    .thumb_func\n"
    "    .type yield_b, %function\n"
    "yield_b:\n"
    "    push {lr}\n"
    "    ldr r0, =b_sp\n"
    "    ldr r1, =a_sp\n"
    "    ldr r1, [r1]\n"
    "    bl switch_task\n"
    "    .global yield_b_resumes\n"
    "yield_b_resumes:\n"
    "    pop {pc}\n"
    "    .pool\n");

void run_a_once(void);
void task_b(void);

int main(void)
{
    irq_init();  /* VBlank interrupts come in while the tasks take turns */
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    uint32_t *top = b_stack + 64 - 5;  /* as switch_task leaves a stack: r4-r7, then pc */
    top[4] = (uint32_t)task_b;
    b_sp = (uint32_t)top;
    for (uint32_t turn = 1; turn <= TURNS; turn++) {
        run_a_once();
        expect("the second task ran once more", b_count, 2 * turn);
    }
    if (TURNS >= 1000)  /* (the lines these print take many frames) */
        check("interrupts came in while the tasks took turns", irq_count[0] > 0);
    test_end();
    return 0;
}
```

In `tests/romtest.py`, replace:
```python
import time
from dataclasses import dataclass
from pathlib import Path
```
with:
```python
import time
from dataclasses import dataclass, field
from pathlib import Path
```

In `tests/romtest.py`, replace:
```python
class TestRom:
    data: bytes
    config: str  # game.toml text


def _digest(*parts: bytes | str) -> str:
```
with:
```python
class TestRom:
    data: bytes
    config: str  # game.toml text
    symbols: dict[str, int] = field(default_factory=dict)  # the ELF's, by name


def _digest(*parts: bytes | str) -> str:
```

In `tests/romtest.py`, replace:
```python
        _run([llvm_tool("llvm-objcopy"), "-O", "binary", str(elf), str(binary)])
        config_path.write_text(config_for(elf_symbols(elf.read_bytes())), encoding="utf-8")
        rom_path.write_bytes(_with_header(binary.read_bytes()))
    return TestRom(rom_path.read_bytes(), config_path.read_text(encoding="utf-8"))


# ---- running a test ROM natively --------------------------------------------------------
```
with:
```python
        _run([llvm_tool("llvm-objcopy"), "-O", "binary", str(elf), str(binary)])
        config_path.write_text(config_for(elf_symbols(elf.read_bytes())), encoding="utf-8")
        rom_path.write_bytes(_with_header(binary.read_bytes()))
    elf = elf_symbols((folder / "game.elf").read_bytes())
    symbols = {name: value for name, (value, _) in elf.items()}
    return TestRom(rom_path.read_bytes(), config_path.read_text(encoding="utf-8"), symbols)


# ---- running a test ROM natively --------------------------------------------------------
```

Create `tests/tracing/test_transfers.py`:
```python
"""gbaport-mgba --trace: the indirect transfers a game took in mGBA
(gbaport/tracing/transfers.py reads them)."""

import pytest
from romtest import build_test_rom

from gbaport.isa.model import Mode
from gbaport.native.mgba import run_mgba
from gbaport.tracing.transfers import Transfer, TransferError, load_transfers, parse_transfers


def transfers_of(name: str, tmp_path, frames: int = 30, input: str | None = None):
    rom = build_test_rom(name)
    (tmp_path / "game.gba").write_bytes(rom.data)
    input_file = None
    if input is not None:
        input_file = tmp_path / "game.input"
        input_file.write_text(input, encoding="utf-8")
    run_mgba(tmp_path / "game.gba", frames, input=input_file, trace=tmp_path / "game.transfers")
    return rom.symbols, load_transfers(tmp_path / "game.transfers")


def test_transfers_read_as_written():
    text = "080001f0 08000300 thumb 080001e5\n\n03000010 08000400 arm 08000123\n"
    assert parse_transfers(text) == {
        Transfer(0x080001F0, 0x08000300, Mode.THUMB, 0x080001E5),
        Transfer(0x03000010, 0x08000400, Mode.ARM, 0x08000123),
    }


@pytest.mark.parametrize("line", ["080001f0 08000300 thumb", "080001f0 08000300 jazz 0", "x y z w"])
def test_a_bad_transfer_line_says_which(line):
    with pytest.raises(TransferError, match="^game.transfers, line 2: expected 'SITE TARGET MODE LR'"):
        parse_transfers("080001f0 08000300 thumb 080001e5\n" + line + "\n", "game.transfers")


def test_mgba_records_calls_through_pointers(tmp_path):
    symbols, transfers = transfers_of("calls", tmp_path)
    went = {(t.target, t.mode) for t in transfers}
    assert (symbols["hidden_thumb"], Mode.THUMB) in went
    assert (symbols["hidden_arm"], Mode.ARM) in went
    assert symbols["hidden_pressed"] not in {t.target for t in transfers}  # A was not pressed


def test_mgba_records_what_the_keys_lead_to(tmp_path):
    symbols, transfers = transfers_of("calls", tmp_path, input="5 A\n")
    assert (symbols["hidden_pressed"], Mode.THUMB) in {(t.target, t.mode) for t in transfers}


def test_mgba_leaves_out_returns_to_calls_in_progress(tmp_path):
    """A return to the latest call is ordinary; one to an outer call skips the calls in
    between, which the runtime unwinds. Neither is recorded; returns elsewhere are."""
    symbols, transfers = transfers_of("tasks", tmp_path)
    targets = {t.target for t in transfers}
    assert {symbols["task_b"] & ~1, symbols["yield_b_resumes"], symbols["task_b_resumes"]} <= targets
    assert symbols["a_resumes"] not in targets  # back past the second task's calls
    assert not targets & {t.lr & ~1 for t in transfers}  # no return to where LR pointed


def test_mgba_traces_calls_that_never_return(tmp_path):
    """A bl used as a jump: the calls in progress pile up, and the oldest are forgotten."""
    symbols, transfers = transfers_of("bl_loop", tmp_path, frames=10)
    assert (symbols["main"] & ~1, Mode.THUMB) in {(t.target, t.mode) for t in transfers}


def test_mgba_writes_the_transfers_to_any_file_name(tmp_path):
    """Windows hands mGBA's program its arguments in UTF-16."""
    folder = tmp_path / "あ-ゲーム"
    folder.mkdir()
    symbols, transfers = transfers_of("calls", folder)
    assert symbols["hidden_thumb"] in {t.target for t in transfers}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/tracing/test_transfers.py`
Expected: FAIL — 1 error: `ModuleNotFoundError: No module named 'gbaport.tracing.transfers'`.

- [ ] **Step 4: The tracer, and its lines read in Python**

In `src/gbaport/native/mgba.py`, replace:
```python
def run_mgba(rom: Path, frames: int, *, input: Path | None = None, picture: Path | None = None,
             sound: Path | None = None, hashes: Path | None = None,
             log: Callable[[str], None] = print) -> None:
```
with:
```python
def run_mgba(rom: Path, frames: int, *, input: Path | None = None, picture: Path | None = None,
             sound: Path | None = None, hashes: Path | None = None, trace: Path | None = None,
             log: Callable[[str], None] = print) -> None:
```

In `src/gbaport/native/mgba.py`, replace:
```python
    for option, path in (("--input", input), ("--picture", picture), ("--sound", sound),
                         ("--hashes", hashes)):
        if path is not None:
```
with:
```python
    for option, path in (("--input", input), ("--picture", picture), ("--sound", sound),
                         ("--hashes", hashes), ("--trace", trace)):
        if path is not None:
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
 *     gbaport-mgba ROM --frames N [--input FILE] [--picture PATH] [--sound PATH]
 *                  [--hashes PATH]
 *
```
with:
```c
 *     gbaport-mgba ROM --frames N [--input FILE] [--picture PATH] [--sound PATH]
 *                  [--hashes PATH] [--trace PATH]
 *
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
 * - --hashes writes one line a frame: the picture's 64-bit FNV-1a hash (over its colours
 *   as two bytes each, low byte first), as 16 hex digits, the same the hosts write.
 * mGBA is built with 16-bit colour, so it works in GBA colours throughout, blending in 5
```
with:
```c
 * - --hashes writes one line a frame: the picture's 64-bit FNV-1a hash (over its colours
 *   as two bytes each, low byte first), as 16 hex digits, the same the hosts write;
 * - --trace runs the game an instruction at a time and writes each indirect transfer it
 *   took once, as "SITE TARGET MODE LR" (gbaport/tracing/transfers.py reads them), but for
 *   ordinary returns and returns to an outer call (see run_frame_traced).
 * mGBA is built with 16-bit colour, so it works in GBA colours throughout, blending in 5
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
#include <mgba/core/log.h>
#include <mgba/gba/core.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
```
with:
```c
#include <mgba/core/log.h>
#include <mgba/gba/core.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/gba/gba.h>

#if !defined(COLOR_16_BIT) || defined(COLOR_5_6_5)
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c

/* ---- pictures ---------------------------------------------------------------------- */
```
with:
```c

/* ---- the trace ----------------------------------------------------------------------- */

/* Taken indirect transfers, each (site, target, state, lr) once, in an open hash table. */
typedef struct {
    uint32_t site, target, lr;
    uint8_t thumb, used;
} Hit;

static Hit *hits;
static size_t hit_slots, hit_count;

static size_t slot(uint32_t site, uint32_t target, uint32_t lr)
{
    uint32_t h = 2166136261u;
    h = (h ^ site) * 16777619u;
    h = (h ^ target) * 16777619u;
    h = (h ^ lr) * 16777619u;
    return h & (hit_slots - 1);
}

static void remember(uint32_t site, uint32_t target, int thumb, uint32_t lr)
{
    if (2 * (hit_count + 1) > hit_slots) {  /* grow: twice the slots, everything again */
        Hit *old = hits;
        size_t old_slots = hit_slots;
        hit_slots = hit_slots ? 2 * hit_slots : 4096;
        hits = calloc(hit_slots, sizeof *hits);
        if (!hits) {
            fprintf(stderr, "error: out of memory for the trace\n");
            exit(3);
        }
        hit_count = 0;
        for (size_t i = 0; i < old_slots; i++)
            if (old[i].used)
                remember(old[i].site, old[i].target, old[i].thumb, old[i].lr);
        free(old);
    }
    size_t i = slot(site, target, lr);
    for (; hits[i].used; i = (i + 1) & (hit_slots - 1))
        if (hits[i].site == site && hits[i].target == target && hits[i].lr == lr
                && hits[i].thumb == thumb)
            return;
    hits[i] = (Hit){site, target, lr, (uint8_t)thumb, 1};
    hit_count++;
}

/* An instruction that may write the PC with a value it does not hold itself: BX, a POP or
 * LDM with the PC, and anything else that writes R15 (B, BL and SWI are direct). */
static int indirect(uint32_t opcode, int thumb)
{
    if (thumb)
        return (opcode & 0xFF00) == 0x4700      /* BX */
            || (opcode & 0xFF00) == 0xBD00      /* POP {..., pc} */
            || (opcode & 0xFF87) == 0x4487      /* ADD pc, rm */
            || (opcode & 0xFF87) == 0x4687;     /* MOV pc, rm */
    uint32_t kind = opcode >> 25 & 7;
    if (kind == 5 || (opcode >> 24 & 15) == 15)
        return 0;                               /* B, BL, SWI */
    if (kind == 4)
        return (opcode >> 20 & 1) && (opcode >> 15 & 1);  /* LDM with the PC */
    return (opcode >> 12 & 15) == 15 || (opcode & 0x0FFFFFF0) == 0x012FFF10;
}

/* The calls in progress, as their return addresses: the shadow of the game's own stack. */
enum { SHADOW = 4096 };
static uint32_t shadow[SHADOW];
static int depth;

/* One frame, an instruction at a time. A transfer that leaves LR pointing just after it is
 * a call (BL, or BX after MOV LR, PC). An indirect transfer to the latest call's return
 * address is an ordinary return; to an outer call's, a return past the calls in between
 * (the runtime unwinds those); anything else is recorded. The BIOS is left out. */
static void run_frame_traced(struct mCore *core)
{
    struct GBA *gba = core->board;
    struct ARMCore *cpu = core->cpu;
    uint32_t frame = gba->video.frameCounter;
    while (gba->video.frameCounter == frame) {
        while (cpu->cycles >= cpu->nextEvent)
            cpu->irqh.processEvents(cpu);
        int thumb = cpu->executionMode == MODE_THUMB;
        uint32_t width = thumb ? 2 : 4, site = cpu->gprs[ARM_PC] - width;
        uint32_t opcode = cpu->prefetch[0], lr = cpu->gprs[ARM_LR];
        ARMRun(cpu);
        if (site < 0x02000000u)
            continue;
        int now_thumb = cpu->executionMode == MODE_THUMB;
        uint32_t target = cpu->gprs[ARM_PC] - (now_thumb ? 2 : 4);
        if (target == site + width)
            continue;  /* not taken */
        if (cpu->gprs[ARM_LR] == (site + width) + (uint32_t)thumb) {
            if (depth == SHADOW) {  /* calls that never return: forget the oldest half */
                memmove(shadow, shadow + SHADOW / 2, sizeof shadow / 2);
                depth -= SHADOW / 2;
            }
            shadow[depth++] = site + width;
            if (!indirect(opcode, thumb))
                continue;  /* BL */
        } else if (!indirect(opcode, thumb) || target < 0x02000000u) {
            continue;
        } else {
            int back = -1;
            for (int i = depth - 1; i >= 0 && back < 0; i--)
                if (shadow[i] == target)
                    back = i;
            if (back >= 0) {  /* a return, ordinary or past calls in progress */
                depth = back;
                continue;
            }
        }
        remember(site, target, now_thumb, lr);
    }
}

static int write_trace(const char *path)
{
    FILE *f = open_file(path, "wb");
    if (!f) {
        fprintf(stderr, "error: cannot write %s\n", path);
        return 3;
    }
    for (size_t i = 0; i < hit_slots; i++)
        if (hits[i].used)
            fprintf(f, "%08x %08x %s %08x\n", (unsigned)hits[i].site, (unsigned)hits[i].target,
                    hits[i].thumb ? "thumb" : "arm", (unsigned)hits[i].lr);
    fclose(f);
    return 0;
}

/* ---- pictures ---------------------------------------------------------------------- */
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
    const char *rom = NULL, *input = NULL, *picture = NULL, *sound_path = NULL, *hashes_path = NULL;
    long frames = -1;
```
with:
```c
    const char *rom = NULL, *input = NULL, *picture = NULL, *sound_path = NULL, *hashes_path = NULL;
    const char *trace_path = NULL;
    long frames = -1;
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
            hashes_path = argv[++i];
        else if (!rom && argv[i][0] != '-')
```
with:
```c
            hashes_path = argv[++i];
        else if (strcmp(argv[i], "--trace") == 0 && value)
            trace_path = argv[++i];
        else if (!rom && argv[i][0] != '-')
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
        fprintf(stderr, "usage: %s ROM --frames N [--input FILE] [--picture PATH] [--sound PATH] "
                "[--hashes PATH]\n", argv[0]);
        return 2;
```
with:
```c
        fprintf(stderr, "usage: %s ROM --frames N [--input FILE] [--picture PATH] [--sound PATH] "
                "[--hashes PATH] [--trace PATH]\n", argv[0]);
        return 2;
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
        core->setKeys(core, keys);
        core->runFrame(core);
        if (hashes)
```
with:
```c
        core->setKeys(core, keys);
        if (trace_path)
            run_frame_traced(core);
        else
            core->runFrame(core);
        if (hashes)
```

In `src/gbaport/native/mgba_oracle/mgba.c`, replace:
```c
        fclose(sound);
    FILE *out = open_out(picture);
```
with:
```c
        fclose(sound);
    if (trace_path && write_trace(trace_path))
        return 3;
    FILE *out = open_out(picture);
```

Create `src/gbaport/tracing/transfers.py`:
```python
"""Traces from gbaport's own mGBA: every indirect transfer a game took while it played.

``gbaport-mgba --trace PATH`` runs the game an instruction at a time and writes each
indirect transfer once, as ``site target mode lr`` (hex, hex, arm or thumb, hex): the
instruction at ``site`` went to ``target`` in ``mode``, with ``lr`` as it was before.
Calls are followed on a shadow stack, so ordinary returns, and returns to an outer
call's return address (which the runtime unwinds), are left out.
"""

from dataclasses import dataclass
from pathlib import Path

from gbaport.isa.model import Mode


class TransferError(ValueError):
    """A transfer file is malformed."""


@dataclass(frozen=True)
class Transfer:
    site: int
    target: int
    mode: Mode
    lr: int


def parse_transfers(text: str, source: str = "transfers") -> set[Transfer]:
    transfers = set()
    for number, line in enumerate(text.splitlines(), start=1):
        fields = line.split()
        if not fields:
            continue
        try:
            site, target, mode, lr = fields
            transfers.add(Transfer(int(site, 16), int(target, 16), Mode(mode), int(lr, 16)))
        except ValueError:
            raise TransferError(f"{source}, line {number}: expected 'SITE TARGET MODE LR', "
                                f"got {line!r}") from None
    return transfers


def load_transfers(path: Path) -> set[Transfer]:
    return parse_transfers(path.read_text(encoding="utf-8"), str(path))
```

- [ ] **Step 5: Run the whole suite**

The first test that needs mGBA builds `gbaport-mgba` again (its source changed), which takes a minute or two.

Run: `uv run pytest`
Expected: 867 passed (858 + 9).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/native src/gbaport/tracing/transfers.py tests/romtest.py tests/gbaroms/calls.c tests/gbaroms/tasks.c tests/gbaroms/bl_loop.c tests/tracing/test_transfers.py
git commit -m "feat: mGBA's program records the indirect transfers a game takes, but for returns to calls in progress"
```

---

### Task 2: `gbaport trace --frames`, and returns that go elsewhere

`gbaport trace ROM --frames N [--input FILE]` plays the game in gbaport-mgba and turns the transfers into the trace file. By default that is `games/<game_code>/traces/mgba.trace`; each run adds to it.
- **The input file** is given to mGBA's program as Python reads it, as `gbaport verify` does.
- **`to_trace`** keeps the transfers whose site the analysis decodes as an instruction that writes the PC (not a `bl`). A transfer at a `bx rN` veneer is recorded at the `bl` before LR. It analyses again with what it added, until a round adds nothing.
- **Without `--frames`,** the command records through mGBA's GDB server as before. `--input` without `--frames` is an error.

Discovery has so far ignored traced targets of a return. It now takes them as entries, like those of a jump that leaves the function. A task switcher returns into another task, where that task last called it, and that place is reached by no call.

Native test builds can now take traces (`run_rom(..., traces=)`).

**Files:**
- Modify: `src/gbaport/tracing/transfers.py` (`to_trace`), `src/gbaport/cli.py` (`trace --frames`, `--input`), `src/gbaport/analysis/discover.py` (traced returns)
- Modify: `tests/romtest.py` (`native_program` and `run_rom` take `traces`)
- Test: `tests/test_trace_mgba.py`

**Interfaces:**
- Consumes: `run_mgba(..., trace=)`, `load_transfers`, `Transfer`, `TestRom.symbols`, the `calls` and `tasks` ROMs (Task 1); `analysis.flow.writes_pc`; `analysis.traces.Hit`, `Trace`, `save_trace`, `load_trace`; `inputs.load_input`, `format_input`; `cli._at_least` (Plan 7a).
- **Produces:**
  - **`to_trace(transfers, analyze: Callable[[Trace], Exploration], trace: Trace) -> int`:** the number of hits added.
  - **`gbaport trace ROM --frames N [--input FILE] [--out PATH] [--config] [--trace]...`:** prints `played N frames in mGBA: T indirect transfers, K new hits` and `wrote PATH (H hits)`.
  - **`native_program(rom, host="headless", traces=())`** and **`run_rom(..., traces=())`**.

- [ ] **Step 1: Write the failing tests**

In `tests/romtest.py`, replace:
```python
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
```
with:
```python
from gbaport.analysis.config import parse_config
from gbaport.analysis.traces import Trace
from gbaport.lift.program import lift_program
```

In `tests/romtest.py`, replace:
```python

def native_program(rom: TestRom, host: str = "headless") -> Path:
    """Recompile ``rom`` and build it with ``host`` (cached by the C sources)."""
    image = RomImage(rom.data)
    analysis = analyze_rom(image, parse_config(rom.config), ())
    lifted = lift_program(analysis.program, analysis.exploration)
```
with:
```python

def native_program(rom: TestRom, host: str = "headless", traces: tuple[Trace, ...] = ()) -> Path:
    """Recompile ``rom`` with ``traces`` and build it with ``host`` (cached by the C
    sources)."""
    image = RomImage(rom.data)
    analysis = analyze_rom(image, parse_config(rom.config), traces)
    lifted = lift_program(analysis.program, analysis.exploration)
```

In `tests/romtest.py`, replace:
```python
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (), env: dict[str, str] | None = None,
) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set).

    The game's save file is ``save``; without one, every run starts with a blank save.
```
with:
```python
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (), env: dict[str, str] | None = None,
    traces: tuple[Trace, ...] = (),
) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set),
    recompiled with ``traces``.

    The game's save file is ``save``; without one, every run starts with a blank save.
```

In `tests/romtest.py`, replace:
```python
    """
    program = native_program(rom, host)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
```
with:
```python
    """
    program = native_program(rom, host, traces)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
```

Create `tests/test_trace_mgba.py`:
```python
"""``gbaport trace --frames N``: the game plays in gbaport's own mGBA, and the calls and
jumps it made through registers become a trace that leads discovery to the code there."""

from romtest import build_test_rom, run_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.analysis.traces import Hit, load_trace
from gbaport.cli import main
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage


def traced(name: str, tmp_path, *args: str):
    rom = build_test_rom(name)
    path = tmp_path / f"{name}.gba"
    path.write_bytes(rom.data)
    out = tmp_path / f"{name}.trace"
    assert main(["trace", str(path), "--frames", "30", "--out", str(out), *args]) == 0
    return rom, load_trace(out)


def unresolved_calls(rom) -> list[int]:
    ex = analyze_rom(RomImage(rom.data), parse_config(rom.config), ()).exploration
    return sorted(issue.addr for issue in ex.issues if issue.kind == "unresolved_call")


def test_trace_records_the_calls_discovery_could_not_follow(tmp_path, capsys):
    """Each at the bl that called the shared bx veneer, so each call site has its own."""
    rom, trace = traced("calls", tmp_path)
    thumb_call, arm_call, _ = unresolved_calls(rom)
    assert Hit(thumb_call, rom.symbols["hidden_thumb"], Mode.THUMB) in trace.hits
    assert Hit(arm_call, rom.symbols["hidden_arm"], Mode.ARM) in trace.hits
    out = capsys.readouterr().out.splitlines()
    assert out[-2].startswith("played 30 frames in mGBA: ")
    assert out[-1] == f"wrote {tmp_path / 'calls.trace'} ({len(trace.hits)} hits)"


def test_a_traced_game_runs_natively(tmp_path):
    rom, trace = traced("calls", tmp_path)
    missing = f"error: no recompiled code at {rom.symbols['hidden_thumb']:#010x}"
    assert missing in run_rom(rom, frames=30).stderr
    run = run_rom(rom, frames=30, traces=(trace,))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 2 passed, 0 failed"


def test_trace_plays_an_input_file(tmp_path):
    """Saved by a Windows editor: a UTF-8 byte order mark and CRLF line ends."""
    (tmp_path / "a.input").write_bytes(b"\xef\xbb\xbf# A from frame 5\r\n5 A\r\n")
    rom, trace = traced("calls", tmp_path, "--input", str(tmp_path / "a.input"))
    pressed_call = unresolved_calls(rom)[2]
    assert Hit(pressed_call, rom.symbols["hidden_pressed"], Mode.THUMB) in trace.hits
    run = run_rom(rom, frames=30, traces=(trace,), args=("--input", str(tmp_path / "a.input")))
    assert run.lines[-1] == "DONE 3 passed, 0 failed", run.stderr


def test_trace_adds_to_the_hits_already_recorded(tmp_path, capsys):
    (tmp_path / "a.input").write_text("5 A\n", encoding="utf-8")
    _, first = traced("calls", tmp_path, "--input", str(tmp_path / "a.input"))
    _, second = traced("calls", tmp_path)  # A not pressed: nothing new, nothing lost
    assert second.hits == first.hits
    assert capsys.readouterr().out.splitlines()[-2].endswith(", 0 new hits")


def test_trace_checks_its_file_before_playing(tmp_path, capsys):
    """A trace of another ROM in the way: nothing is played, nothing is overwritten."""
    rom = tmp_path / "calls.gba"
    rom.write_bytes(build_test_rom("calls").data)
    other = "gbaport-trace/1 " + "0" * 40 + "\n"
    (tmp_path / "calls.trace").write_text(other, encoding="utf-8")
    args = ["trace", str(rom), "--frames", "30", "--out", str(tmp_path / "calls.trace")]
    assert main(args) == 1
    assert "calls.trace: recorded on ROM sha1 0000" in capsys.readouterr().err
    assert (tmp_path / "calls.trace").read_text(encoding="utf-8") == other


def test_an_input_file_needs_frames(tmp_path, capsys):
    rom = tmp_path / "calls.gba"
    rom.write_bytes(build_test_rom("calls").data)
    (tmp_path / "a.input").write_text("5 A\n", encoding="utf-8")
    assert main(["trace", str(rom), "--input", str(tmp_path / "a.input")]) == 1
    assert "--input needs --frames" in capsys.readouterr().err


def test_returns_the_trace_saw_going_elsewhere_lead_discovery_there(tmp_path):
    """switch_task returns into the other task, where that task last called it."""
    rom, trace = traced("tasks", tmp_path)
    ex = analyze_rom(RomImage(rom.data), parse_config(rom.config), (trace,)).exploration
    assert {rom.symbols["yield_b_resumes"], rom.symbols["task_b_resumes"]} <= set(ex.entries)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_trace_mgba.py`
Expected: FAIL — 7 failed: the command does not know `--frames` or `--input` yet, so each run ends in `SystemExit: 2` (`gbaport: error: unrecognized arguments: --frames 30`).

- [ ] **Step 3: The command, the conversion, and traced returns**

In `src/gbaport/analysis/discover.py`, replace:
```python
        elif kind is FlowKind.RETURN:
            here = ()
```
with:
```python
        elif kind is FlowKind.RETURN:
            hits = self.traced.get(ins.addr, ())
            if hits:  # a return that went somewhere other than a caller: entries there
                self._traced_jump(ins, hits, switch=False)
            here = ()
```

In `src/gbaport/cli.py`, replace:
```python
import sys
from pathlib import Path
```
with:
```python
import sys
import tempfile
from pathlib import Path
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.disasm import disassemble, format_line
from gbaport.inputs import load_input
from gbaport.isa.model import Mode
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.rom.header import parse_header
```
with:
```python
from gbaport.disasm import disassemble, format_line
from gbaport.inputs import format_input, load_input
from gbaport.isa.model import Mode
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.native.mgba import run_mgba
from gbaport.rom.header import parse_header
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.tracing.session import TraceSession, check_loaded_rom
from gbaport.verify import verify
```
with:
```python
from gbaport.tracing.session import TraceSession, check_loaded_rom
from gbaport.tracing.transfers import load_transfers, to_trace
from gbaport.verify import verify
```

In `src/gbaport/cli.py`, replace:
```python
    )
    trace.add_argument("--host", default="127.0.0.1", help="GDB server host (default 127.0.0.1)")
```
with:
```python
    )
    trace.add_argument(
        "--frames",
        type=_at_least(1),
        help="play this many frames in gbaport's own mGBA instead of through its GDB server",
    )
    trace.add_argument("--input", help="input file to play (with --frames; default: no keys)")
    trace.add_argument("--host", default="127.0.0.1", help="GDB server host (default 127.0.0.1)")
```

In `src/gbaport/cli.py`, replace:
```python

    client = GdbClient(SocketTransport.connect(args.host, args.port))
```
with:
```python

    if args.frames is not None:
        return _trace_in_mgba(args, recorded, analyze, out)
    if args.input:
        raise ValueError("--input needs --frames (through the GDB server, you play the game)")
    client = GdbClient(SocketTransport.connect(args.host, args.port))
```

In `src/gbaport/cli.py`, replace:
```python
        client.close()
    print(f"wrote {out} ({len(recorded.hits)} hits)")
```
with:
```python
        client.close()
    print(f"wrote {out} ({len(recorded.hits)} hits)")
    return 0


def _trace_in_mgba(args: argparse.Namespace, recorded: Trace, analyze, out: Path) -> int:
    """Plays ``args.frames`` frames in gbaport-mgba and adds what its transfers resolve."""
    with tempfile.TemporaryDirectory() as folder:
        input_file = None
        if args.input:  # the presses as Python reads them (see gbaport/verify.py)
            input_file = Path(folder) / "trace.input"
            input_file.write_text(format_input(load_input(args.input)), encoding="utf-8")
        transfers_file = Path(folder) / "transfers.txt"
        run_mgba(Path(args.rom), args.frames, input=input_file, trace=transfers_file)
        transfers = load_transfers(transfers_file)
    added = to_trace(transfers, analyze, recorded)
    save_trace(recorded, out)
    print(f"played {args.frames} frames in mGBA: {len(transfers)} indirect transfers, "
          f"{added} new hits")
    print(f"wrote {out} ({len(recorded.hits)} hits)")
```

Create `src/gbaport/tracing/transfers.py` (replacing the current version):
```python
"""Traces from gbaport's own mGBA: every indirect transfer a game took while it played.

``gbaport-mgba --trace PATH`` runs the game an instruction at a time and writes each
indirect transfer once, as ``site target mode lr`` (hex, hex, arm or thumb, hex): the
instruction at ``site`` went to ``target`` in ``mode``, with ``lr`` as it was before.
Calls are followed on a shadow stack, so ordinary returns, and returns to an outer
call's return address (which the runtime unwinds), are left out.

``to_trace`` keeps the transfers whose site the analysis decodes as an instruction that
writes the PC, again and again, as the traced targets lead it to more code. A transfer
through a shared ``bx rN`` call veneer is recorded at the ``bl`` that called the veneer
(found from LR), so each call site gets its own targets, as ``gbaport trace`` records
them through mGBA's GDB server.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gbaport.analysis.discover import Exploration
from gbaport.analysis.flow import writes_pc
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode, Op


class TransferError(ValueError):
    """A transfer file is malformed."""


@dataclass(frozen=True)
class Transfer:
    site: int
    target: int
    mode: Mode
    lr: int


def parse_transfers(text: str, source: str = "transfers") -> set[Transfer]:
    transfers = set()
    for number, line in enumerate(text.splitlines(), start=1):
        fields = line.split()
        if not fields:
            continue
        try:
            site, target, mode, lr = fields
            transfers.add(Transfer(int(site, 16), int(target, 16), Mode(mode), int(lr, 16)))
        except ValueError:
            raise TransferError(f"{source}, line {number}: expected 'SITE TARGET MODE LR', "
                                f"got {line!r}") from None
    return transfers


def load_transfers(path: Path) -> set[Transfer]:
    return parse_transfers(path.read_text(encoding="utf-8"), str(path))


def to_trace(transfers: set[Transfer], analyze: Callable[[Trace], Exploration],
             trace: Trace) -> int:
    """Adds to ``trace`` the transfers the analysis can place; returns how many were new."""
    added = 0
    while True:
        ex = analyze(trace)
        veneers = {addr for addr, kind in ex.entry_kinds.items() if kind == "veneer"}
        new = 0
        for transfer in sorted(transfers, key=lambda t: (t.site, t.target, t.lr)):
            ins = ex.instructions.get(transfer.site)
            if ins is None or ins.op is Op.BL or not writes_pc(ins):
                continue
            origin = transfer.site
            if origin in veneers:
                caller = ex.instructions.get((transfer.lr & ~1) - 4)
                if caller is not None and caller.op is Op.BL:
                    origin = caller.addr
            new += trace.add(Hit(origin, transfer.target, transfer.mode))
        added += new
        if not new:
            return added
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: 874 passed (867 + 7).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/tracing/transfers.py src/gbaport/cli.py src/gbaport/analysis/discover.py tests/romtest.py tests/test_trace_mgba.py
git commit -m "feat: gbaport trace --frames plays the game in gbaport's mGBA; traced returns lead discovery on"
```

---

### Task 3: Returns past calls in progress unwind them

A recompiled call runs a chain of functions until the chain comes back to the call's return address. A task switch breaks that: the second task runs inside the first task's call to `switch_task`, then switches back, returning to that call's return address from inside its own calls. The lookup of that address used to miss: `no recompiled code at ...`.
- **The return addresses.** `gba_call` and `gba_call_direct` now keep each running call's return address in `ctx->rets[depth]`.
- **The miss.** `gba_missing` checks a missed address against them, innermost first. On a match it sets `ctx->unwind_depth` to that call's depth and returns `unwinding`, a function that returns the address at once.
- **The way back.** Each chain loop sees `unwind_depth`, and ends unless it is that depth. After every call, the lifter writes `GBA_UNWOUND()`, which returns from the function when `unwind_depth` is set.
- **The call itself** clears it and carries on after its return address.

**Files:**
- Modify: `src/gbaport/lift/gba_cpu.h` (`rets`, `unwind_depth`, `gba_call`, `gba_call_direct`, `GBA_UNWOUND`), `src/gbaport/lift/function.py` (`GBA_UNWOUND();` after each call), `src/gbaport/runtime/runtime.c` (`gba_missing`, `unwinding`)
- Test: `tests/runtime/test_unwind.py`

**Interfaces:**
- Consumes: the `tasks` ROM and `TURNS` (Task 1); `gbaport trace --frames` and `run_rom(..., traces=)` (Task 2).
- **Produces:**
  - **`GbaCtx`:** `uint32_t rets[GBA_MAX_CALL_DEPTH + 1]; uint32_t unwind_depth;`. `GBA_MAX_CALL_DEPTH` is now defined before `GbaCtx`.
  - **`GBA_UNWOUND()`:** a statement the lifter writes after every `gba_call` and `gba_call_direct`.

- [ ] **Step 1: Write the failing tests**

Create `tests/runtime/test_unwind.py`:
```python
"""Returns past calls in progress: when code returns to an outer call's return address (a
task switch, say), the recompiled functions in between return too, as the runtime unwinds
them, and the calls are as deep as before."""

from romtest import build_test_rom, run_rom

from gbaport.analysis.traces import load_trace
from gbaport.cli import main


def traced(rom, tmp_path):
    path = tmp_path / "tasks.gba"
    path.write_bytes(rom.data)
    out = tmp_path / "tasks.trace"
    assert main(["trace", str(path), "--frames", "30", "--out", str(out)]) == 0
    return load_trace(out)


def test_a_task_switch_returns_past_the_other_tasks_calls(tmp_path):
    rom = build_test_rom("tasks")
    run = run_rom(rom, frames=30, traces=(traced(rom, tmp_path),))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 5 passed, 0 failed"


def test_two_thousand_switches_leave_the_calls_as_deep_as_before(tmp_path):
    """The runtime allows 1024 calls in progress: without unwinding, these would pile up.
    Interrupts come in while they run, at times inside the second task's calls."""
    rom = build_test_rom("tasks", "#define TURNS 2000\n")
    run = run_rom(rom, frames=600, traces=(traced(rom, tmp_path),))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 2001 passed, 0 failed"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/runtime/test_unwind.py`
Expected: FAIL — 2 failed, each with `AssertionError: error: no recompiled code at 0x080005ca (Thumb state, lr = 0x080005e9): add it to game.toml [code] thumb_entries, or record a trace`. 0x080005ca is `a_resumes`: the second task switches back by returning to the first task's call, which the runtime does not follow yet.

- [ ] **Step 3: Unwinding**

In `src/gbaport/lift/function.py`, replace:
```python
Thumb state. The lookup ignores that bit; a miss reports it, so the user knows
which state the missing code is in. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address. Blocks that loops
or switches jump back to check for due events, so long loops still let the
scheduler run.

Time is counted as mGBA counts it (gba_cpu.h): each instruction costs the fetch of
```
with:
```python
Thumb state. The lookup ignores that bit; a miss reports it, so the user knows
which state the missing code is in. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address; after it,
``GBA_UNWOUND`` returns too when code went back to a call further out (a task
switch). Blocks that loops or switches jump back to check for due events, so long
loops still let the scheduler run.

Time is counted as mGBA counts it (gba_cpu.h): each instruction costs the fetch of
```

In `src/gbaport/lift/function.py`, replace:
```python
                return [set_lr, refill], False
            return [set_lr, refill, self._call(ins.target, ret, ins.mode)], False
        if op is Op.BL_LO:
```
with:
```python
                return [set_lr, refill], False
            call = self._call(ins.target, ret, ins.mode)
            return [set_lr, refill, call, "GBA_UNWOUND();"], False
        if op is Op.BL_LO:
```

In `src/gbaport/lift/function.py`, replace:
```python
                f"gba_call(ctx, t, {hexu(ret)});",
            ], False
```
with:
```python
                f"gba_call(ctx, t, {hexu(ret)});",
                "GBA_UNWOUND();",
            ], False
```

In `src/gbaport/lift/function.py`, replace:
```python
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
            return body + ["gba_call(ctx, t, ctx->r[14]);"], False
        return body + self._switch(ins) + ["GBA_EXIT(t);"], True
```
with:
```python
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
            return body + ["gba_call(ctx, t, ctx->r[14]);", "GBA_UNWOUND();"], False
        return body + self._switch(ins) + ["GBA_EXIT(t);"], True
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c

typedef struct GbaCtx {
```
with:
```c

#ifndef GBA_MAX_CALL_DEPTH
#define GBA_MAX_CALL_DEPTH 1024u
#endif

typedef struct GbaCtx {
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c
    uint32_t call_depth;        /* gba_call chains currently running */
    /* Timing as mGBA counts it: the wait states of a 16- or 32-bit access to each memory
```
with:
```c
    uint32_t call_depth;        /* gba_call chains currently running */
    uint32_t rets[GBA_MAX_CALL_DEPTH + 1]; /* each running call's return address, by depth */
    uint32_t unwind_depth;      /* nonzero: going back to the call at this depth */
    /* Timing as mGBA counts it: the wait states of a 16- or 32-bit access to each memory
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c

#ifndef GBA_MAX_CALL_DEPTH
#define GBA_MAX_CALL_DEPTH 1024u
#endif

/* Runs the chain that starts at guest address next until it comes back to ret. */
static inline void gba_call(GbaCtx *ctx, uint32_t next, uint32_t ret)
{
    if (++ctx->call_depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    while ((next ^ ret) & ~1u)
        next = ctx->lookup(ctx, next)(ctx);
    ctx->call_depth--;
```
with:
```c

/* Runs the chain that starts at guest address next until it comes back to ret. When code
 * goes to the return address of a call further out instead (gba_missing sets unwind_depth
 * to that call's depth), the chains in between end and their functions return too
 * (GBA_UNWOUND), down to that call, which carries on after its return address. */
static inline void gba_call(GbaCtx *ctx, uint32_t next, uint32_t ret)
{
    uint32_t depth = ++ctx->call_depth;
    if (depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    ctx->rets[depth] = ret;
    while ((next ^ ret) & ~1u) {
        next = ctx->lookup(ctx, next)(ctx);
        if (ctx->unwind_depth) {  /* code went back to a call further out */
            if (ctx->unwind_depth != depth)
                break;
            ctx->unwind_depth = 0;  /* this one: carry on after it */
        }
    }
    ctx->call_depth--;
```

In `src/gbaport/lift/gba_cpu.h`, replace:
```c
static inline void gba_call_direct(GbaCtx *ctx, GbaFn fn, uint32_t ret)
{
    if (++ctx->call_depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    uint32_t next = fn(ctx);
    ctx->call_depth--;
    gba_call(ctx, next, ret);
}

#define GBA_EXIT(target) do { \
```
with:
```c
static inline void gba_call_direct(GbaCtx *ctx, GbaFn fn, uint32_t ret)
{
    uint32_t depth = ++ctx->call_depth;
    if (depth > GBA_MAX_CALL_DEPTH)
        gba_call_overflow(ctx, ret);
    ctx->rets[depth] = ret;
    uint32_t next = fn(ctx);
    ctx->call_depth--;
    if (ctx->unwind_depth) {
        if (ctx->unwind_depth != depth)
            return;
        ctx->unwind_depth = 0;
        next = ret;
    }
    gba_call(ctx, next, ret);
}

/* After a call: when code went back to a call further out, this function returns too. */
#define GBA_UNWOUND() do { \
        if (ctx->unwind_depth) return ctx->rets[ctx->unwind_depth]; \
    } while (0)

#define GBA_EXIT(target) do { \
```

In `src/gbaport/runtime/runtime.c`, replace:
```c

/* addr has bit 0 set when execution was to go on in Thumb state. */
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
{
    int thumb = addr & 1;
```
with:
```c

/* What a lookup of an outer call's return address runs: it goes back there at once, and
 * the calls in between see unwind_depth and return too (gba_call, GBA_UNWOUND). */
static uint32_t unwinding(GbaCtx *ctx)
{
    return ctx->rets[ctx->unwind_depth];
}

/* addr has bit 0 set when execution was to go on in Thumb state. The return address of a
 * call further out is not missing code: execution goes back to that call (the innermost,
 * if several), as when a task switch returns into the task that called it. */
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
{
    for (uint32_t depth = ctx->call_depth; depth > 0; depth--)
        if (!((ctx->rets[depth] ^ addr) & ~1u)) {
            ctx->unwind_depth = depth;
            return unwinding;
        }
    int thumb = addr & 1;
```

- [ ] **Step 4: Run the whole suite**

Every test program is built again (the lifter and the runtime changed), which can take several minutes.

Run: `uv run pytest`
Expected: 876 passed (874 + 2).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/lift/gba_cpu.h src/gbaport/lift/function.py src/gbaport/runtime/runtime.c tests/runtime/test_unwind.py
git commit -m "feat: a return to an outer call's return address unwinds the calls in between"
```

---

### Task 4: The user's game into its first fight

`games/BT4E/first-fight.input` plays the user's game from power-on through the menus into its first fight. `gbaport trace` records its trace with it into `games/BT4E/traces/mgba.trace`; like `game.toml`, both hold no ROM bytes. A test reads every committed game file as gbaport reads it. The README and the spec describe the new trace recorder and unwinding.

**Files:**
- Create: `games/BT4E/first-fight.input`, `games/BT4E/traces/mgba.trace` (recorded in Step 4)
- Modify: `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`
- Test: `tests/test_games.py`

**Interfaces:**
- Consumes: everything above; `analysis.config.load_config`.
- Produces: no code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_games.py`:
```python
"""What the games folder keeps for each game (no ROM bytes: addresses, key names and frame
numbers) reads as gbaport reads it."""

from pathlib import Path

import pytest

from gbaport.analysis.config import load_config
from gbaport.analysis.traces import load_trace
from gbaport.inputs import load_input

GAMES = Path(__file__).parent.parent / "games"


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/game.toml")), ids=lambda p: p.parent.name)
def test_the_games_configs_read(path):
    load_config(path)


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/*.input")), ids=lambda p: p.name)
def test_the_games_input_files_read(path):
    assert load_input(path)


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/traces/*.trace")),
                         ids=lambda p: f"{p.parent.parent.name}-{p.name}")
def test_the_games_traces_read(path):
    assert load_trace(path).hits


def test_the_users_game_has_its_way_into_the_first_fight():
    """The README's commands play 4200 frames of it."""
    assert load_input(GAMES / "BT4E" / "first-fight.input")[-1].frame < 4200
    assert load_trace(GAMES / "BT4E" / "traces" / "mgba.trace").hits
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_games.py`
Expected: FAIL — 1 failed, 1 passed, 2 skipped.
- `test_the_users_game_has_its_way_into_the_first_fight` fails with `FileNotFoundError` for `games\BT4E\first-fight.input`.
- BT4E's `game.toml` reads.
- There is no input file or trace to read yet: the two other tests have empty parameter sets and are skipped.

- [ ] **Step 3: The input file and the documentation**

In `README.md`, replace:
```markdown
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]
```
with:
```markdown
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba --frames 4200 [--input FILE]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]
```

In `README.md`, replace:
```markdown
message says) and build again, or record a trace with mGBA (below).
`games/BT4E/game.toml` is an example: the entries Dragon Ball GT Transformation needs to
boot and play its first minute.

The game's time is counted as mGBA counts it: each instruction costs its fetches at the
```
with:
```markdown
message says) and build again, or record a trace with mGBA (below).
`games/BT4E/game.toml` is an example: the entries Dragon Ball GT Transformation needs to
boot and play its first minute. With `games/BT4E/traces/mgba.trace`, recorded from
`games/BT4E/first-fight.input`, it plays on into its first fight.

Some games switch between tasks, each on its own stack: a task "returns" into another one,
where that one last switched away, past the calls the first task made since. The runtime
keeps each running call's return address, so when code goes to the return address of a
call further out, the recompiled functions in between return too, and the calls are as
deep as before.

The game's time is counted as mGBA counts it: each instruction costs its fetches at the
```

In `README.md`, replace:
```markdown
The headless and window programs play one with `--input FILE`.

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA (0.10 or newer, dev machine only) and records where its indirect calls
and jumps go:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
```
with:
```markdown
The headless and window programs play one with `--input FILE`.

`games/BT4E/first-fight.input` plays Dragon Ball GT Transformation from power-on into its
first fight. Through the menus and the fight's first seconds, the pictures stay within a
frame of mGBA's:

    uv run gbaport verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input
    verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart

Further on they part, at frame 3627: where the native build has come a frame early, a press
reaches the game a frame later in its own time, so the fighter it moves is one step behind
the rest of the picture; by frame 3837 the fight goes its own way.

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA and records where its indirect calls and jumps go, into
`games/<game_code>/traces/mgba.trace` (addresses only, safe to commit), which every
command reads. Each run adds to the file.

With `--frames N`, gbaport's own mGBA plays the game from power-on, holding the keys an
input file names (`--input`):

    uv run gbaport trace roms/mygame.gba --frames 4200 --input games/BT4E/first-fight.input
    played 4200 frames in mGBA: 914 indirect transfers, 729 new hits

It runs the game an instruction at a time and follows its calls on a stack of its own, so
it leaves out returns to the latest call and to calls further out (the runtime unwinds
those, above), and keeps every other jump through a register. A call through a shared
`bx rN` veneer is recorded at the `bl` that called the veneer, so each call site gets its
own targets.

Without `--frames`, it records what you play in mGBA's window (0.10 or newer, dev machine
only), through mGBA's GDB server:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
  end, so nesting deeper than `GBA_MAX_CALL_DEPTH` (1024) aborts through the runtime's
  `gba_call_overflow` with the return address.
- **Memory.** Region page table (`addr >> 24`) with fast paths for EWRAM, IWRAM, VRAM, OAM,
```
with:
```markdown
  end, so nesting deeper than `GBA_MAX_CALL_DEPTH` (1024) aborts through the runtime's
  `gba_call_overflow` with the return address. Each running call keeps its return address:
  code that goes to the return address of a call further out (a task switch) ends the
  calls in between too (Plan 7b).
- **Memory.** Region page table (`addr >> 24`) with fast paths for EWRAM, IWRAM, VRAM, OAM,
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown

Traces recorded with `gbaport trace` live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
```
with:
```markdown

Traces recorded with `gbaport trace` (gbaport's mGBA playing an input file, or mGBA's
GDB server while someone plays) live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
```

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
```markdown
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
- mGBA 0.10.5's GBA core, built from source by gbaport (16-bit colour, no dependencies)
  as the renderer's reference (Plan 5), the sound's (Plan 6), and the timing's and
  `gbaport verify`'s (Plan 7a).

## Risks
```
with:
```markdown
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.
- mGBA 0.10.5's GBA core, built from source by gbaport (16-bit colour, no dependencies)
  as the renderer's reference (Plan 5), the sound's (Plan 6), the timing's and
  `gbaport verify`'s (Plan 7a), and `gbaport trace --frames`'s (Plan 7b).

## Risks
```

Create `games/BT4E/first-fight.input`:
```
# Dragon Ball GT Transformation (BT4E): from power-on into its first fight.
# Frames count from power-on, 60 a second; each line holds its keys from that frame on
# (gbaport/inputs.py). Played by `gbaport trace` and `gbaport verify` (README).

900 A          # past the title screen
906 none
1100 A         # the menu's first choice
1106 none

# the opening's scenes, skipped one at a time
1700 START
1706 none
1760 START
1766 none
1820 START
1826 none
1880 START
1886 none
1940 START
1946 none
2000 START
2006 none
2060 START
2066 none
2120 START
2126 none
2180 START
2186 none
2240 START
2246 none
2300 START
2306 none
2360 START
2366 none

2500 A         # the first stage's choice
2506 none

# the scenes before the fight
3300 START
3306 none
3360 START
3366 none
3420 START
3426 none

# the fight: RIGHT, A ten times, LEFT, then B, A with RIGHT, and B again
3500 RIGHT
3600 none
3620 A
3625 none
3640 A
3645 none
3660 A
3665 none
3680 A
3685 none
3700 A
3705 none
3720 A
3725 none
3740 A
3745 none
3760 A
3765 none
3780 A
3785 none
3800 A
3805 none
3820 LEFT
3880 B
3886 none
3900 A+RIGHT
3960 none
3980 B
3985 none
4010 B
4015 none
4040 B
4045 none
4070 B
4075 none
4100 B
4105 none
4130 B
4135 none
4160 B
4165 none
```

- [ ] **Step 4: Record the user's game's trace**

Run, from the repo root:

```bash
uv run python -m gbaport.cli trace roms/mygame.gba --frames 4200 --input games/BT4E/first-fight.input
```

Expected (validated before this plan was approved): `played 4200 frames in mGBA: 914 indirect transfers, 729 new hits` and `wrote games\BT4E\traces\mgba.trace (729 hits)`, in about 15 seconds.

`games/BT4E/traces/mgba.trace` holds addresses only: a `gbaport-trace/1` header with the ROM's SHA-1, then `site target mode` lines.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: 880 passed (876 + 4).

Run: `uv run ruff check src tests`
Expected: All checks passed!

- [ ] **Step 6: Verify the user's game against mGBA**

Run, from the repo root:

```bash
uv run python -m gbaport.cli verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input; echo "exit $?"
uv run python -m gbaport.cli verify roms/mygame.gba --frames 4200 --input games/BT4E/first-fight.input; echo "exit $?"
```

Expected (validated before this plan was approved):
- `verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart`, exit 0.
- `the pictures part at frame 3627 (mGBA's frame 3628)` and `wrote build\BT4E-verify\frame-3627.png (ours, then mGBA's)`, exit 1: the fight's limitation (Known limitations).
- `build/` is ignored by git; the program, the hash files and the PNG stay on this machine.

Record the lines in the ledger.

- [ ] **Step 7: Commit**

```bash
git add tests/test_games.py games/BT4E/first-fight.input games/BT4E/traces/mgba.trace README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "feat: the user's game plays into its first fight with its input file and trace"
```

---

## Done criteria for Plan 7b

- `uv run pytest` passes 880 tests and `uv run ruff check src tests` is clean.
- **mGBA's program traces a game:** calls and jumps through registers, and returns no call in progress came from. It leaves out returns to calls in progress, and keeps going through calls that never return.
- **`gbaport trace --frames N [--input FILE]`** turns them into the game's trace, at the `bl` of a veneer call. Discovery follows traced returns.
- **A return to an outer call's return address** unwinds the calls in between: two thousand task switches, with interrupts, leave the calls as deep as before.
- **The user's game** plays from power-on into its first fight natively (4200 frames, no error), and `gbaport verify` keeps its first 3600 frames within a frame of mGBA's.
