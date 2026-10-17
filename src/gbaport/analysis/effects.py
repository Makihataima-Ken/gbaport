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
