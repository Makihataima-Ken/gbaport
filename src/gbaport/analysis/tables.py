"""Jump-table recognition at an indirect jump.

Patterns (``history`` is the current walk before the dispatch):

- agbcc Thumb switch: ``cmp rI, #N; b<hi> default; lsls rT, rI, #2;
  ldr rB, =table; adds rA, rT, rB; ldr rX, [rA]; mov pc, rX`` (also the
  ``ldr rX, [rT, rB]`` form). Entries are addresses.
- ARM ``ldr<ls> pc, [pc, rI, lsl #2]``: entries are addresses starting at dispatch + 8.
- ARM ``add<ls> pc, pc, rI, lsl #2``: a run of ``b`` instructions at dispatch + 8.
- GCC Thumb byte table: ``adr rB, table; ldrb rX, [rB, rI]; lsls rX, rX, #1;
  add pc, rX`` (``ldrsb`` too). Entries are halfword offsets from the ``add pc``.
- The ARM compiler's Thumb halfword table: ``adr rB, table; adds rA, rB, rI;
  ldrh rX, [rA, rI]; lsls rX, rX, #1; add pc, rX``. Entries are halfwords, offsets in
  halfwords from the ``add pc``.

The entry count comes from the guarding ``cmp rI, #N`` and the unsigned
condition that guards the dispatch: a ``hi`` branch around it or an ``ls``
dispatch gives N + 1 entries, ``hs`` / ``lo`` give N. Without such a guard the
table is reported instead of guessed. An override from ``game.toml`` supplies
the table and count but keeps the pattern's entry kind (addresses or branches).
"""

from dataclasses import dataclass

from gbaport.analysis.config import JumpTableOverride
from gbaport.analysis.effects import PC, written_registers
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Cond, Instruction, Mode, Op, Shift, ShiftKind

MAX_TABLE_ENTRIES = 1024
_TIMES_4 = Shift(ShiftKind.LSL, 2)
_TIMES_2 = Shift(ShiftKind.LSL, 1)
ADDRESSES, BRANCHES, BYTES, SIGNED_BYTES = "addresses", "branches", "bytes", "signed bytes"
HALFWORDS = "halfwords"
# Entries beyond N for ``cmp rI, #N``, by the condition under which the dispatch runs...
_DISPATCH_IN_RANGE = {Cond.LS: 1, Cond.CC: 0}
# ...or by the condition of a branch that skips it.
_BRANCH_OUT_OF_RANGE = {Cond.HI: 1, Cond.CS: 0}


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
    data: bool  # True: entries are data (addresses or offsets); False: ARM B instructions
    entry_size: int = 4  # bytes per entry


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
    found = _match(dispatch, history)
    override = overrides.get(dispatch.addr)
    if override is not None:
        kind = ADDRESSES if found is None else found[2]
        return TableMatch(_table(dispatch, override.table, override.count, kind, space))
    if found is None:
        return None
    table, count, kind = found
    if count is None:
        return TableMatch(
            None,
            f"jump table at {table:#010x} has no bound; add "
            f"{{ at = {dispatch.addr:#010x}, table = {table:#010x}, count = N }} "
            "to [code] jump_tables",
        )
    return TableMatch(_table(dispatch, table, count, kind, space))


def _match(dispatch: Instruction, history: list[Step]) -> tuple[int, int | None, str] | None:
    """(table address, entry count or None, entry kind) for a known pattern."""
    last = len(history) - 1
    if (
        dispatch.op is Op.LDR
        and dispatch.rn == PC
        and dispatch.rm is not None
        and dispatch.shift == _TIMES_4
        and dispatch.pre
        and dispatch.up
    ):
        return dispatch.addr + 8, _bound(history, last, dispatch.rm, dispatch), ADDRESSES
    if (
        dispatch.op is Op.ADD
        and dispatch.rn == PC
        and dispatch.rm is not None
        and dispatch.shift == _TIMES_4
    ):
        return dispatch.addr + 8, _bound(history, last, dispatch.rm, dispatch), BRANCHES
    if (
        dispatch.mode is Mode.THUMB
        and dispatch.op is Op.ADD
        and dispatch.rd == PC
        and dispatch.rn == PC
        and dispatch.rm not in (None, PC)
        and dispatch.shift is None
    ):
        return _byte_table(dispatch, history)
    if dispatch.op is Op.MOV and dispatch.rm is not None and dispatch.shift is None:
        return _loaded_from_table(dispatch, history)
    return None


