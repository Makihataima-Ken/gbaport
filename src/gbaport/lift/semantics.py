"""C statements for what one ARMv4T instruction does to registers, flags and memory.

ARM and Thumb share one model (Thumb decodes into ARM-equivalent operations), so
one translation serves both. Control flow is left to ``function.py``: a write
to r15 goes to the C local ``t`` instead, and the caller turns it into a jump,
a call or a return. Reads of r15 are compile-time constants (ARM +8, Thumb +4,
+12 for an ARM register-specified shift, word-aligned for Thumb literal loads).
"""

from gbaport.analysis.effects import PC, pc_value
from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    MOVE_OPS,
    Cond,
    Instruction,
    Mode,
    Op,
    ShiftKind,
)

LOGICAL_OPS = frozenset({Op.AND, Op.EOR, Op.TST, Op.TEQ, Op.ORR, Op.MOV, Op.BIC, Op.MVN})
CONDITIONS = {cond: f"GBA_{cond.name}" for cond in Cond if cond is not Cond.AL}
_LOADS = {Op.LDR: "gba_ldr", Op.LDRB: "gba_read8", Op.LDRH: "gba_ldrh",
          Op.LDRSB: "gba_ldrsb", Op.LDRSH: "gba_ldrsh"}
_STORES = {Op.STR: "gba_str", Op.STRB: "gba_strb", Op.STRH: "gba_strh"}
_LONG_MULTIPLY = {Op.UMULL: (False, False), Op.UMLAL: (False, True),
                  Op.SMULL: (True, False), Op.SMLAL: (True, True)}  # (signed, accumulate)


class LiftError(ValueError):
    """An instruction the lifter cannot express in C."""


def hexu(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08x}u"


def read(ins: Instruction, n: int, extra: int = 0) -> str:
    """C expression for the value of register ``n`` as ``ins`` sees it."""
    if n == PC:
        return hexu(pc_value(ins) + extra)
    return f"ctx->r[{n}]"


def dest(n: int) -> str:
    return "t" if n == PC else f"ctx->r[{n}]"


def lift_effects(ins: Instruction) -> list[str]:
    """Statements for ``ins`` apart from control flow (and apart from its condition)."""
    op = ins.op
    if op in DATA_PROCESSING_OPS:
        return _data_processing(ins)
    if op in (Op.MUL, Op.MLA):
        return _multiply(ins)
    if op in _LONG_MULTIPLY:
        return _long_multiply(ins)
    if op in _LOADS or op in _STORES:
        return _single_transfer(ins)
    if op in (Op.LDM, Op.STM):
        return _block_transfer(ins)
    if op in (Op.SWP, Op.SWPB):
        return _swap(ins)
    if op is Op.MRS:  # only ARM code has MRS, so the T bit reads as clear
        return [f"ctx->r[{ins.rd}] = {'ctx->spsr' if ins.spsr else 'gba_cpsr(ctx) & ~0x20u'};"]
    if op is Op.MSR:
        value = hexu(ins.imm) if ins.imm is not None else read(ins, ins.rm)
        setter = "gba_set_spsr" if ins.spsr else "gba_set_cpsr"
        return [f"{setter}(ctx, {value}, {ins.psr_mask}u);"]
    if op is Op.SWI:
        number = ins.imm >> 16 if ins.mode is Mode.ARM else ins.imm
        return [f"gba_swi(ctx, 0x{number:02x}u);"]
    if op is Op.BX:
        return [f"t = {read(ins, ins.rm)};"]
    if op is Op.BL_HI:
        return [f"ctx->r[14] = {hexu(pc_value(ins) + ins.imm)};"]
    raise LiftError(f"{ins.addr:#010x}: no effects for {op.value}")


def cycles(ins: Instruction) -> int:
    """A rough cycle estimate; the scheduler only needs the right order of magnitude."""
    op = ins.op
    if op in _LOADS or op in (Op.SWP, Op.SWPB):
        return 3
    if op in _STORES:
        return 2
    if op in (Op.LDM, Op.STM):
        return 2 + len(ins.reglist)
    if op in (Op.MUL, Op.MLA):
        return 4
    if op in _LONG_MULTIPLY:
        return 5
    if op in (Op.B, Op.BL, Op.BX, Op.BL_LO):
        return 3
    return 1


