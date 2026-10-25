import random

import pytest
from progkit import (
    ARM_TABLES,
    BYTE_TABLE,
    CODE_ADDR,
    CRT0,
    DMA_COPY,
    HALFWORD_TABLE,
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
    SWEEP,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
    explore_program,
    program_space,
)
from romkit import build_rom

from gbaport.analysis.config import GameConfig, JumpTableOverride
from gbaport.analysis.discover import RamCopy, explore
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.tables import JumpTable
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage


def kinds(ex):
    return [(issue.addr, issue.kind) for issue in ex.issues]


def test_crt0_entries_calls_and_literals():
    ex = explore_program(CRT0)
    assert ex.entry_kinds == {
        0x080000C0: "seed",
        0x080000E4: "irq",
        0x080000E8: "call",
        0x080000F6: "call",
    }
    assert ex.entries[0x080000E4] is Mode.ARM
    assert ex.entries[0x080000E8] is Mode.THUMB
    assert ex.calls == {0x080000D4: (0x080000E8,), 0x080000EA: (0x080000F6,)}
    assert ex.literals == {0x080000DC: 4, 0x080000E0: 4}
    assert ex.issues == []


def test_crt0_successors():
    ex = explore_program(CRT0)
    assert ex.successors[0x080000D4] == (0x080000D8,)  # the call returns to the next instruction
    assert ex.successors[0x080000D8] == (0x080000C0,)  # b start
    assert ex.successors[0x080000F4] == ()  # pop {r1}; bx r1 returns
    assert ex.successors[0x080000F8] == (0x080000FC, 0x080000FA)  # beq done


def test_veneer_call_resolves_the_function_pointer():
    ex = explore_program(VENEER, thumb=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000D0: "veneer", 0x080000D4: "call"}
    assert ex.calls == {0x080000C4: (0x080000D4,)}
    assert ex.issues == []


def test_thumb_jump_table():
    ex = explore_program(THUMB_TABLE, thumb=True)
    targets = (0x080000E0, 0x080000E2, 0x080000E4)
    assert ex.tables == [JumpTable(0x080000CC, 0x080000D4, Mode.THUMB, targets, data=True)]
    assert ex.successors[0x080000CC] == targets
    assert ex.successors[0x080000C2] == (0x080000E6, 0x080000C4)
    assert ex.literals == {0x080000D0: 4, 0x080000D4: 4, 0x080000D8: 4, 0x080000DC: 4}
    assert set(ex.instructions) >= {0x080000E0, 0x080000E2, 0x080000E4, 0x080000E6}
    assert ex.issues == []


def test_arm_jump_tables():
    ex = explore_program(ARM_TABLES)
    assert ex.tables == [
        JumpTable(0x080000C4, 0x080000CC, Mode.ARM, (0x080000D4, 0x080000D8), data=True),
        JumpTable(0x080000E0, 0x080000E8, Mode.ARM, (0x080000E8, 0x080000EC), data=False),
    ]
    assert ex.successors[0x080000C4] == (0x080000D4, 0x080000D8, 0x080000C8)
    assert ex.successors[0x080000E0] == (0x080000E8, 0x080000EC, 0x080000E4)
    assert ex.literals == {0x080000CC: 4, 0x080000D0: 4}
    assert ex.issues == []


def test_unknown_indirect_jump_is_reported():
    ex = explore_program("ldr r0, [r1]\nbx r0", thumb=True)
    assert kinds(ex) == [(0x080000C2, "unresolved_jump")]


def test_undefined_instruction_is_reported():
    ex = explore_program("movs r0, #1\n.hword 0xde00", thumb=True)
    assert kinds(ex) == [(0x080000C2, "undefined")]


def test_irq_handler_in_ram_becomes_a_hint():
    ex = explore_program(IRQ_IN_RAM)
    assert kinds(ex) == [(0x080000C8, "outside_code")]
    assert "irq" in ex.issues[0].detail and "[[ram_code]]" in ex.issues[0].detail


