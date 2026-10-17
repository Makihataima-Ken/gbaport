import pytest
from progkit import decode_one, program_space
from romkit import build_rom

from gbaport.analysis.effects import RegState
from gbaport.analysis.flow import Flow, FlowKind, classify
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage

EMPTY = CodeSpace(RomImage(build_rom()))
THUMB, ARM = Mode.THUMB, Mode.ARM


def flow(text, *, thumb=False, consts=None, popped=(), prev=None, space=EMPTY):
    state = RegState(consts=dict(consts or {}), popped=frozenset(popped))
    previous = None if prev is None else decode_one(prev, thumb=thumb)
    return classify(decode_one(text, thumb=thumb), state, previous, space)


@pytest.mark.parametrize(
    "text,thumb,expected",
    [
        ("adds r0, #1", True, Flow(FlowKind.NEXT)),
        ("svc #5", True, Flow(FlowKind.NEXT)),
        ("svc #0", True, Flow(FlowKind.STOP)),
        ("svc #0x260000", False, Flow(FlowKind.STOP)),
        (".hword 0xde00", True, Flow(FlowKind.STOP)),
        ("b #0x08000100", True, Flow(FlowKind.BRANCH, (0x08000100, THUMB))),
        ("beq #0x08000100", True, Flow(FlowKind.BRANCH, (0x08000100, THUMB), True)),
        ("bl #0x08000100", True, Flow(FlowKind.CALL, (0x08000100, THUMB), True)),
        (".hword 0xf87e", True, Flow(FlowKind.CALL, None, True)),
        ("bx lr", True, Flow(FlowKind.RETURN)),
        ("bxeq lr", False, Flow(FlowKind.RETURN, falls_through=True)),
        ("pop {r4, pc}", True, Flow(FlowKind.RETURN)),
        ("ldmfd sp!, {r4, pc}", False, Flow(FlowKind.RETURN)),
        ("subs pc, lr, #4", False, Flow(FlowKind.RETURN)),
        ("ldr pc, [sp], #4", False, Flow(FlowKind.RETURN)),
        ("mov pc, lr", True, Flow(FlowKind.RETURN)),
        ("bx r0", True, Flow(FlowKind.INDIRECT)),
        ("mov pc, r0", True, Flow(FlowKind.INDIRECT)),
        ("add pc, pc, r0, lsl #2", False, Flow(FlowKind.INDIRECT)),
        ("addls pc, pc, r0, lsl #2", False, Flow(FlowKind.INDIRECT, falls_through=True)),
    ],
)
def test_classify(text, thumb, expected):
    assert flow(text, thumb=thumb) == expected


def test_bx_to_popped_register_returns():
    assert flow("bx r1", thumb=True, popped={1}) == Flow(FlowKind.RETURN)


def test_bx_to_known_value_jumps_with_interworking():
    to_thumb = flow("bx r0", thumb=True, consts={0: 0x08000201})
    to_arm = flow("bx r0", thumb=True, consts={0: 0x08000200})
    assert to_thumb == Flow(FlowKind.JUMP, (0x08000200, THUMB))
    assert to_arm == Flow(FlowKind.JUMP, (0x08000200, ARM))


def test_bx_pc_switches_to_arm():
    assert flow("bx pc", thumb=True) == Flow(FlowKind.JUMP, (0x080000C4, ARM))


def test_link_idiom_turns_a_jump_into_a_call():
    called = flow("bx r1", consts={1: 0x080000E9}, prev="mov lr, pc")
    assert called == Flow(FlowKind.CALL, (0x080000E8, THUMB), falls_through=True)
    assert flow("bx r2", prev="mov lr, pc") == Flow(FlowKind.CALL, None, falls_through=True)


def test_ldr_pc_from_literal_jumps_without_interworking():
    space = program_space("ldr pc, lit\nlit: .word 0x08000201")
    assert flow("ldr pc, [pc, #-4]", space=space) == Flow(FlowKind.JUMP, (0x08000200, ARM))
