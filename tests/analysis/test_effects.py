import pytest
from progkit import decode_one, decode_program, program_space

from gbaport.analysis.effects import RegState, interwork_target, pc_value, written_registers
from gbaport.isa.model import Mode


def run_states(source: str, count: int, *, thumb: bool = False) -> RegState:
    space = program_space(source, thumb=thumb)
    state = RegState()
    for ins in decode_program(space, count, thumb=thumb):
        state.step(ins, space)
    return state


@pytest.mark.parametrize(
    "text,thumb,expected",
    [
        ("adds r0, r1, r2", True, {0}),
        ("cmp r0, #1", True, set()),
        ("ldr r0, [r1], #4", False, {0, 1}),
        ("str r0, [r1, #4]!", False, {1}),
        ("pop {r4, pc}", True, {4, 13}),
        ("push {r4, lr}", True, {13}),
        ("umull r0, r1, r2, r3", False, {0, 1}),
        ("bl #0x08000100", True, {14}),
        ("svc #1", True, {0, 1, 2, 3, 12}),
        ("mov pc, lr", True, set()),
    ],
)
def test_written_registers(text, thumb, expected):
    assert written_registers(decode_one(text, thumb=thumb)) == expected


def test_pc_value_and_interworking():
    assert pc_value(decode_one("bx lr")) == 0x080000C8
    assert pc_value(decode_one("bx lr", thumb=True)) == 0x080000C4
    assert interwork_target(0x08000201) == (0x08000200, Mode.THUMB)
    assert interwork_target(0x08000202) == (0x08000200, Mode.ARM)


def test_literal_load_is_constant():
    state = run_states("ldr r0, lit\nbx lr\nlit: .word 0x12345678", 1)
    assert state.consts == {0: 0x12345678}


def test_thumb_adr_moves_shifts_and_adds():
    source = (
        "adr r0, here\nmovs r1, #1\nlsls r1, r1, #26\nadds r2, r1, #4\nmov r3, r2\n"
        "bx lr\n.align 2\nhere: .word 0"
    )
    state = run_states(source, 5, thumb=True)
    assert state.consts == {0: 0x080000CC, 1: 0x04000000, 2: 0x04000004, 3: 0x04000004}


def test_arm_add_pc_reads_address_plus_8():
    assert run_states("add r0, pc, #4\nbx lr", 1).consts == {0: 0x080000CC}


def test_unknown_operands_and_overwrites_forget_constants():
    source = "movs r0, #1\nldr r0, [r1]\nmovs r2, #3\nadds r2, r2, r4\nbx lr"
    assert run_states(source, 4, thumb=True).consts == {}


def test_conditional_write_forgets_register():
    assert run_states("mov r0, #1\nmoveq r0, #2\nbx lr", 2).consts == {}


def test_pops_are_remembered_until_overwritten():
    state = run_states("push {r4, lr}\npop {r4}\npop {r1}\nbx r1", 3, thumb=True)
    assert state.popped == {1, 4}
    state = run_states("pop {r1}\nmovs r1, #0\nbx lr", 2, thumb=True)
    assert state.popped == frozenset()


def test_call_forgets_caller_saved_registers():
    state = RegState(consts={0: 1, 4: 2, 12: 3, 14: 4}, popped=frozenset({0, 5}))
    state.forget_call_clobbered()
    assert state.consts == {4: 2}
    assert state.popped == {5}