def test_unknown_call_through_the_link_idiom():
    ex = explore_program("mov lr, pc\nbx r2\nbx lr")
    assert kinds(ex) == [(0x080000C4, "unresolved_call")]
    assert ex.successors[0x080000C4] == (0x080000C8,)


def test_known_jump_leaves_the_function():
    ex = explore_program(KNOWN_JUMP, thumb=True)
    assert ex.entry_kinds[0x080000C8] == "jump"
    assert ex.jumps == {0x080000C2: 0x080000C8}
    assert ex.issues == []


def test_mode_conflict():
    seeds = [(0x080000C0, Mode.ARM, "seed"), (0x080000C4, Mode.THUMB, "seed")]
    ex = explore_program("b th\n.thumb\nth: bx lr", seeds=seeds)
    assert kinds(ex) == [(0x080000C4, "mode_conflict")]


def test_data_range_stops_the_walk():
    config = GameConfig(data=((0x080000C8, 0x080000CC),))
    ex = explore_program("b skip\n.word 0\nskip: bx lr", config=config)
    assert kinds(ex) == [(0x080000C8, "enters_data")]


def test_unbounded_table_and_its_override():
    ex = explore_program(UNBOUNDED_TABLE, thumb=True)
    assert kinds(ex) == [(0x080000C8, "unbounded_table")]
    config = GameConfig(jump_tables=(JumpTableOverride(0x080000C8, 0x080000D0, 2),))
    ex = explore_program(UNBOUNDED_TABLE, thumb=True, config=config)
    assert ex.issues == []
    assert ex.successors[0x080000C8] == (0x080000D8, 0x080000DA)


def test_loops_and_recursion_terminate():
    ex = explore_program(RECURSION, thumb=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000C6: "call"}
    assert ex.calls == {0x080000C0: (0x080000C6,), 0x080000C6: (0x080000C0,)}
    assert ex.successors[0x080000CC] == (0x080000CC,)  # spin: b spin


def test_garbage_never_crashes():
    rng = random.Random(7)
    for mode in (Mode.ARM, Mode.THUMB):
        for _ in range(25):
            data = bytearray(build_rom(size=0x1000))
            data[0xC0:] = rng.randbytes(0x1000 - 0xC0)
            explore(CodeSpace(RomImage(bytes(data))), [(CODE_ADDR, mode, "seed")])


def test_constants_do_not_flow_into_a_join_point():
    source = """
        ldr r0, pa
        cmp r1, #0
        beq L
        ldr r0, pb
    L:  bx r0
    .align 2
    pa: .word fa+1
    pb: .word fb+1
    fa: bx lr
    fb: bx lr
    """
    ex = explore_program(source, thumb=True)
    assert 0x080000C8 not in ex.jumps
    assert (0x080000C8, "unresolved_jump") in kinds(ex)


def test_constant_left_in_lr_becomes_an_entry():
    source = """
        ldr lr, p
        b h
    h:  bx lr
    p:  .word m+1
    .thumb
    m:  bx lr
    """
    ex = explore_program(source)
    assert ex.entry_kinds[0x080000D0] == "return"
    assert ex.entries[0x080000D0] is Mode.THUMB
    assert ex.issues == []


def test_lr_used_as_a_scratch_register_is_not_followed():
    source = """
        ldr lr, p
        ldr r0, [lr]
        b h
    h:  bx lr
    p:  .word m+1
    .thumb
    m:  bx lr
    """
    assert 0x080000D4 not in explore_program(source).entries


def test_lr_constant_outside_code_is_ignored():
    ex = explore_program("mov lr, #0x04000000\nb h\nh: bx lr")
    assert list(ex.entries) == [CODE_ADDR]
    assert ex.issues == []


# A call through a veneer whose register comes from memory.
#   c0 main   c4 bl via_r3   cc via_r3   d0 target (never reached statically)
UNKNOWN_VENEER = """
main:
    push {lr}
    ldr r3, [r0]
    bl via_r3
    pop {r0}
    bx r0
via_r3:
    bx r3
    mov r8, r8
target:
    bx lr
"""


