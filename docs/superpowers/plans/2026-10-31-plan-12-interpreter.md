# Plan 12: The Interpreter — Implementation Plan

> Carry this plan out task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Code the build did not recompile runs in an interpreter instead of stopping the game, by the same rules as recompiled code, so the game plays on with the same pictures. The hosts list where it ran. `gbaport learn` and `gbaport build` recompile those places next time.

**Architecture:**
- **A decoder in C (`runtime/decode.c`).** It decodes ARM and Thumb instructions field for field as `isa/arm.py` and `isa/thumb.py` do. A test compares the two on every Thumb halfword and on 310,000 ARM words.
- **The interpreter (`runtime/interp.c`).** It runs what `lift/semantics.py` and `lift/function.py` would have generated for each instruction, as the instruction is decoded:
  - the same effects and the same cycles, charged at the same moments;
  - calls run as nested `gba_call` chains;
  - it leaves at the current call's return address, at recompiled code (`ctx->find`), at an outer call's return address, or through a register jump.
  - The lifter's Unicorn and ARMv4 tests run interpreted too.
- **One rule for event checks.** Code checks for due events at every taken branch back to an address at or before the branch, and at every jump through a register that is not a call, and nowhere else.
  - Recompiled code used to check at loop-head labels and at function exits, which depend on where functions begin and end.
  - Every loop still has a check, and the interpreter checks at the same instructions.
  - A test counts the checks both ways. BT4E against mGBA is unchanged.
- **The runtime.**
  - `gba_missing` hands code the build missed to the interpreter. It still fails where there can be no code: past the ROM's end, or memory that holds none.
  - The places it ran from go on a list: `GbaPlace`, which the hosts write with `--places`. The window keeps it next to its save; on the phone it is in the app's storage.
  - The dispatcher finds a function only in the state it was recompiled in, and a direct call happens only within one state.
- **`--interpret-all`.** No recompiled code runs. 14 test ROMs and jsmolka's ROMs give the same lines, pictures and cycles either way. BT4E gives the same picture hash every frame for 3600 frames, about 13 times faster than real time on the PC.
- **`gbaport learn`.**
  - It replays the recording with a places file of its own, learns every place in one round, rebuilds and replays again until nothing runs interpreted. A place that stays interpreted once learned is named and left out.
  - `gbaport build` learns the places in the ROM from the window's list.
  - BT4E with no hand-written entries and no trace plays `walk-right.input` to its end (32 places interpreted). `learn` recompiles all of it (34 places, 112 s).

