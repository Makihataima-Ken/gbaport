import pytest

from gbaport.isa.model import Cond, Mode, Op, Shift, ShiftKind
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000

# (text, halfword, next halfword, address, expected fields)
CASES = [
    ("lsls r0, r1, #2", 0x0088, None, BASE,
     dict(thumb_format=1, op=Op.MOV, s=True, rd=0, rm=1, shift=Shift(ShiftKind.LSL, 2))),
    ("lsrs r0, r1, #32", 0x0808, None, BASE, dict(op=Op.MOV, shift=Shift(ShiftKind.LSR, 32))),
    ("lsls r0, r1, #0", 0x0008, None, BASE, dict(op=Op.MOV, rm=1, shift=None)),
    ("adds r0, r1, r2", 0x1888, None, BASE,
     dict(thumb_format=2, op=Op.ADD, s=True, rd=0, rn=1, rm=2, imm=None)),
    ("subs r0, r1, #3", 0x1EC8, None, BASE, dict(op=Op.SUB, rd=0, rn=1, imm=3, rm=None)),
    ("movs r0, #5", 0x2005, None, BASE,
     dict(thumb_format=3, op=Op.MOV, s=True, rd=0, rn=None, imm=5)),
    ("cmp r0, #5", 0x2805, None, BASE, dict(op=Op.CMP, s=True, rd=None, rn=0, imm=5)),
    ("adds r0, #200", 0x30C8, None, BASE, dict(op=Op.ADD, rd=0, rn=0, imm=200)),
    ("ands r0, r1", 0x4008, None, BASE,
     dict(thumb_format=4, op=Op.AND, s=True, rd=0, rn=0, rm=1)),
    ("rors r0, r1", 0x41C8, None, BASE,
     dict(op=Op.MOV, s=True, rd=0, rm=0, shift=Shift(ShiftKind.ROR, reg=1))),
    ("negs r0, r1", 0x4248, None, BASE, dict(op=Op.RSB, s=True, rd=0, rn=1, imm=0)),
    ("muls r0, r1, r0", 0x4348, None, BASE, dict(op=Op.MUL, s=True, rd=0, rm=1, rs=0)),
    ("tst r0, r1", 0x4208, None, BASE, dict(op=Op.TST, s=True, rd=None, rn=0, rm=1)),
    ("add r0, r8", 0x4440, None, BASE,
     dict(thumb_format=5, op=Op.ADD, s=False, rd=0, rn=0, rm=8)),
    ("mov r8, r0", 0x4680, None, BASE, dict(op=Op.MOV, s=False, rd=8, rm=0)),
    ("cmp r0, r8", 0x4540, None, BASE, dict(op=Op.CMP, s=True, rn=0, rm=8)),
    ("mov pc, lr", 0x46F7, None, BASE, dict(op=Op.MOV, rd=15, rm=14)),
    ("bx r0", 0x4700, None, BASE, dict(op=Op.BX, rm=0)),
    ("ldr r0, [pc, #8] @ 0x08000002", 0x4802, None, BASE + 2,
     dict(thumb_format=6, op=Op.LDR, rd=0, rn=15, imm=8, target=0x0800000C)),
    ("str r0, [r1, r2]", 0x5088, None, BASE,
     dict(thumb_format=7, op=Op.STR, rd=0, rn=1, rm=2)),
    ("ldrsb r0, [r1, r2]", 0x5688, None, BASE,
     dict(thumb_format=8, op=Op.LDRSB, rd=0, rn=1, rm=2)),
    ("ldrb r0, [r1, #3]", 0x78C8, None, BASE,
     dict(thumb_format=9, op=Op.LDRB, rd=0, rn=1, imm=3)),
    ("ldr r0, [r1, #124]", 0x6FC8, None, BASE, dict(op=Op.LDR, imm=124)),
    ("ldrh r0, [r1, #2]", 0x8848, None, BASE,
     dict(thumb_format=10, op=Op.LDRH, rd=0, rn=1, imm=2)),
    ("str r0, [sp, #4]", 0x9001, None, BASE,
     dict(thumb_format=11, op=Op.STR, rd=0, rn=13, imm=4)),
    ("add r0, sp, #8", 0xA802, None, BASE,
     dict(thumb_format=12, op=Op.ADD, rd=0, rn=13, imm=8, target=None)),
    ("adr r0, #8 @ 0x08000002", 0xA002, None, BASE + 2,
     dict(op=Op.ADD, rd=0, rn=15, imm=8, target=0x0800000C)),
    ("sub sp, #8", 0xB082, None, BASE,
     dict(thumb_format=13, op=Op.SUB, rd=13, rn=13, imm=8)),
    ("push {r4, lr}", 0xB510, None, BASE,
     dict(thumb_format=14, op=Op.STM, rn=13, pre=True, up=False, writeback=True,
          reglist=(4, 14))),
    ("pop {r4, pc}", 0xBD10, None, BASE,
     dict(op=Op.LDM, rn=13, pre=False, up=True, writeback=True, reglist=(4, 15))),
    ("ldmia r0!, {r1, r2}", 0xC806, None, BASE,
     dict(thumb_format=15, op=Op.LDM, rn=0, pre=False, writeback=True, reglist=(1, 2))),
    ("ldm r0, {r0, r1}", 0xC803, None, BASE, dict(op=Op.LDM, writeback=False, reglist=(0, 1))),
    ("beq #0x08000010", 0xD006, None, BASE,
     dict(thumb_format=16, op=Op.B, cond=Cond.EQ, target=0x08000010)),
    ("bne #0x07ffffe0", 0xD1EE, None, BASE, dict(op=Op.B, cond=Cond.NE, target=0x07FFFFE0)),
    ("svc #5", 0xDF05, None, BASE, dict(thumb_format=17, op=Op.SWI, imm=5)),
    ("b #0x08000020", 0xE00E, None, BASE, dict(thumb_format=18, op=Op.B, target=0x08000020)),
    ("bl #0x08000100", 0xF000, 0xF87E, BASE,
     dict(thumb_format=19, op=Op.BL, size=4, raw=0xF87EF000, target=0x08000100)),
    ("bl #0x07ff0000", 0xF7EF, 0xFFFE, BASE, dict(op=Op.BL, size=4, target=0x07FF0000)),
    ("lone BL prefix", 0xF000, None, BASE, dict(op=Op.BL_HI, size=2, imm=0)),
    ("BL prefix before non-suffix", 0xF000, 0x2005, BASE, dict(op=Op.BL_HI, size=2)),
    ("lone BL suffix", 0xF87E, None, BASE, dict(op=Op.BL_LO, size=2, imm=0xFC)),
]


@pytest.mark.parametrize("text,hw,nxt,addr,expected", CASES, ids=[case[0] for case in CASES])
def test_decode(text, hw, nxt, addr, expected):
    ins = decode_thumb(hw, addr, nxt)
    assert {key: getattr(ins, key) for key in expected} == expected
    assert ins.mode is Mode.THUMB and ins.addr == addr


UNDEFINED = [
    ("cond 1110 branch", 0xDE00),
    ("BLX suffix (ARMv5)", 0xE800),
    ("sxth (ARMv6)", 0xB200),
    ("bkpt (ARMv5)", 0xBE00),
    ("blx reg (ARMv5)", 0x4780),
]


@pytest.mark.parametrize("name,hw", UNDEFINED, ids=[case[0] for case in UNDEFINED])
def test_non_armv4t_encodings_are_undefined(name, hw):
    assert decode_thumb(hw, BASE).op is Op.UNDEFINED


def test_decoder_is_total_over_every_halfword():
    for hw in range(0x10000):
        ins = decode_thumb(hw, BASE)
        assert ins.size == 2 and ins.raw == hw and ins.mode is Mode.THUMB