def test_trace_resolves_a_call_through_a_veneer():
    assert (0x080000C4, "unresolved_call") in kinds(explore_program(UNKNOWN_VENEER, thumb=True))
    traced = {0x080000C4: ((0x080000D0, Mode.THUMB),)}
    ex = explore_program(UNKNOWN_VENEER, thumb=True, traced=traced)
    assert ex.calls[0x080000C4] == (0x080000D0,)
    assert ex.traced == {0x080000C4: (0x080000D0,)}
    assert ex.entry_kinds[0x080000D0] == "trace"
    assert ex.issues == []


def test_trace_resolves_an_indirect_jump_to_entries():
    source = "ldr r0, [r1]\nbx r0\nt1: bx lr\nt2: bx lr"
    traced = {0x080000C4: ((0x080000CC, Mode.ARM), (0x080000C8, Mode.ARM))}
    ex = explore_program(source, traced=traced)
    assert ex.traced == {0x080000C4: (0x080000C8, 0x080000CC)}
    assert ex.entry_kinds[0x080000C8] == ex.entry_kinds[0x080000CC] == "trace"
    assert ex.successors[0x080000C4] == ()
    assert ex.issues == []


def test_trace_gives_an_unbounded_switch_its_cases():
    traced = {0x080000C8: ((0x080000D8, Mode.THUMB), (0x080000DA, Mode.THUMB))}
    ex = explore_program(UNBOUNDED_TABLE, thumb=True, traced=traced)
    assert ex.successors[0x080000C8] == (0x080000D8, 0x080000DA)
    assert 0x080000D8 not in ex.entries
    assert ex.issues == []


def test_targets_of_unreached_traced_sites_become_entries():
    ex = explore_program("bx lr\nt: bx lr", traced={0x08000300: ((0x080000C4, Mode.ARM),)})
    assert ex.entry_kinds[0x080000C4] == "trace"


# Thumb main calls helper; extra is reachable only through a pointer.
#   c0 main   c2 bl helper (4 bytes)   ca helper   d0 extra
WITH_EXTRA = """
main:
    push {lr}
    bl helper
    pop {r0}
    bx r0
helper:
    push {lr}
    pop {r0}
    bx r0
extra:
    push {lr}
    pop {r0}
    bx r0
"""


def test_candidates_never_split_trusted_code():
    candidates = [
        (0x080000C4, Mode.THUMB, "pointer"),  # second half of the bl
        (0x080000CC, Mode.THUMB, "pointer"),  # inside helper
        (0x080000D0, Mode.THUMB, "pointer"),
    ]
    ex = explore_program(WITH_EXTRA, thumb=True, candidates=candidates)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000CA: "call", 0x080000D0: "pointer"}
    assert ex.issues == []


def test_candidates_never_land_in_data():
    source = "ldr r0, lit\nbx lr\nlit: .word 0"
    ex = explore_program(source, candidates=[(0x080000C8, Mode.ARM, "pointer")])
    assert 0x080000C8 not in ex.entries


@pytest.mark.parametrize(
    "control,size",
    [
        ("0x84000002", 8),  # 2 words, 32-bit units
        ("0x80000004", 8),  # 4 halfwords
        ("0x85000002", None),  # fixed source: a fill, not a copy
        ("0x94000002", None),  # starts at VBlank, not now
        ("0x04000002", None),  # not enabled
    ],
)
def test_dma_copies_with_known_operands(control, size):
    ex = explore_program(DMA_COPY.replace("0x84000002", control))
    expected = [] if size is None else [RamCopy(0x080000D8, 0x08000200, 0x03000000, size)]
    assert ex.copies == expected
    assert ex.outside == {0x03000004: Mode.ARM}


def test_dma_control_built_with_orr_and_a_conditional_store():
    # The start-up code shape of real games: count >> 2 | flags, stored if the count is not 0.
    source = DMA_COPY.replace(
        "    ldr r1, cnt\n    str r1, [r0, #0xdc]\n",
        "    ldr r1, cnt\n    movs r1, r1, lsr #2\n    orr r1, r1, #0x84000000\n"
        "    strne r1, [r0, #0xdc]\n",
    ).replace("0x84000002", "8")
    ex = explore_program(source)
    assert ex.copies == [RamCopy(0x080000E0, 0x08000200, 0x03000000, 8)]


