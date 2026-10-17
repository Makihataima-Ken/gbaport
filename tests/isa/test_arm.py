import random

import pytest

from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Cond, Mode, Op, Shift, ShiftKind

BASE = 0x08000000

CASES = [
    ("add r0, r1, r2, lsl #3", 0xE0810182,
     dict(op=Op.ADD, cond=Cond.AL, s=False, rd=0, rn=1, rm=2, shift=Shift(ShiftKind.LSL, 3))),
    ("addseq r0, r1, r2", 0x00910002,
     dict(op=Op.ADD, cond=Cond.EQ, s=True, rd=0, rn=1, rm=2, shift=None)),
    ("mov r0, #0xff000000", 0xE3A004FF,
     dict(op=Op.MOV, rd=0, rn=None, imm=0xFF000000, imm_rot=4)),
    ("mov r0, r1, lsl r2", 0xE1A00211,
     dict(op=Op.MOV, rd=0, rm=1, shift=Shift(ShiftKind.LSL, reg=2))),
    ("movs r0, r1, lsr #32", 0xE1B00021,
     dict(op=Op.MOV, s=True, rm=1, shift=Shift(ShiftKind.LSR, 32))),
    ("mov r0, r1, rrx", 0xE1A00061, dict(op=Op.MOV, rm=1, shift=Shift(ShiftKind.RRX))),
    ("tst r0, r1, lsl #3", 0xE1100181,
     dict(op=Op.TST, s=True, rd=None, rn=0, rm=1, shift=Shift(ShiftKind.LSL, 3))),
    ("teq r0, #1", 0xE3300001, dict(op=Op.TEQ, rn=0, imm=1, imm_rot=0)),
    ("mulseq r0, r1, r2", 0x00100291,
     dict(op=Op.MUL, cond=Cond.EQ, s=True, rd=0, rm=1, rs=2, rn=None)),
    ("mla r0, r1, r2, r3", 0xE0203291, dict(op=Op.MLA, rd=0, rm=1, rs=2, rn=3)),
    ("umull r0, r1, r2, r3", 0xE0810392, dict(op=Op.UMULL, rd=0, rd_hi=1, rm=2, rs=3)),
    ("smlals r0, r1, r2, r3", 0xE0F10392,
     dict(op=Op.SMLAL, s=True, rd=0, rd_hi=1, rm=2, rs=3)),
    ("swpb r0, r1, [r2]", 0xE1420091, dict(op=Op.SWPB, rd=0, rm=1, rn=2)),
    ("bx lr", 0xE12FFF1E, dict(op=Op.BX, rm=14)),
    ("bl #0x08000100", 0xEB00003E, dict(op=Op.BL, target=0x08000100)),
    ("beq #0x07fffff8", 0x0AFFFFFC, dict(op=Op.B, cond=Cond.EQ, target=0x07FFFFF8)),
    ("svc #0x50000", 0xEF050000, dict(op=Op.SWI, imm=0x50000)),
    ("mrs r0, spsr", 0xE14F0000, dict(op=Op.MRS, rd=0, spsr=True)),
    ("msr cpsr_fc, r0", 0xE129F000, dict(op=Op.MSR, spsr=False, psr_mask=0b1001, rm=0)),
    ("msr cpsr_f, #0xf0000000", 0xE328F20F,
     dict(op=Op.MSR, psr_mask=0b1000, imm=0xF0000000, imm_rot=2)),
    ("ldr r0, [r1, r2, lsl #2]", 0xE7910102,
     dict(op=Op.LDR, rd=0, rn=1, rm=2, shift=Shift(ShiftKind.LSL, 2),
          pre=True, up=True, writeback=False)),
    ("str r0, [r1], -r2, asr #3", 0xE60101C2,
     dict(op=Op.STR, pre=False, up=False, writeback=True, user=False, rm=2,
          shift=Shift(ShiftKind.ASR, 3))),
    ("ldrbt r0, [r1], #4", 0xE4F10004,
     dict(op=Op.LDRB, pre=False, writeback=True, user=True, imm=4)),
    ("ldr r0, [r1, #-4]!", 0xE5310004,
     dict(op=Op.LDR, pre=True, up=False, writeback=True, imm=4, target=None)),
    ("ldr r0, [pc, #8]", 0xE59F0008, dict(op=Op.LDR, rn=15, imm=8, target=0x08000010)),
    ("ldrh r0, [r1, #2]", 0xE1D100B2, dict(op=Op.LDRH, rd=0, rn=1, imm=2, pre=True)),
    ("ldrsh r0, [r1], #-4", 0xE05100F4,
     dict(op=Op.LDRSH, pre=False, up=False, writeback=True, imm=4)),
    ("ldrh r0, [r1, -r2]!", 0xE13100B2,
     dict(op=Op.LDRH, rm=2, up=False, writeback=True, imm=None)),
    ("ldmfd sp!, {r4-r7, pc}", 0xE8BD80F0,
     dict(op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=(4, 5, 6, 7, 15))),
    ("stmdb sp!, {r4, lr}", 0xE92D4010,
     dict(op=Op.STM, rn=13, pre=True, up=False, writeback=True, reglist=(4, 14))),
    ("ldm r0, {r1, r2}^", 0xE8D00006,
     dict(op=Op.LDM, user=True, writeback=False, reglist=(1, 2))),
    # ARMv4: when LDM loads its own base, the loaded value wins over writeback
    ("ldmia r0!, {r0, r1}", 0xE8B00003,
     dict(op=Op.LDM, rn=0, writeback=False, reglist=(0, 1))),
    ("stmia r0!, {r0, r1}", 0xE8A00003,
     dict(op=Op.STM, rn=0, writeback=True, reglist=(0, 1))),
]


@pytest.mark.parametrize("text,word,expected", CASES, ids=[case[0] for case in CASES])
def test_decode(text, word, expected):
    ins = decode_arm(word, BASE)
    assert {key: getattr(ins, key) for key in expected} == expected
    assert (ins.mode, ins.size, ins.raw, ins.addr) == (Mode.ARM, 4, word, BASE)


UNDEFINED = [
    ("NV condition", 0xF0000000),
    ("mcr (coprocessor)", 0xEE000010),
    ("ldc (coprocessor transfer)", 0xEC000000),
    ("clz (ARMv5)", 0xE16F0F11),
    ("blx reg (ARMv5)", 0xE12FFF31),
    ("ldrd (ARMv5TE)", 0xE1C000D0),
    ("media space (ARMv6)", 0xE6100010),
    ("movw (ARMv6T2)", 0xE3000000),
    ("unallocated multiply space", 0xE1600090),
    ("halfword post-index with W", 0xE0B100B2),
]


@pytest.mark.parametrize("name,word", UNDEFINED, ids=[case[0] for case in UNDEFINED])
def test_non_armv4t_encodings_are_undefined(name, word):
    assert decode_arm(word, BASE).op is Op.UNDEFINED


def test_decoder_is_total_over_random_words():
    rng = random.Random(1234)
    for _ in range(200_000):
        word = rng.getrandbits(32)
        ins = decode_arm(word, BASE)
        assert ins.size == 4 and ins.raw == word
