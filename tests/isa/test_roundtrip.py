"""Assemble -> decode -> format -> re-assemble must reproduce the original bytes.

Every corpus entry is canonical assembler output, so a mismatch means the
decoder or the formatter lost information.
"""

import pytest
from ksasm import assemble

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Op
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000

ARM_CORPUS = [
    "add r0, r1, r2, lsl #3", "addseq r0, r1, r2", "mov r0, #0xff000000", "mov r0, r1, lsl r2",
    "movs r0, r1, lsr #32", "mov r0, r1, asr #32", "mov r0, r1, rrx", "tst r0, r1, lsl #3",
    "teq r0, #1", "cmp r0, r1, rrx", "mvns r0, #0", "rsc r0, r1, r2, ror r3", "movs pc, lr",
    "mulseq r0, r1, r2", "mla r0, r1, r2, r3", "umull r0, r1, r2, r3", "smlals r0, r1, r2, r3",
    "umullseq r0, r1, r2, r3", "swp r0, r1, [r2]", "swpbeq r0, r1, [r2]",
    "ldr r0, [r1, r2, lsl #2]", "str r0, [r1], -r2, asr #3", "ldr r0, [r1, -r2, ror #4]!",
    "ldr r0, [r1], r2", "ldr r0, [r1, #-4]!", "ldr r0, [r1, #-0]", "ldrbteq r0, [r1], #4",
    "ldrt r0, [r1], -r2", "ldrbeq r0, [r1]", "ldr r0, [pc, #8]", "str r0, [r1, #0]",
    "ldrh r0, [r1, #2]", "ldrheq r0, [r1]", "ldrsbne r0, [r1]", "ldrsb r0, [r1, -r2]!",
    "ldrh r0, [r1, -r2]!", "ldrsh r0, [r1], #-4", "strh r0, [r1], #-6", "ldrsh r0, [r1]",
    "ldmfd sp!, {r4-r7, pc}", "stmdb sp!, {r4, lr}", "ldmib r0, {r1}", "stmda r0!, {r1}",
    "ldmda r0, {r1, pc}^", "ldm r0, {r1, r2}^", "ldmiaeq r0, {r1}",
    "b #0x08000100", "beq #0x07fffff8", "blne #0x08100000", "bl #0x08000100", "bx lr",
    "bxeq lr", "svc #0x50000", "svceq #0x123456",
    "mrs r0, cpsr", "mrsne r0, cpsr", "mrs r0, spsr", "msr cpsr_fc, r0", "msr cpsr_fsxc, r0",
    "msr cpsr_c, r0", "msr spsr_fc, r0", "msr cpsr_f, #0xf0000000", "msr spsr_fsxc, #0x1f",
]

THUMB_CORPUS = [
    "adds r0, r1, r2", "subs r0, r1, #3", "adds r0, r1, #0", "lsls r0, r1, #2", "lsls r0, r1, #0",
    "lsrs r0, r1, #32", "asrs r0, r1, #32", "movs r0, #5", "cmp r0, #5", "adds r0, #200",
    "ands r0, r1", "eors r0, r1", "adcs r0, r1", "sbcs r0, r1", "rors r0, r1", "lsls r0, r1",
    "tst r0, r1", "negs r0, r1", "cmn r0, r1", "orrs r0, r1", "muls r0, r1, r0", "bics r0, r1",
    "mvns r0, r1", "add r0, r8", "mov r8, r0", "cmp r0, r8", "add r8, r9", "cmp r8, r9",
    "mov pc, lr", "add pc, r0", "bx r0", "bx pc", "ldr r0, [pc, #8]", "ldr r0, [pc, #1020]",
    "str r0, [r1, r2]", "ldrb r0, [r1, r2]", "strh r0, [r1, r2]", "ldrsh r0, [r1, r2]",
    "ldrsb r0, [r1, r2]", "ldrh r0, [r1, #2]", "ldrb r0, [r1, #3]", "ldrb r0, [r1, #31]",
    "ldr r0, [r1, #124]", "strh r0, [r1, #62]", "str r0, [sp, #4]", "ldr r0, [sp, #1020]",
    "add r0, sp, #8", "add r0, sp, #1020", "adr r0, #8", "adr r0, #1020", "add sp, #8",
    "sub sp, #8", "add sp, #508", "sub sp, #508", "push {r4, lr}", "pop {r4, pc}", "push {lr}",
    "pop {pc}", "push {r0-r7, lr}", "ldmia r0!, {r1, r2}", "stmia r0!, {r1, r2}",
    "ldm r0, {r0, r1}", "beq #0x08000010", "bne #0x07ffffe0", "b #0x08000020",
    "b #0x08000400", "svc #5", "svc #255", "bl #0x08000100", "bl #0x07ff0000",
]


@pytest.mark.parametrize("text", ARM_CORPUS)
def test_arm_roundtrip(text):
    code = assemble(text, addr=BASE)
    assert len(code) == 4
    ins = decode_arm(int.from_bytes(code, "little"), BASE)
    assert ins.op is not Op.UNDEFINED
    rendered = format_instruction(ins)
    assert assemble(rendered, addr=BASE) == code, f"{text!r} rendered as {rendered!r}"


@pytest.mark.parametrize("text", THUMB_CORPUS)
def test_thumb_roundtrip(text):
    code = assemble(text, thumb=True, addr=BASE)
    assert len(code) in (2, 4), f"Keystone chose a Thumb-2 encoding for {text!r}"
    nxt = int.from_bytes(code[2:4], "little") if len(code) == 4 else None
    ins = decode_thumb(int.from_bytes(code[0:2], "little"), BASE, nxt)
    assert ins.op is not Op.UNDEFINED and ins.size == len(code)
    rendered = format_instruction(ins)
    assert assemble(rendered, thumb=True, addr=BASE) == code, f"{text!r} rendered as {rendered!r}"
