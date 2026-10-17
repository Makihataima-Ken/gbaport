"""Render decoded instructions as Keystone/LLVM-compatible UAL assembly.

The output must re-assemble to the same bytes (tests/isa/test_roundtrip.py).
Thumb flag-setting forms always carry ``s`` (``adds``, ``lsls``) because the
plain UAL forms would select 32-bit Thumb-2 encodings. Undefined words and
unpaired Thumb BL halves have no assembler syntax and print as data directives.
"""

from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    MOVE_OPS,
    Cond,
    Instruction,
    Mode,
    Op,
    Shift,
    ShiftKind,
)

REG_NAMES = tuple(f"r{n}" for n in range(13)) + ("sp", "lr", "pc")
_LONG_MULTIPLY_OPS = frozenset({Op.UMULL, Op.UMLAL, Op.SMULL, Op.SMLAL})
_TRANSFER_OPS = frozenset(
    {Op.LDR, Op.STR, Op.LDRB, Op.STRB, Op.LDRH, Op.STRH, Op.LDRSB, Op.LDRSH}
)
_BLOCK_MODES = {(False, True): "ia", (True, True): "ib", (False, False): "da", (True, False): "db"}
_PSR_FIELDS = ((3, "f"), (2, "s"), (1, "x"), (0, "c"))


def format_instruction(ins: Instruction) -> str:
    if ins.op is Op.UNDEFINED:
        return _data(ins)
    if ins.mode is Mode.THUMB:
        return _thumb(ins)
    return _arm(ins)


def _data(ins: Instruction) -> str:
    if ins.mode is Mode.ARM:
        return f".word {ins.raw:#010x}"
    return f".hword {ins.raw:#06x}"


def _reg(n: int) -> str:
    return REG_NAMES[n]


def _cond(ins: Instruction) -> str:
    return "" if ins.cond is Cond.AL else ins.cond.name.lower()


def _shift(shift: Shift | None) -> str:
    if shift is None:
        return ""
    if shift.kind is ShiftKind.RRX:
        return ", rrx"
    if shift.reg is not None:
        return f", {shift.kind.value} {_reg(shift.reg)}"
    return f", {shift.kind.value} #{shift.amount}"


def _reglist(regs: tuple[int, ...]) -> str:
    return "{" + ", ".join(_reg(r) for r in regs) + "}"


def _address(ins: Instruction) -> str:
    base = _reg(ins.rn)
    sign = "" if ins.up else "-"
    if ins.rm is not None:
        offset = f"{sign}{_reg(ins.rm)}{_shift(ins.shift)}"
    elif ins.pre and ins.up and not ins.writeback and ins.imm == 0:
        return f"[{base}]"
    else:
        offset = f"#{sign}{ins.imm}"
    if not ins.pre:
        return f"[{base}], {offset}"
    return f"[{base}, {offset}]" + ("!" if ins.writeback else "")


def _arm(ins: Instruction) -> str:
    op, c = ins.op, _cond(ins)
    s = "s" if ins.s and op not in COMPARE_OPS else ""
    if op in DATA_PROCESSING_OPS:
        operands = []
        if op not in COMPARE_OPS:
            operands.append(_reg(ins.rd))
        if op not in MOVE_OPS:
            operands.append(_reg(ins.rn))
        if ins.imm is not None:
            operands.append(f"#{ins.imm:#x}")
        else:
            operands.append(_reg(ins.rm) + _shift(ins.shift))
        return f"{op.value}{s}{c} " + ", ".join(operands)
    if op in (Op.MUL, Op.MLA):
        text = f"{op.value}{s}{c} {_reg(ins.rd)}, {_reg(ins.rm)}, {_reg(ins.rs)}"
        return text + (f", {_reg(ins.rn)}" if op is Op.MLA else "")
    if op in _LONG_MULTIPLY_OPS:
        return (
            f"{op.value}{s}{c} {_reg(ins.rd)}, {_reg(ins.rd_hi)}, "
            f"{_reg(ins.rm)}, {_reg(ins.rs)}"
        )
    if op in (Op.SWP, Op.SWPB):
        return f"{op.value}{c} {_reg(ins.rd)}, {_reg(ins.rm)}, [{_reg(ins.rn)}]"
    if op in _TRANSFER_OPS:
        t = "t" if ins.user else ""
        return f"{op.value}{t}{c} {_reg(ins.rd)}, {_address(ins)}"
    if op in (Op.LDM, Op.STM):
        mode = _BLOCK_MODES[(ins.pre, ins.up)]
        writeback = "!" if ins.writeback else ""
        caret = "^" if ins.user else ""
        return f"{op.value}{mode}{c} {_reg(ins.rn)}{writeback}, {_reglist(ins.reglist)}{caret}"
    if op in (Op.B, Op.BL):
        return f"{op.value}{c} #{ins.target:#x}"
    if op is Op.BX:
        return f"bx{c} {_reg(ins.rm)}"
    if op is Op.SWI:
        return f"svc{c} #{ins.imm:#x}"
    if op is Op.MRS:
        return f"mrs{c} {_reg(ins.rd)}, {'spsr' if ins.spsr else 'cpsr'}"
    if op is Op.MSR:
        fields = "".join(letter for bit, letter in _PSR_FIELDS if (ins.psr_mask >> bit) & 1)
        if not fields:
            return _data(ins)
        source = f"#{ins.imm:#x}" if ins.imm is not None else _reg(ins.rm)
        return f"msr{c} {'spsr' if ins.spsr else 'cpsr'}_{fields}, {source}"
    raise ValueError(f"no ARM syntax for {op}")


