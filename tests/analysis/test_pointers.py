from ksasm import assemble
from progkit import program_rom, program_space

from gbaport.analysis.config import RamCode
from gbaport.analysis.pointers import pointer_candidates
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode

# A table of code pointers next to functions of every shape.
#   c4..d8 the table   dc arm_cb   e4 apcs_cb   ec cb (Thumb)   f2 plain   f4 garbage
POINTERS = """
main:
    bx lr
callbacks:
    .word cb+1
    .word plain+1
    .word garbage+1
    .word arm_cb
    .word apcs_cb
    .word main+2
arm_cb:
    push {r4, lr}
    pop {r4, pc}
apcs_cb:
    mov r12, sp
    bx lr
.thumb
cb:
    push {lr}
    pop {r0}
    bx r0
plain:
    bx lr
garbage:
    push {lr}
    .hword 0xde00
"""


def test_pointers_to_prologues_that_decode_cleanly():
    assert pointer_candidates(program_space(POINTERS)) == [
        (0x080000DC, Mode.ARM, "pointer"),
        (0x080000E4, Mode.ARM, "pointer"),
        (0x080000EC, Mode.THUMB, "pointer"),
    ]


def test_pointers_into_ram_code():
    blob = assemble("push {r4, lr}\npop {r4, pc}", addr=0x03000000)
    rom = program_rom(".word 0x03000000", patches={0x200: blob})
    space = CodeSpace(rom, (RamCode(0x08000200, 0x03000000, len(blob), Mode.ARM),))
    assert pointer_candidates(space) == [(0x03000000, Mode.ARM, "pointer")]


def test_no_pointers_no_candidates():
    assert pointer_candidates(program_space("bx lr")) == []