def _byte_table(dispatch: Instruction, history: list[Step]) -> tuple[int, int | None, str] | None:
    """Match ``ldrb rY, [base, index]; lsls rX, rY, #1; add pc, rX`` with base known, or
    ``adds rA, base, index; ldrh rY, [rA, index]; lsls rX, rY, #1; add pc, rX``."""
    i = _definition(history, len(history) - 1, dispatch.rm)
    if i is None:
        return None
    scale = history[i].ins
    if scale.op is not Op.MOV or scale.rm is None or scale.shift != _TIMES_2:
        return None
    j = _definition(history, i - 1, scale.rm)
    if j is None:
        return None
    load = history[j].ins
    if load.op is Op.LDRH and load.rm is not None and load.shift is None and load.rn != load.rm:
        k = _definition(history, j - 1, load.rn)  # adds rA, rB, rI with rB the table
        if k is None:
            return None
        add = history[k].ins
        if add.op is not Op.ADD or add.rm is None or add.shift is not None:
            return None
        if load.rm not in (add.rn, add.rm):
            return None
        base = add.rm if add.rn == load.rm else add.rn
        if base not in history[k].consts:
            return None
        return history[k].consts[base], _bound(history, k - 1, load.rm, dispatch), HALFWORDS
    if load.op not in (Op.LDRB, Op.LDRSB) or load.rm is None or load.shift is not None:
        return None
    consts = history[j].consts
    known = [r for r in (load.rn, load.rm) if r in consts]
    if len(known) != 1 or load.rn == load.rm:
        return None
    index = load.rm if known[0] == load.rn else load.rn
    kind = BYTES if load.op is Op.LDRB else SIGNED_BYTES
    return consts[known[0]], _bound(history, j - 1, index, dispatch), kind


def _loaded_from_table(
    dispatch: Instruction, history: list[Step]
) -> tuple[int, int | None, str] | None:
    """Match ``ldr rX, [base + index*4]; mov pc, rX`` where exactly one of base/index is known."""
    i = _definition(history, len(history) - 1, dispatch.rm)
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
    return consts[known[0]], _bound(history, k - 1, scale.rm, dispatch), ADDRESSES


def _definition(history: list[Step], start: int, reg: int) -> int | None:
    """Index of the latest instruction at or before ``start`` that writes ``reg``."""
    for i in range(start, -1, -1):
        if reg in written_registers(history[i].ins):
            return i
    return None


def _bound(history: list[Step], start: int, reg: int, dispatch: Instruction) -> int | None:
    """Entry count from a ``cmp reg, #N`` at or before ``start`` and the guard on its flags."""
    for i in range(start, -1, -1):
        ins = history[i].ins
        if ins.op is Op.CMP and ins.rn == reg and ins.imm is not None:
            extra = _guard(history[i + 1 :], dispatch)
            return None if extra is None else ins.imm + extra
        if reg in written_registers(ins):
            return None
    return None


def _guard(after_compare: list[Step], dispatch: Instruction) -> int | None:
    """Entries beyond N that the unsigned guard on the compare's flags allows, if there is one."""
    for step in after_compare:
        ins = step.ins
        if ins.op is Op.B and ins.cond is not Cond.AL:
            return _BRANCH_OUT_OF_RANGE.get(ins.cond)
        if ins.s or ins.op is Op.MSR:  # the flags no longer come from the compare
            return None
    return _DISPATCH_IN_RANGE.get(dispatch.cond)


def _table(dispatch: Instruction, table: int, count: int, kind: str, space: CodeSpace) -> JumpTable:
    if kind == BRANCHES:
        targets = tuple(table + 4 * i for i in range(min(count, MAX_TABLE_ENTRIES)))
        return JumpTable(dispatch.addr, table, dispatch.mode, targets, data=False)
    if kind in (BYTES, SIGNED_BYTES):
        base = dispatch.addr + 4  # what the add reads as pc
        offsets = []
        for i in range(min(count, MAX_TABLE_ENTRIES)):
            if not space.contains(table + i):
                break
            value = space.read8(table + i)
            offsets.append(value - 0x100 if kind == SIGNED_BYTES and value & 0x80 else value)
        targets = tuple((base + 2 * offset) & 0xFFFFFFFE for offset in offsets)
        return JumpTable(dispatch.addr, table, dispatch.mode, targets, data=True, entry_size=1)
    if kind == HALFWORDS:
        base = dispatch.addr + 4  # what the add reads as pc
        targets = []
        for i in range(min(count, MAX_TABLE_ENTRIES)):
            if not space.contains(table + 2 * i, 2):
                break
            targets.append((base + 2 * space.read16(table + 2 * i)) & 0xFFFFFFFE)
        return JumpTable(dispatch.addr, table, dispatch.mode, tuple(targets), data=True, entry_size=2)
    mask = ~1 if dispatch.mode is Mode.THUMB else ~3
    targets = []
    for i in range(min(count, MAX_TABLE_ENTRIES)):
        row = table + 4 * i
        if not space.contains(row, 4):
            break
        targets.append(space.read32(row) & mask)
    return JumpTable(dispatch.addr, table, dispatch.mode, tuple(targets), data=True)
