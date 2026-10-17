"""ARMv4T Thumb-state decoder (ARM7TDMI formats 1-19).

Each Thumb instruction decodes into the equivalent ARM operation so later stages
see one semantic model; ``thumb_format`` keeps the original format number.
PC-relative forms (format 6 literal loads, format 12 ADR) get their absolute
address in ``target`` because Thumb word-aligns the PC for them.
"""

from gbaport.isa.bits import sign_extend
from gbaport.isa.model import Cond, Instruction, Mode, Op, Shift, ShiftKind

_F3_OPS = (Op.MOV, Op.CMP, Op.ADD, Op.SUB)
_F4_BINARY = {0: Op.AND, 1: Op.EOR, 5: Op.ADC, 6: Op.SBC, 12: Op.ORR, 14: Op.BIC}
_F4_SHIFTS = {2: ShiftKind.LSL, 3: ShiftKind.LSR, 4: ShiftKind.ASR, 7: ShiftKind.ROR}
_F4_COMPARE = {8: Op.TST, 10: Op.CMP, 11: Op.CMN}
_F7_OPS = (Op.STR, Op.STRB, Op.LDR, Op.LDRB)  # index: L << 1 | B
_F8_OPS = (Op.STRH, Op.LDRSB, Op.LDRH, Op.LDRSH)  # index: H << 1 | S


def decode_thumb(halfword: int, addr: int, next_halfword: int | None = None) -> Instruction:
    """Decode the Thumb halfword at ``addr``.

    ``next_halfword`` lets a BL prefix pair with its suffix into one 4-byte BL.
    """
    hw = halfword
    top = hw >> 13
    if top == 0b000:
        return _format2(hw, addr) if ((hw >> 11) & 3) == 3 else _format1(hw, addr)
    if top == 0b001:
        return _format3(hw, addr)
    if top == 0b010:
        if (hw >> 10) == 0b010000:
            return _format4(hw, addr)
        if (hw >> 10) == 0b010001:
            return _format5(hw, addr)
        if (hw >> 11) == 0b01001:
            return _format6(hw, addr)
        return _format8(hw, addr) if hw & 0x0200 else _format7(hw, addr)
    if top == 0b011:
        return _format9(hw, addr)
    if top == 0b100:
        return _format11(hw, addr) if hw & 0x1000 else _format10(hw, addr)
    if top == 0b101:
        if not hw & 0x1000:
            return _format12(hw, addr)
        if (hw & 0xFF00) == 0xB000:
            return _format13(hw, addr)
        if (hw & 0xF600) == 0xB400:
            return _format14(hw, addr)
        return _undefined(hw, addr)
    if top == 0b110:
        return _format16_17(hw, addr) if hw & 0x1000 else _format15(hw, addr)
    return _format18_19(hw, addr, next_halfword)


def _base(hw: int, addr: int, fmt: int) -> dict:
    return {"addr": addr, "mode": Mode.THUMB, "size": 2, "raw": hw, "thumb_format": fmt}


def _undefined(hw: int, addr: int) -> Instruction:
    return Instruction(addr=addr, mode=Mode.THUMB, size=2, raw=hw, op=Op.UNDEFINED)


def _lo(hw: int, shift: int) -> int:
    return (hw >> shift) & 7


def _aligned_pc_target(addr: int, imm: int) -> int:
    return (((addr + 4) & ~3) + imm) & 0xFFFFFFFF


def _format1(hw: int, addr: int) -> Instruction:  # LSL/LSR/ASR Rd, Rs, #offset5
    return Instruction(
        **_base(hw, addr, 1), op=Op.MOV, s=True, rd=_lo(hw, 0), rm=_lo(hw, 3),
        shift=Shift.from_imm_field((hw >> 11) & 3, (hw >> 6) & 0x1F),
    )


def _format2(hw: int, addr: int) -> Instruction:  # ADD/SUB Rd, Rs, Rn|#offset3
    operand = {"imm": _lo(hw, 6)} if hw & 0x0400 else {"rm": _lo(hw, 6)}
    return Instruction(
        **_base(hw, addr, 2), op=Op.SUB if hw & 0x0200 else Op.ADD, s=True,
        rd=_lo(hw, 0), rn=_lo(hw, 3), **operand,
    )