def _thumb(ins: Instruction) -> str:
    fmt, op = ins.thumb_format, ins.op
    if fmt == 1:
        kind = ins.shift.kind.value if ins.shift else "lsl"
        amount = ins.shift.amount if ins.shift else 0
        return f"{kind}s {_reg(ins.rd)}, {_reg(ins.rm)}, #{amount}"
    if fmt == 2:
        operand = f"#{ins.imm}" if ins.imm is not None else _reg(ins.rm)
        return f"{op.value}s {_reg(ins.rd)}, {_reg(ins.rn)}, {operand}"
    if fmt == 3:
        if op is Op.CMP:
            return f"cmp {_reg(ins.rn)}, #{ins.imm}"
        return f"{op.value}s {_reg(ins.rd)}, #{ins.imm}"
    if fmt == 4:
        if ins.shift is not None:
            return f"{ins.shift.kind.value}s {_reg(ins.rd)}, {_reg(ins.shift.reg)}"
        if op in COMPARE_OPS:
            return f"{op.value} {_reg(ins.rn)}, {_reg(ins.rm)}"
        if op is Op.RSB:
            return f"rsbs {_reg(ins.rd)}, {_reg(ins.rn)}, #0"
        if op is Op.MUL:
            return f"muls {_reg(ins.rd)}, {_reg(ins.rm)}, {_reg(ins.rd)}"
        return f"{op.value}s {_reg(ins.rd)}, {_reg(ins.rm)}"
    if fmt == 5:
        if op is Op.BX:
            return f"bx {_reg(ins.rm)}"
        if op is Op.CMP:
            return f"cmp {_reg(ins.rn)}, {_reg(ins.rm)}"
        return f"{op.value} {_reg(ins.rd)}, {_reg(ins.rm)}"
    if fmt == 6:
        return f"ldr {_reg(ins.rd)}, [pc, #{ins.imm}]"
    if fmt in (7, 8, 9, 10, 11):
        return f"{op.value} {_reg(ins.rd)}, {_address(ins)}"
    if fmt == 12:
        if ins.rn == 13:
            return f"add {_reg(ins.rd)}, sp, #{ins.imm}"
        return f"adr {_reg(ins.rd)}, #{ins.imm}"
    if fmt == 13:
        return f"{op.value} sp, #{ins.imm}"
    if fmt == 14:
        return f"{'pop' if op is Op.LDM else 'push'} {_reglist(ins.reglist)}"
    if fmt == 15:
        if ins.writeback:
            return f"{op.value}ia {_reg(ins.rn)}!, {_reglist(ins.reglist)}"
        return f"ldm {_reg(ins.rn)}, {_reglist(ins.reglist)}"
    if fmt in (16, 18):
        return f"b{_cond(ins)} #{ins.target:#x}"
    if fmt == 17:
        return f"svc #{ins.imm:#x}"
    if op is Op.BL:
        return f"bl #{ins.target:#x}"
    return f".hword {ins.raw:#06x}  @ {op.value} {ins.imm:+#x}"  # unpaired BL half
