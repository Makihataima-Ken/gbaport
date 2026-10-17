import random

from progkit import (
    ARM_TABLES,
    CODE_ADDR,
    CRT0,
    IRQ_IN_RAM,
    KNOWN_JUMP,
    RECURSION,
    THUMB_TABLE,
    UNBOUNDED_TABLE,
    VENEER,
    explore_program,
)
from romkit import build_rom

from gbaport.analysis.config import GameConfig, JumpTableOverride
from gbaport.analysis.discover import explore
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
