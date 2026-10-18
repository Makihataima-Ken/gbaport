"""Differential tests: whole snippet programs with branches, calls, returns and switches."""

import random

import pytest
from liftkit import IWRAM, assert_same, random_case, run_lifted, run_oracle

ARM_LOOP = """
    mov r0, #0
    and r1, r1, #15
loop:
    add r0, r0, r1
    subs r1, r1, #1
    bgt loop
"""

THUMB_CALLS = """
    movs r0, #5
    bl double
    bl double
    b stop
double:
    lsls r0, r0, #1
    bx lr
"""

ARM_TO_THUMB = """
    ldr r2, fnptr
    mov r0, #3
    mov lr, pc
    bx r2
    add r0, r0, #100
    b stop
fnptr: .word thumb_fn+1
.thumb
thumb_fn:
    adds r0, r0, #7
    bx lr
"""

RECURSION = """
    and r0, r0, #7
    add r0, r0, #1
    bl fact
    b stop
fact:
    cmp r0, #1
    movle r0, #1
    bxle lr
    push {r0, lr}
    sub r0, r0, #1
    bl fact
    pop {r1, lr}
    mul r0, r1, r0
    bx lr
"""

ARM_SWITCH = """
    and r0, r0, #3
    cmp r0, #2
    ldrls pc, [pc, r0, lsl #2]
    b dflt
    .word c0, c1, c2
c0: mov r1, #10
    b stop
c1: mov r1, #11
    b stop
c2: mov r1, #12
    b stop
dflt:
    mov r1, #99
"""

ARM_BRANCH_TABLE = """
    and r0, r0, #3
    cmp r0, #2
    addls pc, pc, r0, lsl #2
    b dflt
    b c0
    b c1
    b c2
c0: mov r1, #20
    b stop
c1: mov r1, #21
    b stop
c2: mov r1, #22
    b stop
dflt:
    mov r1, #77
"""

THUMB_SWITCH = """
    movs r1, #3
    ands r0, r1
    cmp r0, #2
    bhi dflt
    lsls r0, r0, #2
    ldr r1, tabaddr
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
.align 2
tabaddr: .word tab
tab: .word c0, c1, c2
c0: movs r2, #30
    b stop
c1: movs r2, #31
    b stop
c2: movs r2, #32
    b stop
dflt:
    movs r2, #88
"""

THUMB_BYTE_TABLE = """
    movs r1, #3
    ands r0, r1
    cmp r0, #2
    bhi dflt
    adr r3, tbl
    ldrb r3, [r3, r0]
    lsls r3, r3, #1
    add pc, r3
.align 2
tbl: .byte 1, 3, 5
.align 1
c0: movs r2, #40
    b stop
c1: movs r2, #41
    b stop
c2: movs r2, #42
    b stop
dflt:
    movs r2, #66
"""

TAIL_CALL = """
    mov r0, #1
    bl g
    bl f
    b stop
f:
    add r0, r0, #1
    b g
g:
    add r0, r0, #10
    bx lr
"""

VENEER = """
    ldr r3, fptr
    movs r0, #1
    bl via_r3
    adds r0, #5
    b stop
.align 2
fptr: .word target+1
via_r3:
    bx r3
    nop
target:
    lsls r0, r0, #3
    bx lr
"""

CONDITIONAL_RETURN = """
    mov r0, #0
    and r1, r1, #7
    bl f
    b stop
f:
    cmp r1, #4
    addlt r0, r0, #1
    bxlt lr
    add r0, r0, #2
    moveq r0, #50
    bx lr
"""

THUMB_POP_PC = """
    movs r0, #2
    bl f
    adds r0, #1
    b stop
f:
    push {r4, lr}
    movs r4, #3
    adds r0, r0, r4
    pop {r4, pc}
"""

ARM_POP_PC = """
    mov r0, #4
    bl f
    add r0, r0, #1
    b stop
f:
    push {r4, lr}
    mov r4, #6
    add r0, r0, r4
    pop {r4, pc}
"""

# Thumb calls ARM code through a veneer; MRS there must show ARM state (T clear).
THUMB_TO_ARM = """
    adr r0, armfn
    movs r2, #1
    bl via_r0
    adds r2, #1
    b stop
via_r0:
    bx r0
.align 2
.arm
armfn:
    mrs r1, cpsr
    bx lr
"""

# Start-up code that sets LR itself before jumping (BT4E's crt0): init "returns" into main.
EXPLICIT_LR = """
    ldr lr, retptr
    mov r0, #1
    b init
retptr: .word main
init:
    add r0, r0, #2
    bx lr
main:
    add r0, r0, #10
"""

PROGRAMS = [
    (ARM_LOOP, False), (THUMB_CALLS, True), (ARM_TO_THUMB, False), (RECURSION, False),
    (ARM_SWITCH, False), (ARM_BRANCH_TABLE, False), (THUMB_SWITCH, True),
    (THUMB_BYTE_TABLE, True), (TAIL_CALL, False), (VENEER, True), (CONDITIONAL_RETURN, False),
    (THUMB_POP_PC, True), (ARM_POP_PC, False), (THUMB_TO_ARM, True), (EXPLICIT_LR, False),
]


def test_programs_match_unicorn():
    rng = random.Random(21)
    cases = []
    for source, thumb in PROGRAMS:
        for _ in range(8):
            case = random_case(rng, source, thumb=thumb)
            case.regs[13] = IWRAM + 0xC00  # a stack for the calls
            cases.append(case)
    assert_same(cases)


def test_an_endless_loop_hands_control_to_the_scheduler():
    rng = random.Random(22)
    case = random_case(rng, "loop:\n    add r0, r0, #1\n    b loop")
    lifted, oracle = run_lifted([case])[0], run_oracle([case])[0]
    assert lifted.status == oracle.status == "runaway"


@pytest.mark.parametrize("source,status", [
    (".word 0xe7f000f0", "undefined"),  # an undefined instruction
    ("ldr r0, ptr\n    bx r0\nptr: .word 0x08000400", "missing"),  # no code was found there
])
def test_unrecoverable_paths_reach_the_runtime(source, status):
    assert run_lifted([random_case(random.Random(23), source)])[0].status == status