def _operand2(ins: Instruction, carry: bool, extra: int) -> str:
    """The shifter operand; with ``carry``, the expression also sets ctx->c like the shifter."""
    if ins.imm is not None:
        if carry and ins.imm_rot:
            return f"gba_imm_c({hexu(ins.imm)}, &ctx->c)"
        return hexu(ins.imm)
    value = read(ins, ins.rm, extra)
    shift = ins.shift
    if shift is None:
        return value
    if shift.kind is ShiftKind.RRX:
        return f"gba_rrx_c({value}, &ctx->c)" if carry else f"gba_rrx({value}, ctx->c)"
    amount = f"(ctx->r[{shift.reg}] & 0xFFu)" if shift.reg is not None else f"{shift.amount}u"
    name = f"gba_{shift.kind.value}"
    return f"{name}_c({value}, {amount}, &ctx->c)" if carry else f"{name}({value}, {amount})"


def _data_processing(ins: Instruction) -> list[str]:
    op = ins.op
    if op is Op.ADD and ins.rn == PC and ins.target is not None:  # Thumb ADR
        return [f"{dest(ins.rd)} = {hexu(ins.target)};"]
    by_register = ins.shift is not None and ins.shift.reg is not None
    extra = 4 if by_register and ins.mode is Mode.ARM else 0
    exception_return = ins.s and ins.rd == PC
    flags = ins.s and not exception_return
    operand = _operand2(ins, carry=flags and op in LOGICAL_OPS, extra=extra)
    a = None if op in MOVE_OPS else read(ins, ins.rn, extra)
    if op in LOGICAL_OPS:
        value = {
            Op.AND: f"{a} & op2", Op.TST: f"{a} & op2", Op.EOR: f"{a} ^ op2",
            Op.TEQ: f"{a} ^ op2", Op.ORR: f"{a} | op2", Op.BIC: f"{a} & ~op2",
            Op.MOV: "op2", Op.MVN: "~op2",
        }[op]
        if flags:
            value = f"gba_nz(ctx, {value})"
    else:
        x, y, carry_in = {
            Op.ADD: (a, "op2", "0"), Op.CMN: (a, "op2", "0"), Op.ADC: (a, "op2", "ctx->c"),
            Op.SUB: (a, "~op2", "1"), Op.CMP: (a, "~op2", "1"), Op.SBC: (a, "~op2", "ctx->c"),
            Op.RSB: ("op2", f"~{a}", "1"), Op.RSC: ("op2", f"~{a}", "ctx->c"),
        }[op]
        value = f"gba_addc(ctx, {x}, {y}, {carry_in})" if flags else f"{x} + {y} + {carry_in}"
    body = [f"uint32_t op2 = {operand};"]
    if op in COMPARE_OPS:
        body.append(f"(void)({value});")
    else:
        body.append(f"{dest(ins.rd)} = {value};")
    if exception_return:
        body.append("gba_restore_cpsr(ctx);")
    return _scoped(body)


def _multiply(ins: Instruction) -> list[str]:
    value = f"{read(ins, ins.rm)} * {read(ins, ins.rs)}"
    if ins.op is Op.MLA:
        value += f" + {read(ins, ins.rn)}"
    if ins.s:  # C is left alone (the ARM7TDMI leaves it meaningless), V unchanged
        value = f"gba_nz(ctx, {value})"
    return [f"ctx->r[{ins.rd}] = {value};"]


def _long_multiply(ins: Instruction) -> list[str]:
    signed, accumulate = _LONG_MULTIPLY[ins.op]
    rm, rs = read(ins, ins.rm), read(ins, ins.rs)
    if signed:
        product = f"(uint64_t)((int64_t)(int32_t){rm} * (int32_t){rs})"
    else:
        product = f"(uint64_t){rm} * {rs}"
    body = [f"uint64_t p = {product};"]
    if accumulate:
        body.append(f"p += (uint64_t)ctx->r[{ins.rd_hi}] << 32 | ctx->r[{ins.rd}];")
    if ins.s:
        body.append("gba_nz64(ctx, p);")
    body += [f"ctx->r[{ins.rd}] = (uint32_t)p;", f"ctx->r[{ins.rd_hi}] = (uint32_t)(p >> 32);"]
    return _scoped(body)


