from progkit import ARM_TABLES, CRT0, KNOWN_JUMP, TAIL_CALLS, explore_program

from gbaport.analysis.cfg import build_program
from gbaport.isa.model import Mode


def test_crt0_blocks():
    program = build_program(explore_program(CRT0))
    assert sorted(program.blocks) == [
        0x080000C0, 0x080000E4, 0x080000E8, 0x080000F6, 0x080000FA, 0x080000FC,
    ]
    start = program.blocks[0x080000C0]
    assert (start.end, start.successors, len(start.instructions)) == (0x080000DC, (0x080000C0,), 7)
    assert program.blocks[0x080000E8].end == 0x080000F6
    assert program.blocks[0x080000F6].successors == (0x080000FC, 0x080000FA)
    assert program.blocks[0x080000FA].successors == (0x080000FC,)


def test_crt0_functions():
    program = build_program(explore_program(CRT0))
    summary = {
        entry: (f.kind, f.mode, f.blocks, f.calls) for entry, f in program.functions.items()
    }
    assert summary == {
        0x080000C0: ("seed", Mode.ARM, (0x080000C0,), (0x080000E8,)),
        0x080000E4: ("irq", Mode.ARM, (0x080000E4,), ()),
        0x080000E8: ("call", Mode.THUMB, (0x080000E8,), (0x080000F6,)),
        0x080000F6: ("call", Mode.THUMB, (0x080000F6, 0x080000FA, 0x080000FC), ()),
    }


def test_jump_table_blocks_belong_to_the_function():
    program = build_program(explore_program(ARM_TABLES))
    assert program.blocks[0x080000C0].successors == (0x080000D4, 0x080000D8, 0x080000C8)
    assert program.functions[0x080000C0].blocks == (
        0x080000C0, 0x080000C8, 0x080000D4, 0x080000D8, 0x080000DC,
        0x080000E4, 0x080000E8, 0x080000EC, 0x080000F0,
    )


def test_branch_into_another_function_is_a_tail_call():
    seeds = [(0x080000C0, Mode.THUMB, "seed"), (0x080000CA, Mode.THUMB, "seed")]
    program = build_program(explore_program(TAIL_CALLS, thumb=True, seeds=seeds))
    f = program.functions[0x080000CA]
    assert (f.blocks, f.tail_calls) == ((0x080000CA,), (0x080000CC,))
    assert program.functions[0x080000C0].calls == (0x080000CC,)


def test_known_jump_is_a_tail_call():
    program = build_program(explore_program(KNOWN_JUMP, thumb=True))
    assert program.functions[0x080000C0].tail_calls == (0x080000C8,)
    assert program.functions[0x080000C8].kind == "jump"