def _format3(hw: int, addr: int) -> Instruction:  # MOV/CMP/ADD/SUB Rd, #offset8
    op = _F3_OPS[(hw >> 11) & 3]
    reg = _lo(hw, 8)
    if op is Op.MOV:
        regs = {"rd": reg}
    elif op is Op.CMP:
        regs = {"rn": reg}
    else:
        regs = {"rd": reg, "rn": reg}
    return Instruction(**_base(hw, addr, 3), op=op, s=True, imm=hw & 0xFF, **regs)


def _format4(hw: int, addr: int) -> Instruction:  # ALU operations
    alu, rs, rd = (hw >> 6) & 0xF, _lo(hw, 3), _lo(hw, 0)
    base = _base(hw, addr, 4)
    if alu in _F4_BINARY:
        return Instruction(**base, op=_F4_BINARY[alu], s=True, rd=rd, rn=rd, rm=rs)
    if alu in _F4_SHIFTS:
        return Instruction(
            **base, op=Op.MOV, s=True, rd=rd, rm=rd, shift=Shift(_F4_SHIFTS[alu], reg=rs)
        )
    if alu in _F4_COMPARE:
        return Instruction(**base, op=_F4_COMPARE[alu], s=True, rn=rd, rm=rs)
    if alu == 9:  # NEG Rd, Rs == RSBS Rd, Rs, #0
        return Instruction(**base, op=Op.RSB, s=True, rd=rd, rn=rs, imm=0)
    if alu == 13:  # MUL Rd, Rs == MULS Rd, Rs, Rd
        return Instruction(**base, op=Op.MUL, s=True, rd=rd, rm=rs, rs=rd)
    return Instruction(**base, op=Op.MVN, s=True, rd=rd, rm=rs)  # alu == 15


def _format5(hw: int, addr: int) -> Instruction:  # hi-register ops / BX
    op_bits = (hw >> 8) & 3
    rd = _lo(hw, 0) | ((hw >> 4) & 8)  # H1 is bit 7
    rm = _lo(hw, 3) | ((hw >> 3) & 8)  # H2 is bit 6
    base = _base(hw, addr, 5)
    if op_bits == 0:
        return Instruction(**base, op=Op.ADD, rd=rd, rn=rd, rm=rm)
    if op_bits == 1:
        return Instruction(**base, op=Op.CMP, s=True, rn=rd, rm=rm)
    if op_bits == 2:
        return Instruction(**base, op=Op.MOV, rd=rd, rm=rm)
    if hw & 0x0080:  # H1 set on BX is BLX (ARMv5)
        return _undefined(hw, addr)
    return Instruction(**base, op=Op.BX, rm=rm)


def _format6(hw: int, addr: int) -> Instruction:  # LDR Rd, [PC, #imm]
    imm = (hw & 0xFF) * 4
    return Instruction(
        **_base(hw, addr, 6), op=Op.LDR, rd=_lo(hw, 8), rn=15, imm=imm,
        target=_aligned_pc_target(addr, imm),
    )


def _format7(hw: int, addr: int) -> Instruction:  # LDR/STR{B} Rd, [Rb, Ro]
    return Instruction(
        **_base(hw, addr, 7), op=_F7_OPS[(hw >> 10) & 3],
        rd=_lo(hw, 0), rn=_lo(hw, 3), rm=_lo(hw, 6),
    )


def _format8(hw: int, addr: int) -> Instruction:  # STRH/LDRH/LDSB/LDSH Rd, [Rb, Ro]
    return Instruction(
        **_base(hw, addr, 8), op=_F8_OPS[(hw >> 10) & 3],
        rd=_lo(hw, 0), rn=_lo(hw, 3), rm=_lo(hw, 6),
    )


def _format9(hw: int, addr: int) -> Instruction:  # LDR/STR{B} Rd, [Rb, #offset5]
    byte, load = bool(hw & 0x1000), bool(hw & 0x0800)
    offset = (hw >> 6) & 0x1F
    return Instruction(
        **_base(hw, addr, 9), op=((Op.STR, Op.LDR), (Op.STRB, Op.LDRB))[byte][load],
        rd=_lo(hw, 0), rn=_lo(hw, 3), imm=offset if byte else offset * 4,
    )


