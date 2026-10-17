"""Decoded-instruction model shared by the ARM and Thumb decoders.

Thumb instructions decode into the equivalent ARM operation, so analysis and
lifting handle one semantic model. Field meanings per operation:

- Data processing: ``rd`` (None for TST/TEQ/CMP/CMN), ``rn`` (None for
  MOV/MVN); the second operand is ``imm`` (``imm_rot`` is the ARM rotate field,
  needed for the shifter carry-out) or ``rm`` with an optional ``shift``.
- MUL: rd = rm * rs.  MLA: rd = rm * rs + rn.
- Long multiply: ``rd`` is RdLo, ``rd_hi`` is RdHi, operands ``rm`` and ``rs``.
- Single/halfword transfer: ``rd`` data register, ``rn`` base; the offset is
  ``imm`` (a magnitude) or ``rm`` (+``shift``). ``up`` adds the offset, ``pre``
  applies it before the access, ``writeback`` updates the base (always true
  when post-indexed), ``user`` marks LDRT/STRT.
- Block transfer: ``rn``, ``reglist``, ``pre``/``up``/``writeback``; ``user``
  is the ``^`` (S) bit. ``writeback`` means the base really ends up updated:
  it is False for an LDM whose ``reglist`` contains ``rn`` even when the W bit
  is set, because on ARMv4 the loaded value overwrites the written-back base
  (same rule in ARM and Thumb).
- SWP/SWPB: rd <- [rn], then [rn] <- rm.
- B/BL: absolute ``target``.  BX: ``rm``.  SWI: ``imm`` is the comment field.
- MRS: ``rd``, ``spsr``.  MSR: ``spsr``, ``psr_mask`` (bit0 c, bit1 x, bit2 s,
  bit3 f) and ``rm`` or ``imm``/``imm_rot``.
- BL_HI/BL_LO: a Thumb BL half seen without its partner; ``imm`` is the
  sign-extended high offset (already << 12) or the low offset (already << 1).

``target`` is also set to the absolute address of PC-relative literal loads and
Thumb ADR; when present it takes precedence over ``rn == 15`` arithmetic.
``thumb_format`` is the ARM7TDMI Thumb format number (1-19), kept for
formatting only.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum


class Mode(Enum):
    ARM = "arm"
    THUMB = "thumb"


class Cond(IntEnum):
    EQ = 0x0
    NE = 0x1
    CS = 0x2
    CC = 0x3
    MI = 0x4
    PL = 0x5
    VS = 0x6
    VC = 0x7
    HI = 0x8
    LS = 0x9
    GE = 0xA
    LT = 0xB
    GT = 0xC
    LE = 0xD
    AL = 0xE


class Op(Enum):
    AND = "and"
    EOR = "eor"
    SUB = "sub"
    RSB = "rsb"
    ADD = "add"
    ADC = "adc"
    SBC = "sbc"
    RSC = "rsc"
    TST = "tst"
    TEQ = "teq"
    CMP = "cmp"
    CMN = "cmn"
    ORR = "orr"
    MOV = "mov"
    BIC = "bic"
    MVN = "mvn"
    MUL = "mul"
    MLA = "mla"
    UMULL = "umull"
    UMLAL = "umlal"
    SMULL = "smull"
    SMLAL = "smlal"
    LDR = "ldr"
    STR = "str"
    LDRB = "ldrb"
    STRB = "strb"
    LDRH = "ldrh"
    STRH = "strh"
    LDRSB = "ldrsb"
    LDRSH = "ldrsh"
    LDM = "ldm"
    STM = "stm"
    SWP = "swp"
    SWPB = "swpb"
    B = "b"
    BL = "bl"
    BX = "bx"
    SWI = "swi"
    MRS = "mrs"
    MSR = "msr"
    BL_HI = "bl_hi"
    BL_LO = "bl_lo"
    UNDEFINED = "undefined"


# Index == the 4-bit ARM data-processing opcode field.
DATA_PROCESSING_OPS = (
    Op.AND, Op.EOR, Op.SUB, Op.RSB, Op.ADD, Op.ADC, Op.SBC, Op.RSC,
    Op.TST, Op.TEQ, Op.CMP, Op.CMN, Op.ORR, Op.MOV, Op.BIC, Op.MVN,
)
COMPARE_OPS = frozenset({Op.TST, Op.TEQ, Op.CMP, Op.CMN})
MOVE_OPS = frozenset({Op.MOV, Op.MVN})


class ShiftKind(Enum):
    LSL = "lsl"
    LSR = "lsr"
    ASR = "asr"
    ROR = "ror"
    RRX = "rrx"


# Index == the 2-bit shift-type field.
SHIFT_FIELD_KINDS = (ShiftKind.LSL, ShiftKind.LSR, ShiftKind.ASR, ShiftKind.ROR)


@dataclass(frozen=True)
class Shift:
    kind: ShiftKind
    amount: int = 0  # immediate amount, normalised (LSR/ASR #0 encode #32)
    reg: int | None = None  # register holding the amount, for register shifts

    @classmethod
    def from_imm_field(cls, kind_bits: int, amount: int) -> "Shift | None":
        """Decode an immediate shift field; ``None`` means no shift (LSL #0)."""
        kind = SHIFT_FIELD_KINDS[kind_bits]
        if amount == 0:
            if kind is ShiftKind.LSL:
                return None
            if kind is ShiftKind.ROR:
                return cls(ShiftKind.RRX)
            return cls(kind, 32)
        return cls(kind, amount)


@dataclass(frozen=True)
class Instruction:
    addr: int
    mode: Mode
    size: int
    raw: int
    op: Op
    cond: Cond = Cond.AL
    s: bool = False
    rd: int | None = None
    rn: int | None = None
    rm: int | None = None
    rs: int | None = None
    rd_hi: int | None = None
    imm: int | None = None
    imm_rot: int = 0
    shift: Shift | None = None
    pre: bool = True
    up: bool = True
    writeback: bool = False
    user: bool = False
    reglist: tuple[int, ...] = ()
    spsr: bool = False
    psr_mask: int = 0
    target: int | None = None
    thumb_format: int | None = None
