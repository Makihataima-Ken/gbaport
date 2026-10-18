"""Differential tests: data processing, shifts and flags, lifted versus Unicorn."""

import random

from liftkit import assert_same, interesting, random_case

THREE_OPERAND = ["and", "eor", "sub", "rsb", "add", "adc", "sbc", "rsc", "orr", "bic"]
COMPARES = ["tst", "teq", "cmp", "cmn"]
MOVES = ["mov", "mvn"]
CONDS = ["", "eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le"]
SHIFT_RANGES = {"lsl": range(1, 32), "lsr": range(1, 33), "asr": range(1, 33), "ror": range(1, 32)}


def rotated_immediate(rng: random.Random) -> int:
    byte, rotation = rng.randrange(256), rng.choice([0, 0, 2, 4, 8, 16, 24, 30])
    return ((byte >> rotation) | (byte << (32 - rotation))) & 0xFFFFFFFF if rotation else byte


def operand2(rng: random.Random, register_shift: bool = True) -> str:
    form = rng.randrange(5 if register_shift else 4)
    if form == 0:
        return f"#{rotated_immediate(rng):#x}"
    if form == 1:
        return "r2"
    if form == 2:
        kind = rng.choice(list(SHIFT_RANGES))
        return f"r2, {kind} #{rng.choice(SHIFT_RANGES[kind])}"
    if form == 3:
        return "r2, rrx"
    return f"r2, {rng.choice(list(SHIFT_RANGES))} r3"


def arm_instruction(rng: random.Random) -> str:
    cond = rng.choice(CONDS)
    group = rng.randrange(3)
    if group == 0:
        op, s = rng.choice(THREE_OPERAND), rng.choice(["", "s"])
        rd, rn = rng.choice([("r0", "r1"), ("r1", "r1"), ("r0", "pc")])
        # pc with a register-specified shift is unpredictable after ARMv4: no oracle for it
        return f"{op}{s}{cond} {rd}, {rn}, {operand2(rng, register_shift=rn != 'pc')}"
    if group == 1:
        return f"{rng.choice(MOVES)}{rng.choice(['', 's'])}{cond} r0, {operand2(rng)}"
    return f"{rng.choice(COMPARES)}{cond} r1, {operand2(rng)}"


def with_shift_amounts(rng: random.Random, case):
    # r3 holds register shift amounts: favour 0, 31, 32, 33 and values above 255.
    case.regs[3] = rng.choice([0, 1, 31, 32, 33, 64, 255, 256, 257, interesting(rng)])
    return case


def test_arm_data_processing():
    rng = random.Random(2024)
    cases = [
        with_shift_amounts(rng, random_case(rng, arm_instruction(rng))) for _ in range(500)
    ]
    assert_same(cases)


THUMB = [
    "lsls r0, r1, #{n}", "lsrs r0, r1, #{n1}", "asrs r0, r1, #{n1}",
    "adds r0, r1, r2", "subs r0, r1, r2", "adds r0, r1, #{i3}", "subs r0, r1, #{i3}",
    "movs r0, #{i8}", "cmp r0, #{i8}", "adds r0, #{i8}", "subs r0, #{i8}",
    "ands r0, r1", "eors r0, r1", "lsls r0, r3", "lsrs r0, r3", "asrs r0, r3", "adcs r0, r1",
    "sbcs r0, r1", "rors r0, r3", "tst r0, r1", "rsbs r0, r1, #0", "cmp r0, r1", "cmn r0, r1",
    "orrs r0, r1", "bics r0, r1", "mvns r0, r1",
    "add r0, r8", "add r8, r1", "cmp r0, r9", "cmp r9, r1", "mov r9, r2", "mov r0, r10",
    "add r0, pc", "mov r1, pc", "add r0, sp, #{i8x4}", "add sp, #{i7x4}", "sub sp, #{i7x4}",
]


def test_thumb_alu():
    rng = random.Random(7)
    cases = []
    for _ in range(300):
        text = rng.choice(THUMB).format(
            n=rng.randrange(32), n1=rng.randrange(1, 33), i3=rng.randrange(8),
            i8=rng.randrange(256), i8x4=rng.randrange(256) * 4, i7x4=rng.randrange(128) * 4,
        )
        cases.append(with_shift_amounts(rng, random_case(rng, text, thumb=True)))
    assert_same(cases)
