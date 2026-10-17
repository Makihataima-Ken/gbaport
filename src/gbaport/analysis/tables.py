"""Jump-table recognition at an indirect jump.

Patterns (``history`` is the current walk before the dispatch):

- agbcc Thumb switch: ``cmp rI, #N; b<hi> default; lsls rT, rI, #2;
  ldr rB, =table; adds rA, rT, rB; ldr rX, [rA]; mov pc, rX`` (also the
  ``ldr rX, [rT, rB]`` form). Entries are addresses.
- ARM ``ldr<ls> pc, [pc, rI, lsl #2]``: entries are addresses starting at dispatch + 8.
- ARM ``add<ls> pc, pc, rI, lsl #2``: a run of ``b`` instructions at dispatch + 8.

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
    found = _match(dispatch, history)
    override = overrides.get(dispatch.addr)
    if override is not None:
        holds_addresses = True if found is None else found[2]
        return TableMatch(_table(dispatch, override.table, override.count, holds_addresses, space))
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
    return TableMatch(_table(dispatch, table, count, holds_addresses, space))


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
        return dispatch.addr + 8, _bound(history, last, dispatch.rm, dispatch), True
    if (
        dispatch.op is Op.ADD
        and dispatch.rn == PC
        and dispatch.rm is not None
        and dispatch.shift == _TIMES_4
    ):
        return dispatch.addr + 8, _bound(history, last, dispatch.rm, dispatch), False
    if dispatch.op is Op.MOV and dispatch.rm is not None and dispatch.shift is None:
        return _loaded_from_table(dispatch, history)
    return None


def _loaded_from_table(
    dispatch: Instruction, history: list[Step]
) -> tuple[int, int | None, bool] | None:
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
    return consts[known[0]], _bound(history, k - 1, scale.rm, dispatch), True


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


def _table(
    dispatch: Instruction, table: int, count: int, holds_addresses: bool, space: CodeSpace
) -> JumpTable:
    if not holds_addresses:
        targets = tuple(table + 4 * i for i in range(min(count, MAX_TABLE_ENTRIES)))
        return JumpTable(dispatch.addr, table, dispatch.mode, targets, data=False)
    mask = ~1 if dispatch.mode is Mode.THUMB else ~3
    targets = []
    for i in range(min(count, MAX_TABLE_ENTRIES)):
        row = table + 4 * i
        if not space.contains(row, 4):
            break
        targets.append(space.read32(row) & mask)
    return JumpTable(dispatch.addr, table, dispatch.mode, tuple(targets), data=True)