def _offset(ins: Instruction) -> str:
    if ins.rm is None:
        return hexu(ins.imm)
    value = read(ins, ins.rm)
    shift = ins.shift
    if shift is None:
        return value
    if shift.kind is ShiftKind.RRX:
        return f"gba_rrx({value}, ctx->c)"
    return f"gba_{shift.kind.value}({value}, {shift.amount}u)"


def _single_transfer(ins: Instruction) -> list[str]:
    if ins.rn == PC and ins.target is not None:  # literal pool (Thumb: word-aligned pc)
        address, written_back = hexu(ins.target), None
    else:
        base = read(ins, ins.rn)
        moved = f"{base} {'+' if ins.up else '-'} {_offset(ins)}"
        address = moved if ins.pre else base
        written_back = moved if ins.writeback else None
    body = [f"uint32_t addr = {address};"]
    if ins.op in _STORES:
        extra = 4 if ins.rd == PC and ins.mode is Mode.ARM else 0  # STR pc stores pc + 12
        body.append(f"uint32_t v = {read(ins, ins.rd, extra)};")
        if written_back is not None:
            body.append(f"ctx->r[{ins.rn}] = {written_back};")
        body.append(f"{_STORES[ins.op]}(ctx, addr, v);")
    else:
        if written_back is not None:
            body.insert(0, f"uint32_t wb = {written_back};")
        body.append(f"uint32_t v = {_LOADS[ins.op]}(ctx, addr);")
        if written_back is not None:
            body.append(f"ctx->r[{ins.rn}] = wb;")
        body.append(f"{dest(ins.rd)} = v;")  # a loaded base wins over the written-back one
    return _scoped(body)


def _block_transfer(ins: Instruction) -> list[str]:
    regs = ins.reglist
    if not regs:
        raise LiftError(f"{ins.addr:#010x}: LDM/STM with an empty register list")
    count = len(regs)
    base = read(ins, ins.rn)
    first = {(False, True): 0, (True, True): 4, (False, False): -4 * count + 4,
             (True, False): -4 * count}[(ins.pre, ins.up)]
    final = f"{base} {'+' if ins.up else '-'} {hexu(4 * count)}"
    restore = ins.user and ins.op is Op.LDM and PC in regs
    user = ins.user and not restore
    body = [f"uint32_t addr = ({base} + {hexu(first)}) & ~3u;", f"uint32_t final = {final};"]
    for i, r in enumerate(regs):
        slot = f"addr + {4 * i}u"
        target = f"*gba_user_reg(ctx, {r})" if user and r != PC else dest(r)
        if ins.op is Op.STM:
            if r == ins.rn and ins.writeback and i > 0:
                value = "final"  # ARMv4: the new base is stored unless it comes first
            elif r == PC:
                value = hexu(pc_value(ins) + 4)
            else:
                value = target
            body.append(f"gba_write32(ctx, {slot}, {value});")
        else:
            body.append(f"{target} = gba_read32(ctx, {slot});")
    if ins.writeback:
        body.append(f"ctx->r[{ins.rn}] = final;")
    else:
        body.append("(void)final;")
    if restore:
        body.append("gba_restore_cpsr(ctx);")
    return _scoped(body)


def _swap(ins: Instruction) -> list[str]:
    load, store = ("gba_read8", "gba_strb") if ins.op is Op.SWPB else ("gba_ldr", "gba_str")
    return _scoped([
        f"uint32_t addr = {read(ins, ins.rn)};",
        f"uint32_t old = {load}(ctx, addr);",
        f"{store}(ctx, addr, {read(ins, ins.rm)});",
        f"ctx->r[{ins.rd}] = old;",
    ])


def _scoped(body: list[str]) -> list[str]:
    return ["{", *("    " + line for line in body), "}"]