def test_dma_registers_written_with_stmia():
    source = """
        ldr r0, regs
        ldr r1, src
        ldr r2, dst
        ldr r3, cnt
        stmia r0!, {r1, r2, r3}
        bx lr
    .align 2
    regs: .word 0x040000d4
    src: .word 0x08000200
    dst: .word 0x02000000
    cnt: .word 0x84000010
    """
    ex = explore_program(source, thumb=True)
    assert ex.copies == [RamCopy(0x080000C8, 0x08000200, 0x02000000, 64)]


@pytest.mark.parametrize(
    "swi,control,size",
    [
        ("0xb", "0x04000010", 64),  # CpuSet, 16 words
        ("0xb", "0x00000010", 32),  # CpuSet, 16 halfwords
        ("0xc", "0x00000009", 64),  # CpuFastSet rounds up to 8-word blocks
        ("0xb", "0x05000010", None),  # CpuSet fill
    ],
)
def test_bios_copies_with_known_operands(swi, control, size):
    source = f"""
        ldr r0, src
        ldr r1, dst
        ldr r2, ctl
        svc #{swi}
        bx lr
    .align 2
    src: .word 0x08000200
    dst: .word 0x02000000
    ctl: .word {control}
    """
    ex = explore_program(source, thumb=True)
    expected = [] if size is None else [RamCopy(0x080000C6, 0x08000200, 0x02000000, size)]
    assert ex.copies == expected


# Trusted code loads func's address and jumps to it; a wrong guess (cand)
# branches into the middle, between the load and the jump.
#   c0 main   c2 mid (bx r0)   c4 lit   c8 func   ca cand   cc its beq mid
GUESS_INTO_TRUSTED = """
main:
    ldr r0, lit
mid:
    bx r0
.align 2
lit: .word func+1
func:
    bx lr
cand:
    push {lr}
    beq mid
    pop {r0}
    bx r0
"""


def test_a_wrong_guess_cannot_change_trusted_results():
    candidates = [(0x080000CA, Mode.THUMB, "pointer")]
    ex = explore_program(GUESS_INTO_TRUSTED, thumb=True, candidates=candidates)
    assert ex.jumps == {0x080000C2: 0x080000C8}
    assert 0x080000CA not in ex.entries
    assert ex.issues == []


def test_the_sweep_finds_code_that_only_code_before_it_leads_to():
    assert explore_program(SWEEP, thumb=True).entry_kinds == {0x080000C0: "seed"}
    ex = explore(program_space(SWEEP, thumb=True), [(0x080000C0, Mode.THUMB, "seed")], sweep=True)
    assert ex.entry_kinds == {0x080000C0: "seed", 0x080000CA: "neighbour", 0x080000CE: "neighbour"}
    assert ex.entries[0x080000CA] is Mode.THUMB
    assert ex.calls == {0x080000D0: (0x080000CA,)}
    assert ex.issues == []


def test_the_sweep_tries_thumb_code_after_arm_code():
    space = program_space("bx lr\n.thumb\nnext:\n movs r0, #1\n bx lr")
    ex = explore(space, [(0x080000C0, Mode.ARM, "seed")], sweep=True)
    assert ex.entries == {0x080000C0: Mode.ARM, 0x080000C4: Mode.THUMB}
    assert ex.issues == []


def test_the_sweep_leaves_what_is_not_code_alone():
    space = program_space("bx lr\n.hword 0xde00\n.hword 0xde00", thumb=True)
    ex = explore(space, [(0x080000C0, Mode.THUMB, "seed")], sweep=True)
    assert ex.entries == {0x080000C0: Mode.THUMB}
    assert sorted(ex.instructions) == [0x080000C0]  # and the zeros after it, to the ROM's end
    assert ex.issues == []


