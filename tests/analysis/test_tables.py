from progkit import ARM_TABLES, THUMB_TABLE, UNBOUNDED_TABLE, decode_program, program_space

from gbaport.analysis.config import JumpTableOverride
from gbaport.analysis.effects import RegState
from gbaport.analysis.tables import JumpTable, Step, TableMatch, find_jump_table
from gbaport.isa.model import Mode


def dispatch_after(space, count, *, thumb, start=0x080000C0):
    """Run ``count`` instructions; return the next one and the history before it."""
    listing = decode_program(space, count + 1, thumb=thumb, start=start)
    state, history = RegState(), []
    for ins in listing[:-1]:
        history.append(Step(ins, dict(state.consts)))
        state.step(ins, space)
    return listing[-1], history


def test_thumb_switch_table():
    space = program_space(THUMB_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 6, thumb=True)
    targets = (0x080000E0, 0x080000E2, 0x080000E4)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000CC, 0x080000D4, Mode.THUMB, targets, data=True)
    )


def test_arm_ldr_pc_table():
    space = program_space(ARM_TABLES)
    dispatch, history = dispatch_after(space, 1, thumb=False)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000C4, 0x080000CC, Mode.ARM, (0x080000D4, 0x080000D8), data=True)
    )


def test_arm_branch_table():
    space = program_space(ARM_TABLES)
    dispatch, history = dispatch_after(space, 1, thumb=False, start=0x080000DC)
    assert find_jump_table(dispatch, history, space, {}) == TableMatch(
        JumpTable(0x080000E0, 0x080000E8, Mode.ARM, (0x080000E8, 0x080000EC), data=False)
    )


def test_missing_bound_is_reported_not_guessed():
    space = program_space(UNBOUNDED_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 4, thumb=True)
    match = find_jump_table(dispatch, history, space, {})
    assert match.table is None
    assert "{ at = 0x080000c8, table = 0x080000d0, count = N }" in match.problem


def test_override_supplies_table_and_count():
    space = program_space(UNBOUNDED_TABLE, thumb=True)
    dispatch, history = dispatch_after(space, 4, thumb=True)
    overrides = {0x080000C8: JumpTableOverride(0x080000C8, 0x080000D0, 2)}
    match = find_jump_table(dispatch, history, space, overrides)
    assert match.table.targets == (0x080000D8, 0x080000DA)


def test_unrecognised_indirect_jump():
    space = program_space("ldr r0, [r1]\nmov pc, r0", thumb=True)
    dispatch, history = dispatch_after(space, 1, thumb=True)
    assert find_jump_table(dispatch, history, space, {}) is None


def test_table_rows_stop_at_rom_end():
    source = THUMB_TABLE.replace("cmp r0, #2", "cmp r0, #200")
    space = program_space(source, thumb=True, size=0x100)
    dispatch, history = dispatch_after(space, 6, thumb=True)
    match = find_jump_table(dispatch, history, space, {})
    assert len(match.table.targets) == (0x100 - 0xD4) // 4