def _format10(hw: int, addr: int) -> Instruction:  # LDRH/STRH Rd, [Rb, #offset5]
    return Instruction(
        **_base(hw, addr, 10), op=Op.LDRH if hw & 0x0800 else Op.STRH,
        rd=_lo(hw, 0), rn=_lo(hw, 3), imm=((hw >> 6) & 0x1F) * 2,
    )


def _format11(hw: int, addr: int) -> Instruction:  # LDR/STR Rd, [SP, #imm]
    return Instruction(
        **_base(hw, addr, 11), op=Op.LDR if hw & 0x0800 else Op.STR,
        rd=_lo(hw, 8), rn=13, imm=(hw & 0xFF) * 4,
    )


def _format12(hw: int, addr: int) -> Instruction:  # ADD Rd, SP|PC, #imm
    imm = (hw & 0xFF) * 4
    base = _base(hw, addr, 12)
    if hw & 0x0800:
        return Instruction(**base, op=Op.ADD, rd=_lo(hw, 8), rn=13, imm=imm)
    return Instruction(
        **base, op=Op.ADD, rd=_lo(hw, 8), rn=15, imm=imm, target=_aligned_pc_target(addr, imm)
    )


def _format13(hw: int, addr: int) -> Instruction:  # ADD/SUB SP, #imm
    return Instruction(
        **_base(hw, addr, 13), op=Op.SUB if hw & 0x80 else Op.ADD,
        rd=13, rn=13, imm=(hw & 0x7F) * 4,
    )


def _format14(hw: int, addr: int) -> Instruction:  # PUSH/POP
    regs = [r for r in range(8) if hw & (1 << r)]
    base = _base(hw, addr, 14)
    if hw & 0x0800:
        if hw & 0x0100:
            regs.append(15)
        return Instruction(
            **base, op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=tuple(regs)
        )
    if hw & 0x0100:
        regs.append(14)
    return Instruction(
        **base, op=Op.STM, rn=13, pre=True, up=False, writeback=True, reglist=tuple(regs)
    )


def _format15(hw: int, addr: int) -> Instruction:  # LDMIA/STMIA Rb!, {Rlist}
    rb = _lo(hw, 8)
    regs = tuple(r for r in range(8) if hw & (1 << r))
    load = bool(hw & 0x0800)
    # A load that includes the base overwrites the written-back value, so no writeback.
    return Instruction(
        **_base(hw, addr, 15), op=Op.LDM if load else Op.STM, rn=rb, pre=False, up=True,
        writeback=not (load and rb in regs), reglist=regs,
    )


def _format16_17(hw: int, addr: int) -> Instruction:  # B{cond} / SWI
    cond = (hw >> 8) & 0xF
    if cond == 0xF:
        return Instruction(**_base(hw, addr, 17), op=Op.SWI, imm=hw & 0xFF)
    if cond == 0xE:
        return _undefined(hw, addr)
    offset = sign_extend(hw & 0xFF, 8) * 2
    return Instruction(
        **_base(hw, addr, 16), op=Op.B, cond=Cond(cond), target=(addr + 4 + offset) & 0xFFFFFFFF
    )


def _format18_19(hw: int, addr: int, next_hw: int | None) -> Instruction:  # B / BL
    kind = (hw >> 11) & 3
    if kind == 0b00:
        offset = sign_extend(hw & 0x7FF, 11) * 2
        return Instruction(
            **_base(hw, addr, 18), op=Op.B, target=(addr + 4 + offset) & 0xFFFFFFFF
        )
    if kind == 0b01:
        return _undefined(hw, addr)  # BLX suffix (ARMv5)
    if kind == 0b10:
        high = sign_extend(hw & 0x7FF, 11) << 12
        if next_hw is not None and (next_hw & 0xF800) == 0xF800:
            target = (addr + 4 + high + ((next_hw & 0x7FF) << 1)) & 0xFFFFFFFF
            return Instruction(
                addr=addr, mode=Mode.THUMB, size=4, raw=hw | (next_hw << 16), op=Op.BL,
                target=target, thumb_format=19,
            )
        return Instruction(**_base(hw, addr, 19), op=Op.BL_HI, imm=high)
    return Instruction(**_base(hw, addr, 19), op=Op.BL_LO, imm=(hw & 0x7FF) << 1)