**Tech Stack:** Python 3.15 (uv), pytest, ruff; C11 (clang); Unicorn (the lifter's oracle); mGBA 0.10.5's core (`gbaport verify`).

**Spec:** `docs/superpowers/specs/2026-10-28-any-rom-design.md` (section 1 "The fallback interpreter" and section 2 "The run log, and learning from it", roadmap row "12 Fallback interpreter"), on top of `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`.

## Global Constraints

- **From the design, verbatim.**
  - Anti-goals:
    - "The app silently running recompiled RAM code whose bytes the game has since changed."
    - "Native and interpreted code disagreeing: a game must draw the same pictures whether a piece of its code ran native or interpreted."
    - "BT4E getting slower on the phone once its code is native, or `gbaport verify` getting worse than today for BT4E (3600 frames: 1211 pictures in the same order, at most 1 frame apart)."
  - "Each interpreted instruction costs exactly the cycles its recompiled version would."
  - "Speed target. On the PC, headless, BT4E with every function interpreted runs at least as fast as the GBA does (60 frames a second)."
  - "An undefined instruction still stops the game with the message it gives today."
  - "mGBA stays a development tool only and never ships in an app."
- **Rulings this plan makes on the design** (each also in its task):
  - **The run log holds addresses only.** RAM bytes and the hashed RAM code are Plan 13's. `learn` replays the recording, which runs the same code again, so it needs no copy of the phone's log; the phone still keeps its list next to its save.
  - **`gbaport build` learns only the places in the ROM.** Places in RAM go through `learn`, which checks that learning one helps; a RAM place it cannot recompile would otherwise come back on every build.
  - **The design's acceptance item 3 is checked on BT4E with no hand-written entries and no trace.** A copy of its `game.toml` with only `sha1` and `sweep` is used, in a scratch folder; the repository's `games/BT4E` stays as it is until Plan 13.
- **The user's rules.**
  - Commits use the repository's git identity (Ken). No `Co-Authored-By` or any other trailer, and nothing in a commit or a committed file names the tools that wrote it.
  - Never commit a `.gba` file or anything from `roms/` or `build/`.
  - Tests never open a window and never play sound.
  - Whoever carries out or reviews this plan never reads or prints bytes of `roms/` or `build/`.
- **Commands.**
  - Smart App Control can block `uv.exe` and the `gbaport.exe` launcher, so every command runs the project's Python from the repository's root: `.venv/Scripts/python.exe -m gbaport.cli ...`, `.venv/Scripts/python.exe -m pytest`, `.venv/Scripts/python.exe -m ruff check src tests`.
  - Run the tests and ruff as separate commands, and never two test runs at once.
  - A whole-suite run that includes the Android emulator tests takes 8 to 30 minutes. Run it in the foreground; a background run can be stopped when memory runs short.
  - Smart App Control sometimes refuses a freshly built test program ("An Application Control policy has blocked this file"). A test that fails that way passes when run again.
  - Write code that holds backslashes with the Edit or Write tools, never a shell heredoc.

## Review Focus

1. **A call into code recompiled in the other state.** Example: a Thumb `bl` to a `bx pc` veneer that the sweep guessed as ARM code. The call must run that code in the caller's state, in the interpreter, not run its bytes in the wrong state. Pinned in Task 5 (`test_a_call_runs_the_code_in_the_state_it_calls_in`, `tests/gbaroms/wrong_state.c`).
2. **A task switch while interpreted code is on the call stack.** Code goes to an outer call's return address. The interpreter must hand that back to the dispatcher so `gba_missing` unwinds the calls in between, as for recompiled code. Pinned in Task 5 (the `tasks` test ROM, recompiled and interpreted, gives the same lines and pictures).
3. **An interrupt while interpreted code runs.** The handler runs as a nested call, and the interrupted code goes on where it was, in its own state. Pinned in Task 4 (`test_code_the_analysis_cannot_recompile_stays_interpreted`: the `interrupts` ROM's IWRAM handler runs interpreted and all its interrupt tests pass) and in Task 5 (the `interrupts`, `hblank_irq` and `intrwait_ime` ROMs give the same results both ways).
4. **A jump to where there can be no code** (past the end of the ROM). It must stop with the address, not run open-bus values as instructions. Pinned in Task 4 (`test_a_jump_to_where_there_can_be_no_code_names_the_address`, `test_learn_stops_at_a_jump_to_where_there_can_be_no_code`).
5. **A places file from another ROM next to the save.** It must be ignored and written anew, not merged into this game's list. `read_places` checks the CRC32 in the file's first line (Task 4), and so does `load_places` in `host_common.c`. Pinned in Task 4 through `learn`'s replay (its own new file) and in Task 6 (`test_build_learns_the_places_the_window_ran_interpreted`).

## Known limitations (deliberate; later plans)

- Code the game copies to RAM is learned only when the analysis knows where it came from (a detected DMA or CpuSet copy, or `[[ram_code]]`). Otherwise it stays interpreted and `learn` names it (Plan 13: RAM code by content).
- An interpreted function that rewrites its own instructions while it runs is not caught; the interpreter decodes each instruction as it fetches it, so code that changes between runs is run as it is now.
- No decode cache: the interpreter decodes every instruction it runs. Fully interpreted, BT4E runs at about 770 frames a second on the PC; the phone is not measured (no phone was connected).
- The interrupted code's resume address in `lr_irq` is still not known while recompiled code runs (the IRQ entry pushes 0, as before).

---

### Task 1: The decoder in C

**Files:**
- Create: `src/gbaport/runtime/decode.h`, `src/gbaport/runtime/decode.c`
- Test: `tests/runtime/test_decode.py`, `tests/decodehost.c`, `tests/hostkit.py`

**Interfaces:**
- Produces: `decode.h` as below (the interpreter's input), `hostkit.host_program(name, sources, headers) -> Path` (later tests build their C hosts with it).

```c
/* decode.h - ARMv4T instructions decoded as gbaport's analysis decodes them (isa/arm.py,
 * isa/thumb.py): Thumb instructions become the equivalent ARM operation, and anything
 * outside ARMv4T is GBA_OP_UNDEFINED. The interpreter (interp.c) runs what this gives. */
#ifndef GBA_DECODE_H
#define GBA_DECODE_H

#include <stdint.h>

typedef enum {
    /* the ARM data-processing opcodes, in their field's order */
    GBA_OP_AND, GBA_OP_EOR, GBA_OP_SUB, GBA_OP_RSB, GBA_OP_ADD, GBA_OP_ADC, GBA_OP_SBC,
    GBA_OP_RSC, GBA_OP_TST, GBA_OP_TEQ, GBA_OP_CMP, GBA_OP_CMN, GBA_OP_ORR, GBA_OP_MOV,
    GBA_OP_BIC, GBA_OP_MVN,
    GBA_OP_MUL, GBA_OP_MLA, GBA_OP_UMULL, GBA_OP_UMLAL, GBA_OP_SMULL, GBA_OP_SMLAL,
    GBA_OP_LDR, GBA_OP_STR, GBA_OP_LDRB, GBA_OP_STRB, GBA_OP_LDRH, GBA_OP_STRH,
    GBA_OP_LDRSB, GBA_OP_LDRSH, GBA_OP_LDM, GBA_OP_STM, GBA_OP_SWP, GBA_OP_SWPB,
    GBA_OP_B, GBA_OP_BL, GBA_OP_BX, GBA_OP_SWI, GBA_OP_MRS, GBA_OP_MSR, GBA_OP_BL_HI,
    GBA_OP_BL_LO, GBA_OP_UNDEFINED,
} GbaOp;

enum { GBA_COND_AL = 0xE };
enum { GBA_SHIFT_NONE, GBA_SHIFT_LSL, GBA_SHIFT_LSR, GBA_SHIFT_ASR, GBA_SHIFT_ROR, GBA_SHIFT_RRX };
#define GBA_NO_REG (-1)

typedef struct GbaInsn {
    uint32_t addr, raw;
    uint32_t imm;            /* valid when has_imm */
    uint32_t target;         /* valid when has_target: a branch's or PC-relative access's address */
    uint16_t reglist;        /* LDM/STM: bit n = register n */
    uint8_t op, cond, size, thumb;
    uint8_t s, pre, up, writeback, user, spsr, psr_mask, imm_rot;
    uint8_t has_imm, has_target;
    uint8_t shift_kind, shift_amount;  /* GBA_SHIFT_*, immediate amount (LSR/ASR #32 kept) */
    int8_t shift_reg;                  /* register holding the amount, or GBA_NO_REG */
    int8_t rd, rn, rm, rs, rd_hi;      /* GBA_NO_REG when the instruction has none */
} GbaInsn;

void gba_decode_arm(uint32_t word, uint32_t addr, GbaInsn *out);
/* next is the following halfword (a BL prefix pairs with a suffix into one 4-byte BL), or
 * -1 when there is none. */
void gba_decode_thumb(uint32_t halfword, uint32_t addr, int32_t next, GbaInsn *out);

#endif
```

- [ ] **Step 1: Write the failing test**

Create `tests/hostkit.py`:
```python
"""Small C test programs built from runtime sources, once per version of those sources."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.toolchain import find_clang

TESTS = Path(__file__).parent


def host_program(name: str, sources: list[Path], headers: list[Path] = ()) -> Path:
    """``name`` compiled from ``sources`` with the runtime's headers, rebuilt with a salt when
    Windows' Smart App Control refuses to start it, as gbaport build does."""
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in (*sources, *headers))).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / f"gbaport-{name}" / digest
    program = folder / (f"{name}.exe" if os.name == "nt" else name)
    if program.exists():
        return program
    folder.mkdir(parents=True, exist_ok=True)
    salt = folder / "salt.c"
    for _ in range(native.SALTED_REBUILDS):
        salt.write_text(f'const char {name}_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        subprocess.run(
            [find_clang(), "-std=c11", "-O2", "-Wall", "-Werror", f"-I{native.RUNTIME}",
             f"-I{native.PACKAGE / 'lift'}", *map(str, sources), str(salt), "-o", str(program)],
            check=True, capture_output=True,
        )
        if native._starts(program):
            return program
    raise AssertionError(f"Windows refused to start {name}")
```

Create `tests/decodehost.c`:
```c
/* decodehost.c - runtime/decode.c's view of instructions, for tests/runtime/test_decode.py.
 *
 * Reads lines from stdin and prints one line of decoded fields per line:
 *     arm WORD ADDR
 *     thumb HALFWORD ADDR NEXT     NEXT is the following halfword, or - for none
 * (numbers in hex). The fields: op cond size raw s rd rn rm rs rd_hi imm target imm_rot
 * shift pre up writeback user reglist spsr psr_mask, with - for a field the instruction
 * does not have, and shift as kind/amount/register. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <string.h>

#include "decode.h"

static const char *const OPS[] = {
    "and", "eor", "sub", "rsb", "add", "adc", "sbc", "rsc", "tst", "teq", "cmp", "cmn", "orr",
    "mov", "bic", "mvn", "mul", "mla", "umull", "umlal", "smull", "smlal", "ldr", "str", "ldrb",
    "strb", "ldrh", "strh", "ldrsb", "ldrsh", "ldm", "stm", "swp", "swpb", "b", "bl", "bx", "swi",
    "mrs", "msr", "bl_hi", "bl_lo", "undefined",
};
static const char *const SHIFTS[] = {"-", "lsl", "lsr", "asr", "ror", "rrx"};

static void reg(int8_t r)
{
    if (r == GBA_NO_REG) printf(" -");
    else printf(" %d", r);
}

int main(void)
{
    char line[128], kind[16], next[16];
    unsigned a, b;
    while (fgets(line, sizeof line, stdin)) {
        GbaInsn i;
        if (sscanf(line, "%15s %x %x %15s", kind, &a, &b, next) >= 3 && strcmp(kind, "arm") == 0) {
            gba_decode_arm(a, b, &i);
        } else if (strcmp(kind, "thumb") == 0) {
            unsigned n;
            gba_decode_thumb(a, b, sscanf(next, "%x", &n) == 1 ? (int32_t)n : -1, &i);
        } else {
            fprintf(stderr, "decodehost: bad line %s", line);
            return 2;
        }
        printf("%s %u %u %08x %u", OPS[i.op], i.cond, i.size, (unsigned)i.raw, i.s);
        reg(i.rd); reg(i.rn); reg(i.rm); reg(i.rs); reg(i.rd_hi);
        if (i.has_imm) printf(" %08x", (unsigned)i.imm); else printf(" -");
        if (i.has_target) printf(" %08x", (unsigned)i.target); else printf(" -");
        printf(" %u", i.imm_rot);
        if (i.shift_kind == GBA_SHIFT_NONE) printf(" -");
        else if (i.shift_reg == GBA_NO_REG) printf(" %s/%u/-", SHIFTS[i.shift_kind], i.shift_amount);
        else printf(" %s/%u/%d", SHIFTS[i.shift_kind], i.shift_amount, i.shift_reg);
        printf(" %u %u %u %u %04x %u %u\n", i.pre, i.up, i.writeback, i.user, i.reglist, i.spsr,
               i.psr_mask);
    }
    return 0;
}
```

Create `tests/runtime/test_decode.py`:
```python
"""runtime/decode.c decodes every instruction as the analysis does (isa/arm.py, isa/thumb.py)."""

import random
import subprocess

from hostkit import TESTS, host_program

import gbaport.native.build as native
from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Instruction
from gbaport.isa.thumb import decode_thumb


def _decoded(lines: list[str]) -> list[str]:
    program = host_program("decodehost", [TESTS / "decodehost.c", native.RUNTIME / "decode.c"],
                           [native.RUNTIME / "decode.h"])
    out = subprocess.run([str(program)], input="\n".join(lines) + "\n", capture_output=True,
                         text=True, timeout=120, check=True).stdout
    return out.splitlines()


def _fields(ins: Instruction) -> str:
    """The analysis's instruction as decodehost prints one."""
    def opt(v, fmt="{}"):
        return "-" if v is None else fmt.format(v)

    shift = "-" if ins.shift is None else \
        f"{ins.shift.kind.value}/{ins.shift.amount}/{opt(ins.shift.reg)}"
    regs = " ".join(opt(r) for r in (ins.rd, ins.rn, ins.rm, ins.rs, ins.rd_hi))
    mask = sum(1 << r for r in ins.reglist)
    return (f"{ins.op.value} {int(ins.cond)} {ins.size} {ins.raw:08x} {int(ins.s)} {regs} "
            f"{opt(None if ins.imm is None else ins.imm & 0xFFFFFFFF, '{:08x}')} "  # BL_HI: negative
            f"{opt(ins.target, '{:08x}')} {ins.imm_rot} {shift} "
            f"{int(ins.pre)} {int(ins.up)} {int(ins.writeback)} {int(ins.user)} {mask:04x} "
            f"{int(ins.spsr)} {ins.psr_mask}")


def _compare(lines: list[str], expected: list[str]) -> None:
    got = _decoded(lines)
    wrong = [f"{line}: {g} != {e}" for line, g, e in zip(lines, got, expected) if g != e]
    assert len(got) == len(expected)
    assert not wrong, f"{len(wrong)} differ:\n" + "\n".join(wrong[:10])


def _address(rng: random.Random, align: int) -> int:
    return rng.choice([0x08000000, 0x03000000, 0xFFFFFF00, rng.getrandbits(32)]) & ~(align - 1)


def test_every_thumb_halfword_decodes_as_the_analysis_decodes_it():
    rng = random.Random(1)
    lines, expected = [], []
    for hw in range(0x10000):
        addr = _address(rng, 2)
        nxt = rng.choice([None, rng.getrandbits(16), 0xF800 | rng.getrandbits(11)])
        lines.append(f"thumb {hw:x} {addr:x} {'-' if nxt is None else f'{nxt:x}'}")
        expected.append(_fields(decode_thumb(hw, addr, nxt)))
    _compare(lines, expected)


# Encodings random words rarely hit: (value, mask) of each special case's fixed bits.
ARM_PATTERNS = [
    (0x012FFF10, 0x0FFFFFF0), (0x00000090, 0x0FC000F0), (0x00800090, 0x0F8000F0),
    (0x01000090, 0x0FB00FF0), (0x00000090, 0x0E000090), (0x010F0000, 0x0FBF0FFF),
    (0x0120F000, 0x0FB0FFF0), (0x0320F000, 0x0FB0F000), (0x01000000, 0x0F900000),
    (0x0000F000, 0x0000F000), (0x000F0000, 0x000F0000),  # Rd or Rn = pc
]


def test_arm_words_decode_as_the_analysis_decodes_them():
    rng = random.Random(2)
    words = [rng.getrandbits(32) for _ in range(200_000)]
    for value, mask in ARM_PATTERNS:
        words += [(rng.getrandbits(32) & ~mask) | value for _ in range(10_000)]
    lines, expected = [], []
    for word in words:
        addr = _address(rng, 4)
        lines.append(f"arm {word:x} {addr:x}")
        expected.append(_fields(decode_arm(word, addr)))
    _compare(lines, expected)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_decode.py`
Expected: FAIL: 2 failed, `FileNotFoundError` (no `decode.c`).

- [ ] **Step 3: Create `decode.h` (above) and `decode.c`: `gba_decode_arm(word, addr, out)` and `gba_decode_thumb(halfword, addr, next, out)`**

Each branch of `isa/arm.py` and `isa/thumb.py` becomes the same branch in C, in the same order, with the same field values:
- A fresh `GbaInsn` has `cond = GBA_COND_AL`, `pre = up = 1`, every register `GBA_NO_REG`, `size` 4 (ARM) or 2 (Thumb), and `thumb` set for Thumb.
- `Shift.from_imm_field`: LSL #0 is no shift, ROR #0 is RRX, and LSR/ASR #0 keep amount 32. A register shift has amount 0 and `shift_reg`.
- `reglist` is the bit mask of the Python tuple; Thumb's push and pop add r14 and r15 as bits 14 and 15.
- A Thumb BL prefix pairs into one 4-byte BL (`raw = hw | next << 16`) only when `next` is a suffix (`(next & 0xF800) == 0xF800`). Otherwise it is `GBA_OP_BL_HI` with the sign-extended high offset in `imm`.
- PC-relative literal loads and Thumb ADR get their absolute `target`, word-aligned for Thumb.

The file's comment says it follows the Python decoders field for field.

- [ ] **Step 4: Run the test to verify it passes, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_decode.py`
Expected: 2 passed.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 970 passed.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/decode.h src/gbaport/runtime/decode.c tests/decodehost.c tests/hostkit.py tests/runtime/test_decode.py
git commit -m "feat: the runtime decodes ARM and Thumb instructions as the analysis does"
```

---

### Task 2: The interpreter

**Files:**
- Create: `src/gbaport/runtime/interp.h`, `src/gbaport/runtime/interp.c`, `tests/lift/conftest.py`
- Modify: `src/gbaport/lift/gba_cpu.h`, `tests/lifthost.c`, `tests/liftkit.py`, `tests/lift/test_control_flow.py`, `pyproject.toml`

**Interfaces:**
- Consumes: `GbaInsn`, `gba_decode_arm`, `gba_decode_thumb` (Task 1).
- Produces:
  - `interp.h` as below;
  - `GbaCtx` gains `find` (the recompiled function at an address, or NULL), `interp_pc` (where `gba_interpret` starts, bit 0 for Thumb) and `interpreted` (instructions the interpreter has run);
  - `liftkit.MODE` (`"recompiled"` or `"interpreted"`) and `liftkit.run_interpreted(cases) -> list[Outcome]`.

```c
/* interp.h - running guest code that was not recompiled.
 *
 * gba_interpret is a GbaFn: gba_missing hands it the address the dispatcher found no
 * recompiled function for (ctx->interp_pc, bit 0 set for Thumb state), and it runs the
 * code there by the rules recompiled code follows (lift/function.py, lift/semantics.py):
 * the same instruction semantics, the same cycles charged at the same moments, events
 * checked at backward branches and jumps through registers, calls run as nested
 * gba_call chains. It returns the address execution continues at when control reaches
 * the current call's return address, recompiled code (ctx->find), an outer call's return
 * address, or leaves through a register jump.
 *
 * The runtime (or a test host) provides instruction fetches. */
#ifndef GBA_INTERP_H
#define GBA_INTERP_H

#include "gba_cpu.h"

uint32_t gba_interpret(GbaCtx *ctx);

uint32_t gba_fetch16(GbaCtx *ctx, uint32_t addr);
uint32_t gba_fetch32(GbaCtx *ctx, uint32_t addr);

#endif
```

- [ ] **Step 1: Write the failing tests: every lifter test runs interpreted too**

The lifter's tests compare recompiled code with Unicorn. `tests/lift/conftest.py` runs four of their modules twice: recompiled, and in the interpreter. The one case only recompiled code can have, a jump to code that was not found, is marked `recompiled_only`.

Create `tests/lift/conftest.py`:
```python
"""The lifter's tests run twice: recompiled, and in the runtime's interpreter."""

import liftkit
import pytest

TWICE = {"test_armv4_quirks", "test_control_flow", "test_dataproc", "test_memory_system"}


def pytest_generate_tests(metafunc):
    if metafunc.module.__name__ in TWICE and "runner" in metafunc.fixturenames:
        metafunc.parametrize("runner", ["recompiled", "interpreted"], indirect=True)


@pytest.fixture(autouse=True)
def runner(request, monkeypatch):
    mode = getattr(request, "param", "recompiled")
    if mode == "interpreted" and request.node.get_closest_marker("recompiled_only"):
        pytest.skip("only recompiled code has missing code")
    monkeypatch.setattr(liftkit, "MODE", mode)
    return mode
```

In `tests/liftkit.py`:
```diff
@@ -7,6 +7,10 @@ both runs end there, and snippets may branch to ``stop`` themselves.
 batch (cached by the hash of its sources) and runs it; ``run_oracle`` executes the
 same cases in Unicorn's ARM926 model. Both report an ``Outcome``.
 
+``run_lifted`` runs the cases recompiled, or with ``MODE = "interpreted"`` (which
+tests/lift/conftest.py sets for a second run of every lifter test) in the runtime's
+interpreter (runtime/interp.c) instead, so both follow the same oracle.
+
 Memory is three 4 KiB windows: the ROM at 0x08000000 (the assembled snippet), EWRAM
 at 0x02000000 and IWRAM at 0x03000000. Unicorn is an ARMv5 core, so tests stay
 inside the behaviour ARMv4T shares with it: aligned memory accesses, and no
@@ -47,6 +51,8 @@ STATUSES = ("stopped", "returned", "undefined", "missing", "fault", "runaway")
 HOST = Path(__file__).with_name("lifthost.c")
 INCLUDE = Path(gbaport.lift.__file__).parent
 CACHE = Path(tempfile.gettempdir()) / "gbaport-liftcache"
+INTERPRETER = [native.RUNTIME / name for name in ("interp.c", "decode.c", "interp.h", "decode.h")]
+MODE = "recompiled"
 _UC_REGS = [getattr(uc_arm, f"UC_ARM_REG_R{n}") for n in range(13)] + [
     uc_arm.UC_ARM_REG_SP,
     uc_arm.UC_ARM_REG_LR,
@@ -136,14 +142,16 @@ def lift_cases(cases: list[Case]) -> str:
     return "\n".join(parts) + "\n"
 
 
-def build(source: str) -> Path:
+def build(source: str, interpret: bool = False) -> Path:
     """Compile the harness with ``source``; reuses an earlier build of the same sources.
 
     A build Windows refuses to start (Smart App Control) is compiled again with a different
     ``salt.c``, as ``gbaport build`` does.
     """
     digest = hashlib.sha1()
-    for text in (source, HOST.read_text(), (INCLUDE / "gba_cpu.h").read_text()):
+    extra = INTERPRETER if interpret else []
+    for text in (source, HOST.read_text(), (INCLUDE / "gba_cpu.h").read_text(),
+                 *(p.read_text() for p in extra)):
         digest.update(text.encode())
     folder = CACHE / digest.hexdigest()[:16]
     exe = folder / "lifthost.exe"
@@ -156,6 +164,9 @@ def build(source: str) -> Path:
         clang(), "-std=c11", "-O1", "-Wall", "-Werror", "-Wno-unused-label", f"-I{INCLUDE}",
         f"-I{HOST.parent}", str(HOST), str(folder / "cases.c"), str(salt), "-o", str(exe),
     ]
+    if interpret:
+        command[1:1] = ["-DLIFTHOST_INTERPRET", f"-DLIFTHOST_ENTRY={CODE_ADDR:#x}u", f"-I{native.RUNTIME}"]
+        command += [str(p) for p in extra if p.suffix == ".c"]
     for _ in range(native.SALTED_REBUILDS + 1):
         salt.write_text(f'const char lifthost_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
         result = subprocess.run(command, capture_output=True, text=True, check=False)
@@ -167,9 +178,9 @@ def build(source: str) -> Path:
     raise RuntimeError(f"Windows refused to start {exe} after {native.SALTED_REBUILDS} rebuilds")
 
 
-def run_compiled(source: str, cases: list[Case]) -> list[Outcome]:
+def run_compiled(source: str, cases: list[Case], interpret: bool = False) -> list[Outcome]:
     """Run ``cases`` with the harness built around ``source`` (it defines HARNESS_CASES)."""
-    exe = build(source)
+    exe = build(source, interpret)
     with tempfile.TemporaryDirectory() as tmp:
         inp, out = Path(tmp) / "in.bin", Path(tmp) / "out.bin"
         with open(inp, "wb") as f:
@@ -193,9 +204,16 @@ def run_compiled(source: str, cases: list[Case]) -> list[Outcome]:
 
 
 def run_lifted(cases: list[Case]) -> list[Outcome]:
+    if MODE == "interpreted":
+        return run_interpreted(cases)
     return run_compiled(lift_cases(cases), cases)
 
 
+def run_interpreted(cases: list[Case]) -> list[Outcome]:
+    """The cases run by the runtime's interpreter, with nothing recompiled."""
+    return run_compiled('#include "lifthost.h"\n', cases, interpret=True)
+
+
 def run_oracle(cases: list[Case]) -> list[Outcome]:
     return [_oracle(case) for case in cases]
 
```

In `tests/lifthost.c`:
```diff
@@ -5,7 +5,10 @@
  * INPUT holds a u32 case count, then per case: u32 case index, u32 r0-r14, u32 CPSR,
  * and the ROM, EWRAM and IWRAM windows (WINDOW bytes each). OUTPUT holds per case:
  * u32 status, u32 r0-r14, u32 CPSR and the EWRAM and IWRAM windows. A program stops
- * at "svc #0xff"; every other way out is a status the tests report. */
+ * at "svc #0xff"; every other way out is a status the tests report.
+ *
+ * Built with LIFTHOST_INTERPRET, it runs every case in runtime/interp.c instead, from
+ * LIFTHOST_ENTRY, and has no case table. */
 #define _CRT_SECURE_NO_WARNINGS /* fopen is fine here (MSVC's C library) */
 #include <setjmp.h>
 #include <stdio.h>
@@ -13,6 +16,9 @@
 #include <string.h>
 
 #include "lifthost.h"
+#ifdef LIFTHOST_INTERPRET
+#include "interp.h"
+#endif
 
 #define WINDOW 0x1000u
 #define CYCLE_LIMIT 1000000u
@@ -80,7 +86,20 @@ void gba_swi(GbaCtx *ctx, uint32_t number)
 
 void gba_undefined(GbaCtx *ctx, uint32_t addr) { (void)ctx; (void)addr; longjmp(escape, UNDEFINED); }
 
+#ifdef LIFTHOST_INTERPRET
+uint32_t gba_fetch16(GbaCtx *ctx, uint32_t addr) { return gba_read16(ctx, addr); }
+uint32_t gba_fetch32(GbaCtx *ctx, uint32_t addr) { return gba_read32(ctx, addr); }
+
+GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
+{
+    ctx->interp_pc = addr;
+    return gba_interpret;
+}
+
+static GbaFn interpret_everything(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }
+#else
 GbaFn gba_missing(GbaCtx *ctx, uint32_t addr) { (void)ctx; (void)addr; longjmp(escape, MISSING); }
+#endif
 
 /* Calls nested this deep come from code that calls without returning: a runaway. */
 void gba_call_overflow(GbaCtx *ctx, uint32_t ret) { (void)ctx; (void)ret; longjmp(escape, RUNAWAY); }
@@ -131,10 +150,14 @@ int main(int argc, char **argv)
     for (uint32_t n = 0; n < count; n++) {
         static GbaCtx ctx;
         uint32_t index = read_u32(in);
+#ifdef LIFTHOST_INTERPRET
+        (void)index;  /* every case runs from LIFTHOST_ENTRY */
+#else
         if (index >= HARNESS_CASE_COUNT) {
             fprintf(stderr, "lifthost: no case %u\n", index);
             return 2;
         }
+#endif
         memset(&ctx, 0, sizeof ctx);
         for (int r = 0; r < 15; r++)
             ctx.r[r] = read_u32(in);
@@ -145,14 +168,22 @@ int main(int argc, char **argv)
         ctx.v = (cpsr >> 28) & 1;
         ctx.cpsr_ctrl = cpsr & 0x0FFFFFFFu;
         ctx.next_event = CYCLE_LIMIT;
+#ifdef LIFTHOST_INTERPRET
+        ctx.lookup = interpret_everything;
+#else
         ctx.lookup = HARNESS_CASES[index].lookup;
+#endif
         read_window(in, rom);
         read_window(in, ewram);
         read_window(in, iwram);
         uint32_t initial_lr = ctx.r[14];
         int status = setjmp(escape);
         if (status == 0) {
+#ifdef LIFTHOST_INTERPRET
+            gba_call(&ctx, LIFTHOST_ENTRY | (cpsr & 0x20u ? 1u : 0u), initial_lr);
+#else
             gba_call_direct(&ctx, HARNESS_CASES[index].entry, initial_lr);
+#endif
             status = RETURNED;
         }
         write_u32(out, (uint32_t)(status - STOPPED));
```

In `tests/lift/test_control_flow.py`:
```diff
@@ -258,7 +258,8 @@ def test_an_endless_loop_hands_control_to_the_scheduler():
 
 @pytest.mark.parametrize("source,status", [
     (".word 0xe7f000f0", "undefined"),  # an undefined instruction
-    ("ldr r0, ptr\n    bx r0\nptr: .word 0x08000400", "missing"),  # no code was found there
+    pytest.param("ldr r0, ptr\n    bx r0\nptr: .word 0x08000400", "missing",  # no code was found
+                 marks=pytest.mark.recompiled_only),
 ])
 def test_unrecoverable_paths_reach_the_runtime(source, status):
     assert run_lifted([random_case(random.Random(23), source)])[0].status == status
```

In `pyproject.toml`:
```diff
@@ -29,6 +29,7 @@ pythonpath = ["tests"]
 # Unicorn raises and handles access violations internally on Windows, and
 # faulthandler would print each one as a fatal error.
 addopts = "-q -p no:faulthandler"
+markers = ["recompiled_only: a lifter test only recompiled code can pass (it has missing code)"]
 
 [tool.ruff]
 line-length = 100
```

In `src/gbaport/lift/gba_cpu.h` (the lifthost build needs the new fields):
```diff
@@ -48,7 +48,10 @@ typedef struct GbaCtx {
     uint8_t n16[16], s16[16], n32[16], s32[16];
     uint32_t prefetch;          /* WAITCNT bit 14 */
     uint32_t prefetched;        /* how far the buffer has fetched (mGBA's lastPrefetchedPc) */
-    GbaFn (*lookup)(struct GbaCtx *ctx, uint32_t addr); /* recompiled function at addr */
+    GbaFn (*lookup)(struct GbaCtx *ctx, uint32_t addr); /* what runs the code at addr */
+    GbaFn (*find)(struct GbaCtx *ctx, uint32_t addr);   /* recompiled function at addr, or NULL */
+    uint32_t interp_pc;         /* where gba_interpret starts (bit 0: Thumb state) */
+    uint64_t interpreted;       /* instructions the interpreter has run */
     void *runtime;              /* owned by the runtime */
 } GbaCtx;
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/lift -k interpreted`
Expected: FAIL: 27 failed, 1 skipped, 40 deselected, `FileNotFoundError` (no `interp.c`).

- [ ] **Step 3: Create `interp.h` (above) and `interp.c`: `uint32_t gba_interpret(GbaCtx *ctx)`**

It decodes at `ctx->interp_pc` (`gba_fetch16`/`gba_fetch32`; a Thumb BL prefix fetches the next halfword), counts each instruction in `ctx->interpreted`, and runs it by the lifter's rules. Each rule's comment names the Python function it follows.

- **Cycles** (`function.py` `_block`, `_static`, `_extra`, `_cost_expr`; `semantics.py` `cycles`):
  - The static cost is pending. A leaving instruction (B, BL, BL_LO, or one that writes r15) adds its own cost first.
  - Pending is added to `ctx->cycles` before a leaving instruction or one that accesses memory (loads, stores, LDM/STM, SWP, SWI). Then the instruction's own cost becomes pending.
  - A conditional ARM instruction charges (1, 1, 0) up front, and the rest (k-1, s-1, n) only when its condition holds, before its effects.
- **Effects** (`semantics.py`): data processing (Thumb ADR, register-shift pc + 12, the logical shifter carry, exception returns), multiplies (`gba_mul_wait` first), single and block transfers, swaps, MRS/MSR, SWI (ARM: `imm >> 16`), BX and BL_HI. A write to r15 goes to `t`.
- **Control** (`function.py` `_instruction`):
  - UNDEFINED calls `gba_undefined`.
  - B pays `gba_jumped(2 + N + S of the target)`. A B to the next instruction goes on. Otherwise it checks events when its target is at or before the branch, then leaves when the target is the current call's return address, recompiled code (`ctx->find`) or an outer call's return address, and otherwise goes on interpreting there.
  - BL (when its target is not the next instruction) and BL_LO run `gba_call(target in its state, return address)`, then `GBA_UNWOUND()`, then go on after the call.
  - An instruction that writes r15 masks `t` as `_mask` does and pays `gba_refill`.
    - After a `mov lr, pc` at the address before it (`flow.py` `links_to_next`, decoded again), it is a call: `gba_call(ctx, t, lr)`, then `GBA_UNWOUND()`, and execution goes on after it.
    - Otherwise it checks events and returns `t`.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/lift`
Expected: 67 passed, 1 skipped.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 997 passed, 1 skipped.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime/interp.h src/gbaport/runtime/interp.c src/gbaport/lift/gba_cpu.h tests/lift/conftest.py tests/lifthost.c tests/liftkit.py tests/lift/test_control_flow.py pyproject.toml
git commit -m "feat: an interpreter runs ARM and Thumb code by the rules recompiled code follows"
```

---

### Task 3: One rule for event checks

**Files:**
- Modify: `src/gbaport/lift/function.py`, `src/gbaport/lift/gba_cpu.h`, `tests/lifthost.c`, `tests/liftkit.py`
- Test: `tests/lift/test_events.py`

**Interfaces:**
- Produces:
  - `GBA_LEAVE(target)`: leave without a check;
  - `Outcome.checks`: how often a lifthost run checked for due events. lifthost keeps `next_event` at 0, so every check calls `gba_events`.

- [ ] **Step 1: Write the failing test**

In `tests/lifthost.c`:
```diff
@@ -4,7 +4,8 @@
  *
  * INPUT holds a u32 case count, then per case: u32 case index, u32 r0-r14, u32 CPSR,
  * and the ROM, EWRAM and IWRAM windows (WINDOW bytes each). OUTPUT holds per case:
- * u32 status, u32 r0-r14, u32 CPSR and the EWRAM and IWRAM windows. A program stops
+ * u32 status, u32 r0-r14, u32 CPSR, u32 checks (how often the code checked for due events)
+ * and the EWRAM and IWRAM windows. A program stops
  * at "svc #0xff"; every other way out is a status the tests report.
  *
  * Built with LIFTHOST_INTERPRET, it runs every case in runtime/interp.c instead, from
@@ -27,6 +28,7 @@ enum { STOPPED = 1, RETURNED, UNDEFINED, MISSING, FAULT, RUNAWAY }; /* setjmp re
 
 static uint8_t rom[WINDOW], ewram[WINDOW], iwram[WINDOW];
 static jmp_buf escape;
+static uint32_t checks;  /* every check calls gba_events: next_event stays 0 */
 
 static uint8_t *window(uint32_t addr, uint32_t size, int writing)
 {
@@ -106,9 +108,9 @@ void gba_call_overflow(GbaCtx *ctx, uint32_t ret) { (void)ctx; (void)ret; longjm
 
 void gba_events(GbaCtx *ctx)
 {
+    checks++;
     if (ctx->cycles >= CYCLE_LIMIT)
         longjmp(escape, RUNAWAY);
-    ctx->next_event = CYCLE_LIMIT;
 }
 
 static uint32_t read_u32(FILE *f)
@@ -167,7 +169,7 @@ int main(int argc, char **argv)
         ctx.c = (cpsr >> 29) & 1;
         ctx.v = (cpsr >> 28) & 1;
         ctx.cpsr_ctrl = cpsr & 0x0FFFFFFFu;
-        ctx.next_event = CYCLE_LIMIT;
+        checks = 0;
 #ifdef LIFTHOST_INTERPRET
         ctx.lookup = interpret_everything;
 #else
@@ -190,6 +192,7 @@ int main(int argc, char **argv)
         for (int r = 0; r < 15; r++)
             write_u32(out, ctx.r[r]);
         write_u32(out, gba_cpsr(&ctx));
+        write_u32(out, checks);
         fwrite(ewram, 1, WINDOW, out);
         fwrite(iwram, 1, WINDOW, out);
     }
```

In `tests/liftkit.py`:
```diff
@@ -99,6 +99,7 @@ class Outcome:
     cpsr: int
     ewram: bytes
     iwram: bytes
+    checks: int = 0  # how often the code checked for due events (not the oracle's)
 
 
 def random_case(rng: random.Random, source: str, *, thumb: bool = False, **fields) -> Case:
@@ -191,14 +192,14 @@ def run_compiled(source: str, cases: list[Case], interpret: bool = False) -> lis
                 f.write(case.rom().ljust(WINDOW, b"\0")[:WINDOW] + case.ewram + case.iwram)
         subprocess.run([str(exe), str(inp), str(out)], check=True, timeout=30)
         data = out.read_bytes()
-    size = 17 * 4 + 2 * WINDOW
+    size = 18 * 4 + 2 * WINDOW
     outcomes = []
     for i in range(len(cases)):
         chunk = data[i * size : (i + 1) * size]
-        words = struct.unpack_from("<17I", chunk)
-        ram = chunk[68:]
+        words = struct.unpack_from("<18I", chunk)
+        ram = chunk[72:]
         outcomes.append(
-            Outcome(STATUSES[words[0]], words[1:16], words[16], ram[:WINDOW], ram[WINDOW:])
+            Outcome(STATUSES[words[0]], words[1:16], words[16], ram[:WINDOW], ram[WINDOW:], words[17])
         )
     return outcomes
 
```

Create `tests/lift/test_events.py`:
```python
"""Recompiled code and the interpreter check for due events at the same instructions.

Both follow one rule, so a piece of a game's code checks (and takes interrupts) at the
same moments wherever it runs: at every taken branch back to an address at or before
the branch, and at every jump through a register that is not a call. Every loop has one
of those, so a loop still lets the scheduler run.
"""

import random

import pytest
from liftkit import IWRAM, lift_cases, random_case, run_compiled, run_interpreted

LOOP_AT_ENTRY = """
    mov r0, #3
    bl count
    b stop
count:
    subs r0, r0, #1
    bne count
    bx lr
"""

FALL_INTO_LOOP = """
    mov r0, #3
loop:
    subs r0, r0, #1
    bne loop
"""

TAIL_BRANCH_AND_TABLE = """
    bl g
    bl f
    and r2, r0, #1
    cmp r2, #1
    ldrls pc, [pc, r2, lsl #2]
    b stop
    .word one, stop
one:
    add r0, r0, #4
    b stop
f:
    mov r1, #1
    b g
g:
    add r0, r0, #1
    bx lr
"""

THUMB_LOOP_AT_ENTRY = """
    movs r0, #3
    bl count
    b stop
count:
    subs r0, #1
    bne count
    bx lr
"""

THUMB_TAIL_BRANCH = """
    bl g
    bl f
    b stop
f:
    movs r1, #1
    b g
g:
    adds r0, #1
    bx lr
"""

PROGRAMS = [  # a called function whose entry is a loop, a loop reached by falling into it,
    # a forward tail branch into another function and a jump through a table, then in Thumb
    (LOOP_AT_ENTRY, False), (FALL_INTO_LOOP, False), (TAIL_BRANCH_AND_TABLE, False),
    (THUMB_LOOP_AT_ENTRY, True), (THUMB_TAIL_BRANCH, True),
]


@pytest.mark.parametrize("source, thumb", PROGRAMS)
def test_recompiled_and_interpreted_code_check_for_events_at_the_same_places(source, thumb):
    rng = random.Random(41)
    cases = []
    for _ in range(4):
        case = random_case(rng, source, thumb=thumb)
        case.regs[13] = IWRAM + 0xC00  # a stack for the calls
        cases.append(case)
    recompiled = run_compiled(lift_cases(cases), cases)
    interpreted = run_interpreted(cases)
    assert [o.status for o in recompiled] == [o.status for o in interpreted] == ["stopped"] * 4
    assert [o.checks for o in recompiled] == [o.checks for o in interpreted]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/lift/test_events.py`
Expected: FAIL: 5 failed. For example `assert [4, 4, 4, 4] == [3, 3, 3, 3]`: the recompiled code also checks at a loop head when it enters it and at a forward tail branch.

- [ ] **Step 3: Check where the interpreter does, in `function.py` and `gba_cpu.h`**

- `_loop_heads` and the check at a loop-head label go.
- `_branch(ins)`, for a taken B:
  - to a block of the function: `GBA_CHECK_EVENTS(); goto` when the target is at or before the branch, a plain `goto` otherwise;
  - out of the function: `GBA_EXIT` when backward, `GBA_LEAVE` when forward.
- `_fall(target, mode)`: running on into the next block is `goto`, or `GBA_LEAVE` out of the function.
- A register jump with known cases: `GBA_CHECK_EVENTS();`, the `switch`, then `GBA_LEAVE(t)`. Without cases it stays `GBA_EXIT(t)`.
- `gba_cpu.h`: `#define GBA_LEAVE(target) return (target)`, with the comment "Leaving without a check: a forward branch out of the function, or running on into the code after it."

The module's comment says the rule and why: every loop has a backward branch or a register jump, and the rule does not depend on where functions begin and end.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite, then BT4E against mGBA**

Run: `.venv/Scripts/python.exe -m pytest tests/lift`
Expected: 72 passed, 1 skipped.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 1002 passed, 1 skipped. (The mGBA-exact timing, sound and interrupt tests are among them.)

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

Run: `.venv/Scripts/python.exe -m gbaport.cli verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input`
Expected: `verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart`.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/lift/function.py src/gbaport/lift/gba_cpu.h tests/lifthost.c tests/liftkit.py tests/lift/test_events.py
git commit -m "feat: recompiled code checks for events where the interpreter does: backward branches and register jumps"
```

---

### Task 4: Code the build missed runs interpreted; the places; learning from them

**Files:**
- Modify:
  - runtime: `src/gbaport/runtime/runtime.c`, `memory.c`, `gba_runtime.h`, `host_common.c`, `host_common.h`, `host_sdl.c`;
  - `src/gbaport/lift/program.py`, `src/gbaport/native/build.py`, `src/gbaport/learn.py`, `src/gbaport/cli.py`.
- Test: `tests/runtime/test_core.py`, `tests/test_learn.py`, `tests/lift/test_program.py`, `tests/test_trace_mgba.py`, `tests/test_android_device.py`

**Interfaces:**
- Consumes: `gba_interpret`, `ctx->find`, `ctx->interp_pc` (Task 2).
- Produces:
  - **`gba_runtime.h`:**
    - `GbaPlace {uint32_t addr /* bit 0: Thumb */; uint32_t frame;}`, `GBA_MAX_PLACES 16384`;
    - `rt->places`, `rt->place_count`;
    - `int gba_note_place(GbaRuntime *rt, uint32_t addr, uint32_t frame)` (1 when added);
    - `GbaFn gba_find(GbaCtx *ctx, uint32_t addr)` (generated).
  - **The places file:** the line `gbaport-places/1 <ROM CRC32, 8 hex digits>`, then a line a place, `arm|thumb <address, 8 hex digits> <frame>`.
  - **The hosts:** `--places PATH`. The window's default is next to its save (`<save without .sav>.places`). At the end of a run with interpreted code, stderr has the line `interpreted N instructions at M places[, listed in PATH]`.
  - **`learn.py`:**
    - `Place(addr, mode, frame)`;
    - `Learning(learned: list[Place], interpreted: list[tuple[Place, str]])`;
    - `read_places(path, crc32) -> list[Place]`;
    - `learn(...) -> Learning`.

- [ ] **Step 1: Write the failing tests**

In `tests/runtime/test_core.py`:
```diff
@@ -1,3 +1,5 @@
+import re
+
 from romtest import build_test_rom, run_rom, run_test
 
 
@@ -24,12 +26,17 @@ def test_the_bios_sound_driver_is_ignored_with_a_warning():
     assert "ignoring the BIOS sound driver (SWI 0x1c)" in run.stderr
 
 
-def test_a_jump_to_code_that_was_not_recompiled_names_the_address():
+def test_code_that_was_not_recompiled_runs_in_the_interpreter():
+    run = run_test("calls", frames=30, args=("--press", "5:A"))  # game.toml lacks its hooks
+    run.assert_passed()
+    assert re.search(r"^interpreted \d+ instructions at 3 places$", run.stderr, re.MULTILINE)
+
+
+def test_a_jump_to_where_there_can_be_no_code_names_the_address():
     run = run_test("err_missing")
     assert run.status == 3
-    assert "no recompiled code at 0x08100000 (Thumb state" in run.stderr
-    assert ", frame 0): gbaport learn finds it" in run.stderr  # from a recording of the play
-    assert "thumb_entries" in run.stderr
+    assert "no recompiled code at 0x08100000 (Thumb state, lr = 0x" in run.stderr
+    assert ", frame 0), and none can be there: it is past the end of the ROM" in run.stderr
 
 
 def test_the_frame_limit_ends_a_game_that_never_stops():
```

In `tests/test_learn.py`:
```diff
@@ -1,7 +1,8 @@
-"""gbaport learn: a recorded run that stopped at code the recompiler did not find is played
-again natively, and each address it stops at is learned (games/<game_code>/learned.toml),
-until the replay gets through."""
+"""gbaport learn: a recorded run whose code ran partly in the interpreter is played again
+natively, and every place the replay runs interpreted is learned (games/<game_code>/
+learned.toml), until nothing does."""
 
+import dataclasses
 import os
 import re
 
@@ -14,10 +15,13 @@ from gbaport.rom.image import RomImage
 from gbaport.rom.info import inspect_rom
 
 
-def game(tmp_path, monkeypatch, name: str = "calls"):
-    """A test ROM as game.gba with its game.toml in games/ATST; tmp_path is the working folder."""
+def game(tmp_path, monkeypatch, name: str = "calls", ram_code: bool = True):
+    """A test ROM as game.gba with its game.toml in games/ATST; tmp_path is the working folder.
+    Without ``ram_code`` the game.toml does not say where the code it copies to IWRAM is from."""
     monkeypatch.chdir(tmp_path)
     rom = build_test_rom(name)
+    if not ram_code:
+        rom = dataclasses.replace(rom, config=rom.config.split("[[ram_code]]")[0])
     (tmp_path / "game.gba").write_bytes(rom.data)
     (tmp_path / "games" / "ATST").mkdir(parents=True)
     (tmp_path / "games" / "ATST" / "game.toml").write_text(rom.config, encoding="utf-8")
@@ -25,6 +29,7 @@ def game(tmp_path, monkeypatch, name: str = "calls"):
 
 
 RECORDING = "game.session.input"  # where the window records game.gba's play
+INTERPRETED = re.compile(r"^interpreted \d+ instructions at (\d+) places", re.MULTILINE)
 
 
 def built(tmp_path) -> str:
@@ -34,34 +39,31 @@ def built(tmp_path) -> str:
 
 
 def learned_lines(out: str) -> list[tuple[int, str, int]]:
-    found = re.findall(r"learned (0x[0-9a-f]{8}) \((Thumb|ARM)\), missing at frame (\d+)", out)
+    found = re.findall(r"learned (0x[0-9a-f]{8}) \((Thumb|ARM)\), which first ran interpreted at "
+                       r"frame (\d+)", out)
     return [(int(addr, 16), mode, int(frame)) for addr, mode, frame in found]
 
 
-def test_play_learn_build_and_play_on(tmp_path, monkeypatch, capsys):
+def test_play_learn_build_and_play_recompiled(tmp_path, monkeypatch, capsys):
     rom = game(tmp_path, monkeypatch)
     thumb, arm, pressed = (rom.symbols[name] for name in ("hidden_thumb", "hidden_arm", "hidden_pressed"))
-    stopped = run_rom(rom, frames=30, args=("--press", "5:A", "--record", RECORDING)).stderr
-    assert re.search(rf"no recompiled code at 0x{thumb:08x} \(Thumb state, lr = 0x[0-9a-f]{{8}}, "
-                     r"frame 0\): gbaport learn", stopped)  # at once: the A press never came
+    played = run_rom(rom, frames=30, args=("--press", "5:A", "--record", RECORDING))
+    played.assert_passed()  # the code the build missed ran in the interpreter
+    assert INTERPRETED.search(played.stderr).group(1) == "3"
     assert main(["learn", "game.gba"]) == 0
     out = capsys.readouterr().out
-    assert learned_lines(out) == [(thumb, "Thumb", 0), (arm, "ARM", 0)]
-    assert f"2 addresses learned into {learned_path('ATST')}" in out
-    played = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30",
-                          "--record", RECORDING])
-    assert f"no recompiled code at 0x{pressed:08x}" in played.stderr  # further this time
-    capsys.readouterr()
-    assert main(["learn", "game.gba"]) == 0
-    (addr, mode, frame), = learned_lines(capsys.readouterr().out)
+    first, second, (addr, mode, frame) = learned_lines(out)  # all of it in one replay
+    assert [first, second] == [(thumb, "Thumb", 0), (arm, "ARM", 0)]
     assert (addr, mode) == (pressed, "Thumb") and frame >= 5
+    assert f"3 places learned into {learned_path('ATST')}" in out
     sha1 = inspect_rom(RomImage(rom.data)).sha1
     assert load_learned(learned_path("ATST"), sha1) == ((arm,), (thumb, pressed))
     run = run_program([built(tmp_path), "game.gba", "--press", "5:A", "--frames", "30"])
     assert run.stdout.splitlines()[-1] == "DONE 3 passed, 0 failed"
+    assert not INTERPRETED.search(run.stderr)  # all of it recompiled now
 
 
-def test_learn_says_when_the_replay_stops_at_nothing(tmp_path, monkeypatch, capsys):
+def test_learn_says_when_the_replay_runs_nothing_interpreted(tmp_path, monkeypatch, capsys):
     rom = game(tmp_path, monkeypatch, "hello")
     run_rom(rom, frames=30, args=("--record", RECORDING))
     assert main(["learn", "game.gba"]) == 0
@@ -89,15 +91,25 @@ def test_device_is_instead_of_input_and_save(tmp_path, monkeypatch, capsys):
     assert "--device takes the recording from the phone" in capsys.readouterr().err
 
 
-def test_learn_stops_when_learning_does_not_help(tmp_path, monkeypatch, capsys):
+def test_code_the_analysis_cannot_recompile_stays_interpreted(tmp_path, monkeypatch, capsys):
+    rom = game(tmp_path, monkeypatch, "interrupts", ram_code=False)  # IWRAM code it copies
+    run_rom(rom, frames=600, args=("--record", RECORDING)).assert_passed()
+    assert main(["learn", "game.gba"]) == 0
+    out = capsys.readouterr().out
+    assert re.search(r"0x03[0-9a-f]{6} \(ARM\) still runs interpreted: the game runs it from "
+                     r"RAM", out)
+    learned = learned_path("ATST")
+    assert "0x03" not in (learned.read_text(encoding="utf-8") if learned.exists() else "")
+
+
+def test_learn_stops_at_a_jump_to_where_there_can_be_no_code(tmp_path, monkeypatch, capsys):
     rom = game(tmp_path, monkeypatch, "err_missing")  # jumps past the end of the ROM
     run_rom(rom, frames=30, args=("--record", RECORDING))
     assert main(["learn", "game.gba"]) == 1
-    captured = capsys.readouterr()
-    assert "learned 0x08100000 (Thumb)" in captured.out
-    assert "has 0x08100000 already, but it is still missing" in captured.err
-    assert "it is past the end of the ROM" in captured.err  # nothing there to recompile
-    assert "0x08100000" not in learned_path("ATST").read_text(encoding="utf-8")  # not kept
+    err = capsys.readouterr().err
+    assert "the replay stopped: no recompiled code at 0x08100000" in err
+    assert "it is past the end of the ROM" in err
+    assert not learned_path("ATST").exists()
 
 
 def test_learn_says_when_the_replay_cannot_run(tmp_path, monkeypatch, capsys):
@@ -110,10 +122,10 @@ def test_learn_says_when_the_replay_cannot_run(tmp_path, monkeypatch, capsys):
 
 
 def test_learn_plays_to_where_the_recorded_play_ended(tmp_path, monkeypatch, capsys):
-    rom = game(tmp_path, monkeypatch, "late_call")  # stops 2000 frames in, no key pressed
+    rom = game(tmp_path, monkeypatch, "late_call")  # calls missed code 2000 frames in
     run_rom(rom, frames=2100, args=("--record", RECORDING))
     ended = (tmp_path / RECORDING).read_text(encoding="utf-8").splitlines()[-1]
-    assert re.fullmatch(r"# ended at frame \d+: no recompiled code at .*", ended)
+    assert re.fullmatch(r"# ended at frame \d+", ended)
     assert main(["learn", "game.gba"]) == 0
     assert [addr for addr, _, _ in learned_lines(capsys.readouterr().out)] == [
         rom.symbols["hidden_late"]]
@@ -124,7 +136,7 @@ def test_learn_says_when_the_replay_does_not_stop_where_the_play_did(tmp_path, m
     rom = game(tmp_path, monkeypatch, "hello")
     run_rom(rom, frames=30, args=("--record", RECORDING))
     with open(tmp_path / RECORDING, "a", encoding="utf-8") as recording:  # another build's play
-        recording.write("# ended at frame 20: no recompiled code at 0x08000400 (Thumb state)\n")
+        recording.write("# ended at frame 20: undefined instruction at 0x08000400\n")
     assert main(["learn", "game.gba"]) == 1
     assert "the replay did not stop where the recorded play did (frame 20" in \
         capsys.readouterr().err
```

In `tests/lift/test_program.py`:
```diff
@@ -85,4 +85,4 @@ def test_exits_carry_the_state_execution_continues_in():
     assert "t &= ~3u;" in arm
     dispatch = lifted(TWO_FUNCTIONS).dispatch
     assert "uint32_t key = addr & ~1u;" in dispatch
-    assert "return gba_missing(ctx, addr);" in dispatch  # the runtime sees the state bit
+    assert "return fn ? fn : gba_missing(ctx, addr);" in dispatch  # the runtime sees the state bit
```

In `tests/test_trace_mgba.py`:
```diff
@@ -37,13 +37,13 @@ def test_trace_records_the_calls_discovery_could_not_follow(tmp_path, capsys):
     assert out[-1] == f"wrote {tmp_path / 'calls.trace'} ({len(trace.hits)} hits)"
 
 
-def test_a_traced_game_runs_natively(tmp_path):
+def test_a_traced_game_runs_recompiled(tmp_path):
     rom, trace = traced("calls", tmp_path)
-    missing = f"error: no recompiled code at {rom.symbols['hidden_thumb']:#010x}"
-    assert missing in run_rom(rom, frames=30).stderr
+    assert "interpreted" in run_rom(rom, frames=30).stderr  # the calls went to code it missed
     run = run_rom(rom, frames=30, traces=(trace,))
     assert run.status == 0, run.stderr
     assert run.lines[-1] == "DONE 2 passed, 0 failed"
+    assert "interpreted" not in run.stderr
 
 
 def test_trace_plays_an_input_file(tmp_path):
```

In `tests/test_android_device.py`:
```diff
@@ -195,13 +195,14 @@ def test_learn_takes_the_play_the_phone_recorded(phone, tmp_path, monkeypatch, c
     monkeypatch.chdir(tmp_path)  # learned.toml goes into games/ATST here
     hidden = build_test_rom("calls").symbols["hidden_thumb"]
     build_and_install(phone, tmp_path, monkeypatch, "calls")
-    phone.wait_for(rf"^error: no recompiled code at 0x{hidden:08x} ")  # the app records its play
+    phone.wait_for(r"^DONE 2 passed, 0 failed$")  # its calls ran interpreted; the app records
     phone.stop(APP)
     capsys.readouterr()
     assert main(["learn", "game.gba", "--config", "game.toml", "--device"]) == 0
     out = capsys.readouterr().out
     assert f"took the play recorded on {phone.serial}" in out
-    assert "2 addresses learned into" in out
+    assert f"learned 0x{hidden:08x} (Thumb)" in out
+    assert "2 places learned into" in out
     build_and_install(phone, tmp_path, monkeypatch, "calls")
     phone.wait_for(r"^DONE 2 passed, 0 failed$")
     phone.stop(APP)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_core.py tests/test_learn.py tests/lift/test_program.py tests/test_trace_mgba.py`
Expected: FAIL: 9 failed, 24 passed. For example `AssertionError: exit status 3: error: no recompiled code at 0x080005b4 (Thumb state, lr = 0x080005e3, frame 0): gbaport learn finds it from a recording of play, ...`: code the build missed still stops the game.

- [ ] **Step 3: The runtime, the hosts, `learn`**

- **`build.py`:** `RUNTIME_SOURCES` gains `"decode.c", "interp.c"`.
- **`program.py` `_dispatch`:** it emits `gba_find` (the binary search; NULL when nothing is found) and `gba_lookup`, which is `fn ? fn : gba_missing(ctx, addr)`. The prototypes declare both. The module's comment says what each does.
- **`runtime.c`:**
  - `reset_cpu` sets `ctx->find = gba_find` and keeps `ctx->interpreted` across resets, as it keeps `cycles`.
  - `gba_missing`, after the unwinding it already does:
    - When the address cannot hold code, it fails with `no recompiled code at 0x%08x (%s state, lr = 0x%08x, frame %lu), and none can be there: %s`. The reason is "it is past the end of the ROM" for ROM regions 0x08-0x0D at or past `rom_size`, and "no memory there holds code" for anything but regions 0x02, 0x03, 0x06.
    - Otherwise it notes the place (the address aligned for its state, bit 0 for Thumb, and the frame), sets `interp_pc` and returns `gba_interpret`.
  - `gba_note_place`: open addressing over `place_slots[2 * GBA_MAX_PLACES]` (index + 1; hash `addr * 2654435761 >> 8`). Nothing is added once the list is full.
- **`memory.c`:** `gba_fetch16`/`gba_fetch32` are `gba_read16`/`gba_read32`. Code is in RAM, VRAM or the ROM, whose reads have no side effects.
- **`host_common.c`:**
  - `--places PATH`.
  - `beside_save(o, path, size, suffix)`, now also used for the window's recording: the window's places path is its save path with `.places` for `.sav`.
  - `load_places` (in `host_open`, after `gba_init`) reads a file for this ROM's CRC32 into `rt->places`. A file for another ROM is ignored.
  - `store_places` writes the whole list through a `.new` file and `replace_file` when it has grown. It warns once when it cannot write, and runs at the start of `host_store_save`, so it is called every second, at the end and on a phone going to the background.
  - `host_finish` prints the `interpreted ...` line before the error or `stopped after` line.
  - The usage line gains `[--places PATH]`.
- **`host_sdl.c`:** the comment names `game.places` next to the phone's save.
- **`learn.py`** (its module comment says what it now does):
  - `_replay` adds `--places` (a temporary file) and returns the places read with the ROM's `zlib.crc32`. Exit status 3 raises `LearnError("the replay stopped: <its error>")`; any status but 0 and 4 raises "the replay could not run".
  - `learn` makes at most `ROUNDS = 20` rounds: build, replay, then for each place listed:
    - one already learned is taken out of the entries, kept out of later rounds, and added to `Learning.interpreted` with `_why_interpreted`;
    - one not yet learned is added and logged as `learned 0x%08x (Thumb|ARM), which first ran interpreted at frame N`.
    - The round writes `learned.toml` when there were places, and returns when no new one came.
  - `_why_interpreted`: for regions 0x02/0x03/0x06, "the game runs it from RAM, from bytes the analysis does not know: add a [[ram_code]] entry to game.toml for the ROM bytes it copies there"; otherwise "the analysis cannot decode code there".
  - `MISS`, `MOST`, `Learned` and `_why_missing` go.
- **`cli.py`** `_run_learn`:
  - prints `0x%08x (Thumb|ARM) still runs interpreted: <why>` for each place left interpreted;
  - prints `N places learned into <path>; build the game again to run them recompiled`;
  - raises "the replay did not stop where the recorded play did" when the recording ended with an error and nothing was learned;
  - prints "the replay played to its end: nothing to learn" when nothing ran interpreted.
  - The help line becomes "play a recording of the game again and learn the code it ran interpreted".

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_core.py tests/test_learn.py tests/lift/test_program.py tests/test_trace_mgba.py`
Expected: 33 passed.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 1004 passed, 1 skipped (the emulator boots for the Android tests).

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/lift/program.py src/gbaport/native/build.py src/gbaport/learn.py src/gbaport/cli.py tests/runtime/test_core.py tests/test_learn.py tests/lift/test_program.py tests/test_trace_mgba.py tests/test_android_device.py
git commit -m "feat: code the build missed runs in the interpreter, the hosts list where, and learn recompiles it"
```

---

### Task 5: Wholly interpreted, the same game; each function in its own state

**Files:**
- Modify: `src/gbaport/runtime/runtime.c`, `gba_runtime.h`, `host_common.c`, `host_common.h`, `scheduler.c`, `src/gbaport/lift/program.py`, `src/gbaport/lift/function.py`
- Create: `tests/runtime/test_interpret.py`, `tests/gbaroms/wrong_state.c`
- Test: `tests/runtime/test_public_roms.py`, `tests/lift/test_program.py`

**Interfaces:**
- Produces:
  - the hosts' `--interpret-all`, and `rt->interpret_all` (set by `host_open`; read by `reset_cpu`);
  - dispatch rows `{addr, thumb, fn}`: `gba_find` returns NULL when bit 0 asks for the other state.

- [ ] **Step 1: Write the failing tests**

Create `tests/gbaroms/wrong_state.c`:
```c
/* A Thumb call to a `bx pc` veneer that game.toml lists as ARM code, as the sweep can guess
 * one (its alias is an ARM function symbol): the call must run the veneer in Thumb state,
 * where `bx pc` goes on in the ARM code after it. Run as ARM code, its first word
 * (0x00004778, andeq r4, r0, r8, ror r7) would change r4, since Z is set at the call. */
#include "testlib.h"

__asm__(
    "    .text\n"
    "    .align 2\n"
    "    .thumb\n"
    "veneer:\n"                  /* r0 + 1, through ARM code */
    "    bx pc\n"
    "    .hword 0\n"
    "    .arm\n"
    "    add r0, r0, #1\n"
    "    bx lr\n"
    "    .global veneer_as_arm\n"
    "    .type veneer_as_arm, %function\n"
    "    .set veneer_as_arm, veneer\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global caller\n"
    "    .thumb_func\n"
    "    .type caller, %function\n"
    "caller:\n"                  /* veneer(r0) + 7, with Z set at the call */
    "    push {r4, lr}\n"
    "    movs r4, #7\n"
    "    cmp r4, r4\n"
    "    bl veneer\n"
    "    adds r0, r0, r4\n"
    "    pop {r4}\n"
    "    pop {r1}\n"
    "    bx r1\n");

int caller(int x);

int main(void)
{
    expect("a Thumb call to code game.toml lists as ARM", caller(1), 9);
    test_end();
    return 0;
}
```

Create `tests/runtime/test_interpret.py`:
```python
"""A game runs in the interpreter as its recompiled code runs: the same lines, the same
picture every frame, the same cycle counts (the hosts' --interpret-all runs no recompiled
code at all). tests/runtime/test_public_roms.py runs jsmolka's ROMs interpreted too."""

import pytest
from romtest import build_test_rom, run_rom

ROMS = [  # test ROMs that need no keys and no test data: timing, interrupts, DMA, BIOS
    "cycles", "interrupts", "intrwait_ime", "timers", "timer_rewrite", "dma", "hblank_dma",
    "hblank_irq", "bios_calls", "tasks", "mem_map", "ramreset_waits", "eeprom_busy",
    "reset_in_irq",
]


def test_a_call_runs_the_code_in_the_state_it_calls_in():
    rom = build_test_rom("wrong_state")
    assert f"{rom.symbols['veneer_as_arm']:#x}" in rom.config  # listed as ARM code
    run = run_rom(rom, frames=30)
    run.assert_passed()  # the Thumb call ran it in Thumb state, in the interpreter
    assert "interpreted" in run.stderr


@pytest.mark.parametrize("name", ROMS)
def test_a_game_interpreted_runs_as_it_runs_recompiled(name, tmp_path):
    rom = build_test_rom(name)
    recompiled = run_rom(rom, frames=300, args=("--hashes", str(tmp_path / "recompiled")))
    interpreted = run_rom(rom, frames=300, args=("--hashes", str(tmp_path / "interpreted"),
                                                 "--interpret-all"))
    assert interpreted.lines == recompiled.lines
    assert interpreted.status == recompiled.status
    assert (tmp_path / "interpreted").read_text() == (tmp_path / "recompiled").read_text()
    assert "interpreted" in interpreted.stderr
```

In `tests/runtime/test_public_roms.py`:
```diff
@@ -19,12 +19,15 @@ REGISTERS = {"thumb": 7}  # the register with the result: r12, except in thumb.g
 ALL_PASSED = "ae000eb0c97cf8ac296246c6d9eee1d1d2e1d428"  # SHA-1 of that picture's screenshot
 
 
+@pytest.mark.parametrize("how", ["recompiled", "interpreted"])
 @pytest.mark.parametrize(
     "name", ["arm", "thumb", "memory", "bios", "sram", "flash64", "flash128", "none"]
 )
-def test_jsmolka_rom_passes(name, tmp_path):
+def test_jsmolka_rom_passes(name, how, tmp_path):
     shot = tmp_path / "screen.bmp"
     args = ("--registers", "--screenshot", str(shot))
+    if how == "interpreted":
+        args += ("--interpret-all",)
     run = romtest.run_rom(jsmolka_rom(name), frames=120, args=args)
     assert run.status == 4, run.stderr
     register = REGISTERS.get(name, 12)
```

In `tests/lift/test_program.py`:
```diff
@@ -33,10 +33,17 @@ def test_every_function_gets_a_prototype_and_a_sorted_dispatch_row():
     for entry in BOTH:
         assert f"uint32_t f_{entry:08x}(GbaCtx *ctx);" in program.prototypes
     rows = [line for line in program.dispatch.splitlines() if line.strip().startswith("{0x")]
-    assert rows == [f"    {{0x{e:08x}u, f_{e:08x}}}," for e in BOTH]
+    assert rows == [f"    {{0x{e:08x}u, 0, f_{e:08x}}}," for e in BOTH]  # ARM state
     assert "GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr)" in program.dispatch
 
 
+def test_a_function_is_found_only_in_the_state_it_was_recompiled_in():
+    thumb = lifted("movs r0, #1\n    bx lr", thumb=True).dispatch
+    assert "    {0x080000c0u, 1, f_080000c0}," in thumb.splitlines()
+    # the same address in the other state goes to gba_missing (the interpreter)
+    assert "return table[mid].thumb == (addr & 1u) ? table[mid].fn : 0;" in thumb
+
+
 def test_prefix_keeps_programs_apart():
     program = lifted(TWO_FUNCTIONS, prefix="c7_")
     assert program.lookup_name == "c7_gba_lookup"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_interpret.py tests/runtime/test_public_roms.py tests/lift/test_program.py`
Expected: FAIL: 25 failed, 14 passed. For example `AssertionError: FAIL a Thumb call to code game.toml lists as ARM: got 0x00000002, want 0x00000009`; the interpreted runs stop at the hosts' usage line, which has no `--interpret-all` yet.

- [ ] **Step 3: `--interpret-all`; states in the dispatcher and in direct calls**

- **`host_common.c`/`.h`:** `--interpret-all` sets `o->interpret_all`, and `host_open` copies it to `rt->interpret_all` after `gba_init`. The usage line gains `[--interpret-all]`.
- **`runtime.c`:** `interpret_everything(ctx, addr)` returns `gba_missing(ctx, addr)`. With `interpret_all`, `reset_cpu` sets `ctx->lookup` to it and `ctx->find` to NULL.
- **`program.py`:**
  - The table's rows are `{0x%08xu, <0|1 for Thumb>, f_...}` (struct `{ uint32_t addr, thumb; GbaFn fn; }`).
  - `gba_find`'s hit returns `table[mid].thumb == (addr & 1u) ? table[mid].fn : 0`, with the comment "in the other state it is code that was not recompiled".
  - `lift_program` passes each function's state.
- **`function.py` `_call`:** a direct call (`gba_call_direct`) only when the target was recompiled in the call's state. Otherwise it is `gba_call` with the target in that state, so the dispatcher hands it to the interpreter.
- **`scheduler.c` `deliver`:** it calls `gba_call(ctx, handler & ~3u, BIOS_IRQ_RETURN)`. The BIOS reaches the handler with `ldr pc`, in ARM state.

- [ ] **Step 4: Run the tests to verify they pass, then the whole suite, then BT4E wholly interpreted**

Run: `.venv/Scripts/python.exe -m pytest tests/runtime/test_interpret.py tests/runtime/test_public_roms.py tests/lift/test_program.py`
Expected: 39 passed.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 1028 passed, 1 skipped.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

Build BT4E headless (`.venv/Scripts/python.exe -m gbaport.cli build roms/mygame.gba --host headless --out build/BT4E-h`). Then play `games/BT4E/first-fight.input` for 3600 frames twice, each with a fresh `--save build/t.sav` and `--hashes`: once as is, and once with `--interpret-all`, timing that run.
Expected:
- the two hash files are identical (3600 lines);
- the interpreted run prints `interpreted 174238063 instructions at 762 places` (about that many) and takes about 5 s, more than 60 frames a second.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/lift/program.py src/gbaport/lift/function.py tests/runtime/test_interpret.py tests/gbaroms/wrong_state.c tests/runtime/test_public_roms.py tests/lift/test_program.py
git commit -m "feat: --interpret-all runs a game wholly interpreted, with the same pictures; calls and the dispatcher keep to each function's state"
```

---

### Task 6: `gbaport build` learns the window's places; the docs; BT4E with nothing found by hand

**Files:**
- Modify: `src/gbaport/learn.py`, `src/gbaport/cli.py`, `README.md`, `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`
- Test: `tests/test_learn.py`

**Interfaces:**
- Consumes: `read_places`, `Place` (Task 4).
- Produces: `learn_places(places_file, rom, learned) -> list[Place]`.

- [ ] **Step 1: Write the failing test**

In `tests/test_learn.py`:
```diff
@@ -63,6 +63,16 @@ def test_play_learn_build_and_play_recompiled(tmp_path, monkeypatch, capsys):
     assert not INTERPRETED.search(run.stderr)  # all of it recompiled now
 
 
+def test_build_learns_the_places_the_window_ran_interpreted(tmp_path, monkeypatch, capsys):
+    rom = game(tmp_path, monkeypatch)
+    run_rom(rom, frames=30, args=("--press", "5:A", "--places", "game.places"))  # as the window
+    program = built(tmp_path)
+    assert "3 places that ran interpreted, from game.places" in capsys.readouterr().out
+    run = run_program([program, "game.gba", "--press", "5:A", "--frames", "30"])
+    assert run.stdout.splitlines()[-1] == "DONE 3 passed, 0 failed"
+    assert not INTERPRETED.search(run.stderr)
+
+
 def test_learn_says_when_the_replay_runs_nothing_interpreted(tmp_path, monkeypatch, capsys):
     rom = game(tmp_path, monkeypatch, "hello")
     run_rom(rom, frames=30, args=("--record", RECORDING))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_learn.py -k build_learns`
Expected: FAIL: 1 failed, 11 deselected: `assert '3 places that ran interpreted, from game.places' in ...`: the build does not read the window's places yet.

- [ ] **Step 3: `learn_places` and the build's use of it; the docs**

- **`learn.py`:** `learn_places` adds the ROM places (regions 0x08-0x0D) that the file lists for this ROM's CRC32 and that `learned.toml` lacks. It writes the file when it added any. Its docstring says why places in RAM are left to `learn`.
- **`cli.py` `_run_build`:** before `_recompile`, when `Path(args.rom).with_suffix(".places")` exists (the window's list, next to its default save) and `learn_places` added any, it prints `learned      N places that ran interpreted, from <path>`.
- **`README.md`:**
```diff
@@ -99,7 +99,12 @@ without a window, for tests and scripts. Both programs take:
   compares them with mGBA's);
 - `--record PATH`: record the play: the keys the game is given, as an input file, and the
   save it started from as `PATH.sav`. The window records by default, next to its save
-  file (`roms/mygame.session.input` for `roms/mygame.sav`), each run over the last.
+  file (`roms/mygame.session.input` for `roms/mygame.sav`), each run over the last;
+- `--places PATH`: list there the places code ran interpreted (below), adding to those the
+  file lists already. The window lists them by default next to its save file
+  (`roms/mygame.places`);
+- `--interpret-all`: run the whole game in the interpreter, no recompiled code at all (it
+  must give the same pictures and results: a test of the interpreter).
 
 Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
 the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
@@ -119,35 +124,47 @@ some of them for good ("An Application Control policy has blocked this file"). `
 build` checks that the program starts and, when Windows refuses it, links it again with a
 few different bytes, up to 20 times.
 
-The most common runtime error is code the recompiler did not find:
+Code the recompiler did not find runs in the interpreter (`runtime/interp.c`), which
+follows the rules recompiled code follows: the same instructions, the same cycles, and
+interrupts taken at the same instructions (every taken branch back to an address at or
+before it, and every jump through a register that is not a call). The game plays on, more
+slowly there, and when the run ends the program says how much ran interpreted:
 
-    error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3, frame 4296):
-    gbaport learn finds it from a recording of play, or add it to game.toml [code]
-    thumb_entries
+    interpreted 120394 instructions at 41 places, listed in roms/mygame.places
 
-The window recorded the play that led there, so
+`gbaport build` learns the places in the ROM from the window's list (next to the ROM's save
+file): it adds them to the game's learned entries (`games/<game_code>/learned.toml`, read
+together with `game.toml`), so the build runs them recompiled. `learned.toml` holds
+addresses only and can be committed.
+
+The window also recorded the play, so
 
     uv run python -m gbaport.cli learn roms/mygame.gba
 
 plays it again natively from the save it started from, up to where the play ended (the
 recording's last line says where, and why; an app killed in the background leaves none,
-and then the replay plays 30 seconds past the last key change, or `--frames N`). The
-replay does exactly what the play did, so it stops at the same place; `learn` adds the
-address to the game's learned
-entries (`games/<game_code>/learned.toml`, read together with `game.toml`), builds again
-and replays again, until the replay gets through. Each round takes about 15 seconds for
-Dragon Ball GT Transformation: a rebuild compiles only the code files that changed (code
-goes into files by address, 8 KiB of game code each). Then build the game again and play
-on; `learned.toml` holds addresses only and can be committed. `--input` and `--save` name
-another recording and the save it started from; `--device` takes the recording from the
-phone (below).
+and then the replay plays 30 seconds past the last key change, or `--frames N`), with a
+list of places of its own. The replay does exactly what the play did; `learn` adds every
+place it ran interpreted to the learned entries, those in RAM too, builds again and
+replays again, until nothing runs interpreted. A place that still runs interpreted once
+learned is left out again and named: the analysis cannot recompile code there (code the
+game copied to RAM from bytes the analysis does not know, for example). Each round takes
+about 15 seconds for Dragon Ball GT Transformation: a rebuild compiles only the code files
+that changed (code goes into files by address, 8 KiB of game code each). `--input` and
+`--save` name another recording and the save it started from; `--device` takes the
+recording from the phone (below).
+
+A jump to where no code can be is still a runtime error:
+
+    error: no recompiled code at 0x08100000 (Thumb state, lr = 0x080005c3, frame 0), and
+    none can be there: it is past the end of the ROM
 
 Discovery cannot follow the tables of relative offsets many games call their functions
 through, so for those `game.toml`'s `[code] sweep = true` turns on the sweep: where code
 found so far ends (a return, a jump), the code after it, past literal pools and padding,
 is tried as a function too, and kept only when it decodes as code a compiler emits.
-Addresses can also go into `game.toml` by hand (`thumb_entries` or `entries`, as the
-message says), or come from a trace recorded with mGBA (below).
+Addresses can also go into `game.toml` by hand (`thumb_entries` or `entries`), or come
+from a trace recorded with mGBA (below).
 
 `games/BT4E/game.toml` is an example: Dragon Ball GT Transformation with the sweep, about
 2200 functions. `games/BT4E/walk-right.input` plays it into its first fight, then walks
@@ -221,8 +238,9 @@ handing it to the screen (which can wait there for the display):
 A runtime error, or one that stops the game from starting (a save file of the wrong
 size), shows its message on the screen; the app ends when it is closed.
 
-The app records its play as the window does, in its own storage. When it stops at code
-the recompiler did not find, with the phone still connected:
+The app records its play as the window does, in its own storage, and runs the code the
+recompiler did not find in the interpreter too. To have that code recompiled, with the
+phone still connected:
 
     uv run python -m gbaport.cli learn roms/mygame.gba --device
     uv run python -m gbaport.cli build roms/mygame.gba --host android --install
```
- **The base spec:**
```diff
@@ -28,9 +28,9 @@ Out of scope:
   never committed to the repository.
 - Matching (byte-identical) decompilation.
 - Zero-input support for every ROM. Each game is expected to need a small `game.toml`.
-- Any runtime interpreter or JIT. Code the recompiler did not find is a build-time error
-  that names the address, fixed by adding it to `game.toml`, by importing a trace, or by
-  `gbaport learn`, which replays recorded play natively to find it (Plan 7c).
+- A JIT. Code the recompiler did not find runs in an interpreter instead, and `gbaport
+  learn` or the next `gbaport build` recompiles it (Plan 12; this replaces the earlier "no
+  runtime interpreter", see `2026-10-28-any-rom-design.md`).
 
 ## Key decisions
 
@@ -44,10 +44,11 @@ Out of scope:
    keyed by `addr >> 24`. This sidesteps the 64-bit pointer problem and the fact that iOS
    arm64 reserves the whole low 4 GB (`__PAGEZERO`), so GBA addresses cannot be mapped 1:1.
    Readable decompiled functions use the same accessors until their data is symbolized.
-4. **No runtime fallback.** Unknown indirect-branch targets abort with the address. Coverage
-   comes from static analysis (with an optional sweep of the code that follows code),
-   recorded traces, per-game overrides, and addresses learned by replaying recorded play
-   natively (`gbaport learn`, Plan 7c).
+4. **Recompiled code first, the interpreter for the rest** (Plan 12). Code the build did not
+   find runs in `runtime/interp.c`, which follows the recompiled code's rules exactly; the
+   hosts list where, and `gbaport learn` and `gbaport build` recompile it next time.
+   Coverage comes from static analysis (with an optional sweep of the code that follows
+   code), recorded traces, per-game overrides, and those places.
 5. **Emulators are dev-time test oracles only.** Unicorn (CPU semantics) and mGBA
    (whole-game lockstep) are used by tests and tools, never linked into a shipped app.
 6. **Python tooling, C11 runtime, clang everywhere.** Analysis and code generation are
@@ -100,8 +101,8 @@ The stages are exposed through one CLI, `gbaport`, with subcommands such as `inf
   A call site sets LR and runs `gba_call(ctx, next, return_address)`: a loop that looks up
   each returned address in a sorted address→function table (`gba_lookup`) and runs it, until
   the chain comes back to the call's return address. A direct `BL` to a recompiled function
-  starts the loop with a direct C call. A lookup miss aborts with the address and the hint
-  to add it to `game.toml`.
+  starts the loop with a direct C call. A lookup miss goes to the runtime's `gba_missing`,
+  which runs the code in the interpreter (Plan 12).
 - **Returns.** A return is just a jump to the return address, so it ends the C call that
   made it; tail calls and jumps through registers return their target and never grow the C
   stack. Comparing against the call site's return address, rather than the LR a function was
@@ -116,8 +117,8 @@ The stages are exposed through one CLI, `gbaport`, with subcommands such as `inf
 - **Timing.** Counted as mGBA counts it (Plan 7a): each instruction adds its fetches at
   the wait states WAITCNT sets, data accesses add their memory's waits (through mGBA's
   model of the prefetch buffer) and DMA its transfer time, each before the next memory
-  access sees the time; loop back-edges and function returns check
-  `ctx->cycles >= ctx->next_event` and run the scheduler, which advances scanlines and
+  access sees the time; taken branches back to an address at or before them and jumps
+  through registers that are not calls check `ctx->cycles >= ctx->next_event` and run the scheduler, which advances scanlines and
   delivers HBlank/VBlank/timer/DMA interrupts by calling the recompiled IRQ handler (address
   read from 0x03007FFC). Wait points (`Halt`, `IntrWait`, `VBlankIntrWait`, and recognised
   busy-wait loops on `VCOUNT`/`DISPSTAT`/`IF`) fast-forward to the next event. VBlank start
@@ -180,6 +181,7 @@ entries it learned by replaying recorded play), is read together with `game.toml
 | Runtime (Plans 4–6) | Self-built test ROMs (clang `--target=armv4t-none-eabi` + `ld.lld`) and public GBA test suites (licence checked before vendoring) | Expected outputs and reference images |
 | Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
 | Android (Plan 8) | Test ROMs on the Android emulator (dev only) | The app runs them; drawn buttons press keys; saves survive the app being killed; the frame rate holds |
+| Interpreter (Plan 12) | The lifter's oracles, and recompiled code | The lifter's Unicorn and ARMv4 tests run interpreted too; test ROMs and jsmolka's ROMs give the same lines, pictures and cycles interpreted as recompiled |
 | Coverage (Plan 7c) | The native build itself | A recording of play replays with the same picture each frame, also one recorded on a phone; `gbaport learn` turns a run that stopped at missing code into one that gets through |
 | Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |
 
@@ -206,6 +208,10 @@ depends on what the earlier stages reveal.
 | P10 Decomp loop | Override mechanism, Ghidra headless export, Claude agent loop, function-level differential tester | Functions replaced with tests passing; game still verifies | P7 |
 | P11 Symbolized data (optional) | ROM tables → C structs, GBA pointers → native symbols in decompiled code | Decompiled modules no longer use raw GBA addresses | P10 |
 
+Plans 8b and 12 to 16 follow `2026-10-28-any-rom-design.md` (any ROM to Windows and
+Android: the interpreter, code in RAM by content, no per-game setup, the compatibility
+report, cartridge hardware and the apps).
+
 ## Toolchain
 
 Already on the development machine (Windows 11): uv 0.11.32 with CPython 3.15.0b4, Git 2.51,
```

- [ ] **Step 4: Run the test to verify it passes, then the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_learn.py`
Expected: 12 passed.

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 1029 passed, 1 skipped.

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: All checks passed!

- [ ] **Step 5: BT4E with no hand-written entries and no trace**

The design's acceptance items 2 and 3, in a scratch working folder that holds only a reduced `game.toml`. The repository's `games/BT4E` stays as it is.

```bash
mkdir -p build/acceptance/games/BT4E
printf '[rom]\nsha1 = "8dd4b6e95dca4554a919bff55128481a9a95b611"\n\n[code]\nsweep = true\n' > build/acceptance/games/BT4E/game.toml
cd build/acceptance
../../.venv/Scripts/python.exe -m gbaport.cli build ../../roms/mygame.gba --host headless --out h
h/build/BT4E-headless.exe ../../roms/mygame.gba --input ../../games/BT4E/walk-right.input --frames 60000 --save t.sav --places t.places
```

Expected:
- the build reports about 2231 functions;
- the run exits with status 4 after 60000 frames, in about 14 s, and stderr says `interpreted 12979792 instructions at 32 places, listed in t.places` (about that many).

```bash
../../.venv/Scripts/python.exe -m gbaport.cli learn ../../roms/mygame.gba --input ../../games/BT4E/walk-right.input --frames 60000
../../.venv/Scripts/python.exe -m gbaport.cli build ../../roms/mygame.gba --host headless --out h
```

Expected:
- `learn` says `34 places learned into games\BT4E\learned.toml` (about that many) in about 2 minutes;
- the build reports `learned` and about 2259 functions.
- Playing `walk-right.input` (60000 frames) and `first-fight.input` again, each from a fresh `t.sav`, both runs end with status 4 and no `interpreted` line.

Then go back to the repository's root (`cd ../..`) and remove `build/acceptance`. Record the numbers in the ledger.

- [ ] **Step 6: The user's game on the phone**

This step needs the user's phone over USB. If it is not there, ledger that and carry on.

Run: `.venv/Scripts/python.exe -m gbaport.cli build roms/mygame.gba --host android --install --input games/BT4E/first-fight.input --out build/BT4E-android`

After 80 seconds, run `adb logcat -d -s gbaport`. Expected:
- the frame-rate lines are at 59.5 to 60.0 frames a second;
- the log has no `interpreted` line. BT4E's committed `game.toml` lists its code, so nothing runs interpreted; record the lines.

- [ ] **Step 7: Commit**

```bash
git add src/gbaport/learn.py src/gbaport/cli.py tests/test_learn.py README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "feat: gbaport build recompiles the places the window ran interpreted; the interpreter in the README and the spec"
```

---

## Done criteria for Plan 12

- `.venv/Scripts/python.exe -m pytest` passes 1029 tests (1 skipped), and `ruff check src tests` is clean.
- **Code the build missed runs interpreted** instead of stopping the game. A jump to where there can be no code still stops with the address.
- **The interpreter agrees with recompiled code:**
  - the lifter's Unicorn and ARMv4 tests run both ways, and recompiled and interpreted code check for events at the same instructions;
  - 14 test ROMs and jsmolka's ROMs give the same lines, pictures and cycles wholly interpreted;
  - BT4E gives the same picture hash every frame for 3600 frames, wholly interpreted, at about 13 times the GBA's speed on the PC.
- **BT4E against mGBA is unchanged:** `verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart`.
- **BT4E with no hand-written entries and no trace plays `walk-right.input` to its end.** After `gbaport learn` and a rebuild, nothing in it runs interpreted.
