"""Differential tests: multiplies, loads and stores, block transfers, SWP and PSR access.

Unicorn is an ARMv5 core, so misaligned accesses (where the ARM7TDMI rotates or
truncates) are checked against the ARM7TDMI rules directly instead.
"""

import random
import struct

from liftkit import EWRAM, IWRAM, Case, assert_same, random_case, run_lifted

CONDS = ["", "eq", "ne", "cs", "cc", "mi", "pl", "hi", "ls", "ge", "lt"]


def aligned_base(rng: random.Random, region: int = EWRAM) -> int:
    return region + rng.randrange(0x200, 0xE00, 4)


def test_multiplies():
    rng = random.Random(11)
    templates = [
        "mul{s}{c} r0, r1, r2", "mla{s}{c} r0, r1, r2, r3", "umull{s}{c} r0, r4, r1, r2",
        "umlal{s}{c} r0, r4, r1, r2", "smull{s}{c} r0, r4, r1, r2", "smlal{s}{c} r0, r4, r1, r2",
    ]
    cases = [
        random_case(rng, rng.choice(templates).format(s=rng.choice(["", "s"]), c=rng.choice(CONDS)))
        for _ in range(150)
    ]
    cases += [random_case(rng, "muls r0, r1, r0", thumb=True) for _ in range(20)]
    assert_same(cases, ignore_cv=True)  # the ARM7TDMI leaves C (and V) meaningless


def arm_transfer(rng: random.Random) -> tuple[str, int]:
    """An ARM load or store with an aligned address, and the value for r2 (the index)."""
    op, size = rng.choice([("ldr", 4), ("str", 4), ("ldrb", 1), ("strb", 1), ("ldrh", 2),
                           ("strh", 2), ("ldrsb", 1), ("ldrsh", 2)])
    cond = rng.choice(CONDS)
    imm = rng.randrange(-0x40, 0x40) * size
    index = rng.randrange(-16, 16) * size
    sign = "-" if imm < 0 else ""
    forms = [f"[r1, #{sign}{abs(imm)}]", f"[r1, #{sign}{abs(imm)}]!", f"[r1], #{sign}{abs(imm)}",
             "[r1, r2]", "[r1, -r2]", "[r1, r2]!", "[r1], r2"]
    if size == 4 or op in ("ldrb", "strb"):
        forms += ["[r1, r2, lsl #2]", "[r1, r2, asr #1]"]
        index = rng.randrange(-16, 16) * 8  # keeps r2 >> 1 word-aligned too
    return f"{op}{cond} r0, {rng.choice(forms)}", index & 0xFFFFFFFF


def test_arm_loads_and_stores():
    rng = random.Random(12)
    cases = []
    for _ in range(300):
        text, index = arm_transfer(rng)
        case = random_case(rng, text)
        case.regs[1] = aligned_base(rng, rng.choice([EWRAM, IWRAM]))
        case.regs[2] = index
        cases.append(case)
    cases.append(random_case(rng, "ldr r0, [pc]"))  # reads the word after the stop svc
    assert_same(cases)


THUMB_TRANSFERS = [
    "ldr r0, [r1, r2]", "str r0, [r1, r2]", "ldrb r0, [r1, r2]", "strb r0, [r1, r2]",
    "ldrh r0, [r1, r2]", "strh r0, [r1, r2]", "ldrsb r0, [r1, r2]", "ldrsh r0, [r1, r2]",
    "ldr r0, [r1, #{w}]", "str r0, [r1, #{w}]", "ldrb r0, [r1, #{b}]", "strb r0, [r1, #{b}]",
    "ldrh r0, [r1, #{h}]", "strh r0, [r1, #{h}]", "ldr r0, [sp, #{sp}]", "str r0, [sp, #{sp}]",
    "ldr r0, [pc, #4]", "push {{r0, r4, lr}}", "pop {{r2, r5}}", "ldmia r1!, {{r0, r2, r3}}",
    "stmia r1!, {{r0, r2, r3}}", "ldm r1, {{r1, r2}}",
]  # str.format templates: {{ }} are literal braces


def test_thumb_loads_and_stores():
    rng = random.Random(13)
    cases = []
    for _ in range(250):
        text = rng.choice(THUMB_TRANSFERS).format(
            w=rng.randrange(32) * 4, b=rng.randrange(32), h=rng.randrange(32) * 2,
            sp=rng.randrange(256) * 4,
        )
        case = random_case(rng, text, thumb=True)
        case.regs[1] = aligned_base(rng)
        case.regs[2] = rng.randrange(0, 64) * 4
        case.regs[13] = IWRAM + rng.randrange(0x100, 0xB00, 4)
        cases.append(case)
    assert_same(cases)


def reglist(rng: random.Random, exclude: int) -> str:
    regs = sorted(rng.sample([r for r in range(13) if r != exclude], rng.randint(1, 6)))
    return "{" + ", ".join(f"r{r}" for r in regs) + "}"


