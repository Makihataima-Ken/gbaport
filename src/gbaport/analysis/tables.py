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
