"""ARMv4T (ARM7TDMI) ARM-state decoder.

Anything outside ARMv4T decodes to ``Op.UNDEFINED``: coprocessor instructions
(the GBA has no coprocessor), ARMv5+ encodings (BLX, CLZ, LDRD/STRD, QADD, ...),
ARMv6 media instructions and the NV condition.
"""

from gbaport.isa.bits import bit, field, ror32, sign_extend
from gbaport.isa.model import (
    COMPARE_OPS,
    DATA_PROCESSING_OPS,
    MOVE_OPS,
    SHIFT_FIELD_KINDS,
    Cond,
    Instruction,
    Mode,
    Op,
    Shift,
)

_LONG_MULTIPLY = ((Op.UMULL, Op.UMLAL), (Op.SMULL, Op.SMLAL))  # [signed][accumulate]
_SINGLE_OPS = ((Op.STR, Op.STRB), (Op.LDR, Op.LDRB))  # [load][byte]
_HALFWORD_OPS = {
    (False, 1): Op.STRH,
    (True, 1): Op.LDRH,
    (True, 2): Op.LDRSB,
    (True, 3): Op.LDRSH,
}  # (load, SH field)


def decode_arm(word: int, addr: int) -> Instruction:
    """Decode the 32-bit ARM instruction ``word`` located at bus address ``addr``."""
    if word >> 28 == 0xF:
        return Instruction(addr=addr, mode=Mode.ARM, size=4, raw=word, op=Op.UNDEFINED)
    base = {"addr": addr, "mode": Mode.ARM, "size": 4, "raw": word, "cond": Cond(word >> 28)}
    group = field(word, 27, 25)
    if group == 0b000:
        return _group0(word, base)
    if group == 0b001:
        return _group1(word, base)
    if group in (0b010, 0b011):
        return _single_transfer(word, base)
    if group == 0b100:
        return _block_transfer(word, base)
    if group == 0b101:
        offset = sign_extend(word & 0xFFFFFF, 24) << 2
        return Instruction(
            **base, op=Op.BL if bit(word, 24) else Op.B, target=(addr + 8 + offset) & 0xFFFFFFFF
        )
    if group == 0b111 and bit(word, 24):
        return Instruction(**base, op=Op.SWI, imm=word & 0xFFFFFF)
    return Instruction(**base, op=Op.UNDEFINED)  # coprocessor space


def _group0(word: int, base: dict) -> Instruction:
    if (word & 0x0FFFFFF0) == 0x012FFF10:
        return Instruction(**base, op=Op.BX, rm=word & 0xF)
    if (word & 0x0FC000F0) == 0x00000090:
        accumulate = bit(word, 21)
        return Instruction(
            **base,
            op=Op.MLA if accumulate else Op.MUL,
            s=bit(word, 20),
            rd=field(word, 19, 16),
            rn=field(word, 15, 12) if accumulate else None,
            rs=field(word, 11, 8),
            rm=word & 0xF,
        )
    if (word & 0x0F8000F0) == 0x00800090:
        return Instruction(
            **base,
            op=_LONG_MULTIPLY[bit(word, 22)][bit(word, 21)],
            s=bit(word, 20),
            rd_hi=field(word, 19, 16),
            rd=field(word, 15, 12),
            rs=field(word, 11, 8),
            rm=word & 0xF,
        )
    if (word & 0x0FB00FF0) == 0x01000090:
        return Instruction(
            **base,
            op=Op.SWPB if bit(word, 22) else Op.SWP,
            rn=field(word, 19, 16),
            rd=field(word, 15, 12),
            rm=word & 0xF,
        )
    if (word & 0x90) == 0x90:
        if (word & 0x60) == 0:
            return Instruction(**base, op=Op.UNDEFINED)  # unallocated multiply space
        return _halfword_transfer(word, base)
    if (word & 0x0FBF0FFF) == 0x010F0000:
        return Instruction(**base, op=Op.MRS, rd=field(word, 15, 12), spsr=bit(word, 22))
    if (word & 0x0FB0FFF0) == 0x0120F000:
        return Instruction(
            **base, op=Op.MSR, spsr=bit(word, 22), psr_mask=field(word, 19, 16), rm=word & 0xF
        )
    if (word & 0x01900000) == 0x01000000:
        return Instruction(**base, op=Op.UNDEFINED)  # ARMv5+ miscellaneous space
    op = DATA_PROCESSING_OPS[field(word, 24, 21)]
    if bit(word, 4):
        shift = Shift(SHIFT_FIELD_KINDS[field(word, 6, 5)], reg=field(word, 11, 8))
    else:
        shift = Shift.from_imm_field(field(word, 6, 5), field(word, 11, 7))
    return Instruction(**base, op=op, rm=word & 0xF, shift=shift, **_dp_registers(word, op))


