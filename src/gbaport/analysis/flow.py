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
    if not writes_pc(ins):
        return Flow(FlowKind.NEXT)
    if _is_return(ins, state):
        return Flow(FlowKind.RETURN, falls_through=conditional)
    target = _pc_target(ins, state, space)
    if _links_to_next(prev):
        return Flow(FlowKind.CALL, target, falls_through=True)
    if target is None:
        return Flow(FlowKind.INDIRECT, falls_through=conditional)
    return Flow(FlowKind.JUMP, target, falls_through=conditional)


def writes_pc(ins: Instruction) -> bool:
    """True when ``ins`` may write r15 (``bx`` included)."""
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