def test_block_transfers():
    rng = random.Random(14)
    cases = []
    for _ in range(200):
        op = rng.choice(["ldm", "stm"]) + rng.choice(["ia", "ib", "da", "db"]) + rng.choice(CONDS)
        text = f"{op} r1{rng.choice(['', '!'])}, {reglist(rng, exclude=1)}"
        case = random_case(rng, text)
        case.regs[1] = EWRAM + rng.randrange(0x400, 0xC00, 4)
        cases.append(case)
    for text in ["stmia r1!, {r1, r4, r7}", "ldmia r1, {r0, r1, r2}", "push {r4-r11, lr}",
                 "pop {r4-r11}", "stmdb sp!, {r0-r3}", "ldmfd sp!, {r0, r1}"]:
        for _ in range(5):
            case = random_case(rng, text)
            case.regs[1] = EWRAM + rng.randrange(0x400, 0xC00, 4)
            case.regs[13] = IWRAM + rng.randrange(0x400, 0xC00, 4)
            cases.append(case)
    assert_same(cases)


def test_swaps():
    rng = random.Random(15)
    cases = []
    for text in ["swp r0, r2, [r1]", "swpb r0, r2, [r1]", "swp r0, r0, [r1]", "swpbne r3, r2, [r1]"]:
        for _ in range(10):
            case = random_case(rng, text)
            case.regs[1] = aligned_base(rng)
            cases.append(case)
    assert_same(cases)


def test_psr_transfers_and_banked_registers():
    rng = random.Random(16)
    snippets = [
        "mrs r0, cpsr",
        "msr cpsr_f, #0xa0000000\nmrs r0, cpsr",
        "msr cpsr_f, r2\nmrs r0, cpsr",
        "msr cpsr_fc, r2",  # r2 holds a system-mode control field (below)
        # IRQ mode has its own r13, r14 and SPSR; system mode gets its own back.
        (
            "msr cpsr_c, #0xd2\nmov r13, r2\nmov r14, r3\nmsr spsr_f, r2\nmrs r4, spsr\n"
            "msr cpsr_c, #0x1f\nmov r0, r13\nmov r1, r14\nmsr cpsr_c, #0xd2\nmov r5, r13"
        ),
        # FIQ banks r8-r12 as well.
        "msr cpsr_c, #0xd1\nmov r8, #1\nmov r12, #2\nmsr cpsr_c, #0x1f\nmov r0, r8\nmov r1, r12",
        # STM/LDM with ^ in IRQ mode move the user registers.
        "msr cpsr_c, #0xd2\nstmia r0, {r13, r14}^\nldmia r0, {r8, r9}\nmsr cpsr_c, #0x1f",
        "msr cpsr_c, #0xd2\nldmia r0, {r13, r14}^\nmsr cpsr_c, #0x1f",
    ]
    cases = []
    for text in snippets:
        for _ in range(6):
            case = random_case(rng, text)
            case.regs[0] = aligned_base(rng)
            case.regs[2] = (case.regs[2] & 0xF0000000) | 0xDF  # flags + SYS mode, I and F set
            cases.append(case)
    assert_same(cases)


# ---- ARM7TDMI misalignment (Unicorn's ARMv5 core does these differently) ------------


def word_at(ram: bytes, offset: int) -> int:
    return struct.unpack_from("<I", ram, offset)[0]


def misaligned(source: str, offset: int, **regs) -> tuple[Case, object]:
    ram = bytes(range(256)) * 16
    case = Case(source, regs=[0] * 15, ewram=ram)
    case.regs[1] = EWRAM + offset
    for name, value in regs.items():
        case.regs[int(name[1:])] = value
    return case, run_lifted([case])[0]


def ror(value: int, amount: int) -> int:
    return ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF if amount else value


def test_misaligned_ldr_rotates_the_word():
    for offset in (0x101, 0x102, 0x103):
        _, out = misaligned("ldr r0, [r1]", offset)
        assert out.regs[0] == ror(word_at(bytes(range(256)) * 16, 0x100), 8 * (offset & 3))


def test_misaligned_ldrh_rotates_and_ldrsh_loads_a_byte():
    _, out = misaligned("ldrh r0, [r1]", 0x181)
    assert out.regs[0] == ror(0x8180, 8)
    _, out = misaligned("ldrsh r0, [r1]", 0x181)
    assert out.regs[0] == 0xFFFFFF81  # the sign-extended byte at 0x181
    _, out = misaligned("ldrsh r0, [r1]", 0x180)
    assert out.regs[0] == 0xFFFF8180


def test_misaligned_stores_and_block_transfers_align_down():
    _, out = misaligned("str r0, [r1]", 0x102, r0=0xAABBCCDD)
    assert word_at(out.ewram, 0x100) == 0xAABBCCDD
    _, out = misaligned("strh r0, [r1]", 0x105, r0=0xAABBCCDD)
    assert out.ewram[0x104:0x106] == bytes([0xDD, 0xCC])
    _, out = misaligned("ldmia r1, {r0, r2}", 0x103)
    ram = bytes(range(256)) * 16
    assert (out.regs[0], out.regs[2]) == (word_at(ram, 0x100), word_at(ram, 0x104))


def test_misaligned_swp_rotates_the_loaded_word():
    _, out = misaligned("swp r0, r2, [r1]", 0x102, r2=0x11223344)
    ram = bytes(range(256)) * 16
    assert out.regs[0] == ror(word_at(ram, 0x100), 16)
    assert word_at(out.ewram, 0x100) == 0x11223344