def test_the_sweep_never_reads_a_switch_table_as_code():
    ex = explore(program_space(HALFWORD_TABLE, thumb=True), [(0x080000C0, Mode.THUMB, "seed")],
                 sweep=True)
    assert ex.entries == {0x080000C0: Mode.THUMB}
    assert not any(0x080000D0 <= addr < 0x080000D6 for addr in ex.instructions)


def test_a_guess_that_decodes_garbage_is_undone():
    source = "bx lr\ncand:\n push {lr}\n movs r0, r0\n .hword 0xde00\n"
    ex = explore_program(source, thumb=True, candidates=[(0x080000C2, Mode.THUMB, "pointer")])
    assert ex.entries == {0x080000C0: Mode.THUMB}
    assert sorted(ex.instructions) == [0x080000C0]
    assert ex.issues == []


def test_byte_table_rows_are_one_byte_literals():
    ex = explore_program(BYTE_TABLE, thumb=True)
    assert ex.successors[0x080000CA] == (0x080000D0, 0x080000D2, 0x080000D4)
    assert [ex.literals.get(a) for a in (0x080000CC, 0x080000CD, 0x080000CE)] == [1, 1, 1]
    assert ex.issues == []


def test_halfword_table_rows_are_two_byte_literals():
    ex = explore_program(HALFWORD_TABLE, thumb=True)
    assert ex.successors[0x080000CC] == (0x080000D6, 0x080000D8, 0x080000DA)
    assert [ex.literals.get(a) for a in (0x080000D0, 0x080000D2, 0x080000D4)] == [2, 2, 2]
    assert ex.issues == []


def test_traced_targets_of_a_pc_relative_jump_are_cases():
    source = "ldr r3, [r1]\nadd pc, r3\nc0: bx lr\nc1: bx lr"
    traced = {0x080000C2: ((0x080000C4, Mode.THUMB), (0x080000C6, Mode.THUMB))}
    ex = explore_program(source, thumb=True, traced=traced)
    assert ex.successors[0x080000C2] == (0x080000C4, 0x080000C6)
    assert 0x080000C4 not in ex.entries


# A library routine with a second entry point that trusted code never calls.
#   c0 main   ca lib   cc alt (inside lib)   d0 cand calls alt
SECOND_ENTRY = """
main:
    push {lr}
    bl lib
    pop {r0}
    bx r0
lib:
    movs r0, #0
alt:
    adds r0, #1
    bx lr
cand:
    push {lr}
    bl alt
    pop {r0}
    bx r0
"""


def test_a_guess_may_call_into_code_found_before_it():
    ex = explore_program(SECOND_ENTRY, thumb=True, candidates=[(0x080000D0, Mode.THUMB, "pointer")])
    assert ex.entry_kinds[0x080000D0] == "pointer"
    assert ex.entry_kinds[0x080000CC] == "call"


def test_a_guess_with_debug_output_is_kept():
    source = "bx lr\ncand:\n push {lr}\n svc #0xab\n pop {r0}\n bx r0\n"
    ex = explore_program(source, thumb=True, candidates=[(0x080000C2, Mode.THUMB, "pointer")])
    assert ex.entry_kinds[0x080000C2] == "pointer"


def test_a_guess_may_tail_branch_into_code_found_before_it():
    source = SECOND_ENTRY.replace("    bl alt\n    pop {r0}\n    bx r0\n", "    pop {r0}\n    b alt\n")
    ex = explore_program(source, thumb=True, candidates=[(0x080000D0, Mode.THUMB, "pointer")])
    assert ex.entry_kinds[0x080000D0] == "pointer"


def test_a_guess_may_call_library_code_that_shares_tails():
    source = SECOND_ENTRY.replace(
        "    bl alt\n    pop {r0}\n    bx r0\n",
        "    bl lib2\n    pop {r0}\n    bx r0\nlib2:\n    cmp r0, #0\n    beq alt\n    bx lr\n",
    )
    ex = explore_program(source, thumb=True, candidates=[(0x080000D0, Mode.THUMB, "pointer")])
    assert ex.entry_kinds[0x080000D0] == "pointer"
    assert ex.entry_kinds[0x080000DA] == "call"