def _group1(word: int, base: dict) -> Instruction:
    rot = field(word, 11, 8)
    value = ror32(word & 0xFF, rot * 2)
    if (word & 0x0FB0F000) == 0x0320F000:
        return Instruction(
            **base, op=Op.MSR, spsr=bit(word, 22), psr_mask=field(word, 19, 16),
            imm=value, imm_rot=rot,
        )
    if (word & 0x01900000) == 0x01000000:
        return Instruction(**base, op=Op.UNDEFINED)  # MOVW/MOVT (ARMv6T2)
    op = DATA_PROCESSING_OPS[field(word, 24, 21)]
    return Instruction(**base, op=op, imm=value, imm_rot=rot, **_dp_registers(word, op))


def _dp_registers(word: int, op: Op) -> dict:
    return {
        "s": bit(word, 20),
        "rd": None if op in COMPARE_OPS else field(word, 15, 12),
        "rn": None if op in MOVE_OPS else field(word, 19, 16),
    }


def _transfer_fields(word: int) -> dict:
    pre = bit(word, 24)
    return {
        "rd": field(word, 15, 12),
        "rn": field(word, 19, 16),
        "pre": pre,
        "up": bit(word, 23),
        "writeback": bit(word, 21) or not pre,
    }


def _literal_target(addr: int, fields: dict) -> int | None:
    """Absolute address of a PC-relative, pre-indexed access without writeback."""
    if fields["rn"] != 15 or not fields["pre"] or fields["writeback"]:
        return None
    offset = fields["imm"] if fields["up"] else -fields["imm"]
    return (addr + 8 + offset) & 0xFFFFFFFF


def _single_transfer(word: int, base: dict) -> Instruction:
    register_offset = bit(word, 25)
    if register_offset and bit(word, 4):
        return Instruction(**base, op=Op.UNDEFINED)  # ARMv6 media space
    fields = _transfer_fields(word)
    fields["user"] = not bit(word, 24) and bit(word, 21)
    op = _SINGLE_OPS[bit(word, 20)][bit(word, 22)]
    if register_offset:
        fields["rm"] = word & 0xF
        fields["shift"] = Shift.from_imm_field(field(word, 6, 5), field(word, 11, 7))
    else:
        fields["imm"] = word & 0xFFF
        fields["target"] = _literal_target(base["addr"], fields)
    return Instruction(**base, op=op, **fields)


def _halfword_transfer(word: int, base: dict) -> Instruction:
    op = _HALFWORD_OPS.get((bit(word, 20), field(word, 6, 5)))
    post_writeback = not bit(word, 24) and bit(word, 21)
    immediate = bit(word, 22)
    if op is None or post_writeback or (not immediate and field(word, 11, 8)):
        # LDRD/STRD (ARMv5TE), unpredictable post-index writeback, or non-zero SBZ bits
        return Instruction(**base, op=Op.UNDEFINED)
    fields = _transfer_fields(word)
    if immediate:
        fields["imm"] = (field(word, 11, 8) << 4) | (word & 0xF)
        fields["target"] = _literal_target(base["addr"], fields)
    else:
        fields["rm"] = word & 0xF
    return Instruction(**base, op=op, **fields)


def _block_transfer(word: int, base: dict) -> Instruction:
    load, rn = bit(word, 20), field(word, 19, 16)
    reglist = tuple(r for r in range(16) if bit(word, r))
    return Instruction(
        **base,
        op=Op.LDM if load else Op.STM,
        rn=rn,
        pre=bit(word, 24),
        up=bit(word, 23),
        user=bit(word, 22),
        # ARMv4: an LDM that loads its own base keeps the loaded value, not the writeback.
        writeback=bit(word, 21) and not (load and rn in reglist),
        reglist=reglist,
    )
