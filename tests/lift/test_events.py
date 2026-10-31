"""Recompiled code and the interpreter check for due events at the same instructions.

Both follow one rule, so a piece of a game's code checks (and takes interrupts) at the
same moments wherever it runs: at every taken branch back to an address at or before
the branch, and at every jump through a register that is not a call. Every loop has one
of those, so a loop still lets the scheduler run.
"""

import random

import pytest
from liftkit import IWRAM, lift_cases, random_case, run_compiled, run_interpreted

LOOP_AT_ENTRY = """
    mov r0, #3
    bl count
    b stop
count:
    subs r0, r0, #1
    bne count
    bx lr
"""

FALL_INTO_LOOP = """
    mov r0, #3
loop:
    subs r0, r0, #1
    bne loop
"""

TAIL_BRANCH_AND_TABLE = """
    bl g
    bl f
    and r2, r0, #1
    cmp r2, #1
    ldrls pc, [pc, r2, lsl #2]
    b stop
    .word one, stop
one:
    add r0, r0, #4
    b stop
f:
    mov r1, #1
    b g
g:
    add r0, r0, #1
    bx lr
"""

THUMB_LOOP_AT_ENTRY = """
    movs r0, #3
    bl count
    b stop
count:
    subs r0, #1
    bne count
    bx lr
"""

THUMB_TAIL_BRANCH = """
    bl g
    bl f
    b stop
f:
    movs r1, #1
    b g
g:
    adds r0, #1
    bx lr
"""

PROGRAMS = [  # a called function whose entry is a loop, a loop reached by falling into it,
    # a forward tail branch into another function and a jump through a table, then in Thumb
    (LOOP_AT_ENTRY, False), (FALL_INTO_LOOP, False), (TAIL_BRANCH_AND_TABLE, False),
    (THUMB_LOOP_AT_ENTRY, True), (THUMB_TAIL_BRANCH, True),
]


@pytest.mark.parametrize("source, thumb", PROGRAMS)
def test_recompiled_and_interpreted_code_check_for_events_at_the_same_places(source, thumb):
    rng = random.Random(41)
    cases = []
    for _ in range(4):
        case = random_case(rng, source, thumb=thumb)
        case.regs[13] = IWRAM + 0xC00  # a stack for the calls
        cases.append(case)
    recompiled = run_compiled(lift_cases(cases), cases)
    interpreted = run_interpreted(cases)
    assert [o.status for o in recompiled] == [o.status for o in interpreted] == ["stopped"] * 4
    assert [o.checks for o in recompiled] == [o.checks for o in interpreted]
