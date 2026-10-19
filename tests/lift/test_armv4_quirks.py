"""ARMv4 behaviours Unicorn's ARMv5 core does differently, checked against the ARM7TDMI's
rules directly (jsmolka's arm.gba and thumb.gba test them too: test_public_roms.py)."""

import struct

from liftkit import EWRAM, Case, run_lifted
from progkit import CODE_ADDR

FIQ, SYS = 0xD1, 0x1F


def test_a_compare_with_rd_15_copies_spsr_to_cpsr_and_does_not_jump():
    source = (
        "msr cpsr_c, #0xd1\n"         # FIQ mode, which banks r8
        "mov r8, #64\n"
        "msr spsr_fsxc, #0x1f\n"      # SPSR: system mode, flags clear
        ".word 0xe15ff000\n"          # cmp pc, r0 with Rd = 15 (the old cmpp)
        "mov r0, r8\n"                # runs next, in system mode: its own r8
    )
    case = Case(source, flags=0xF0000000)
    case.regs[8] = 32
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    assert out.cpsr & 0xFF == SYS and out.cpsr >> 28 == 0  # SPSR's mode and flags
    assert out.regs[0] == 32


def test_tst_teq_and_cmn_with_rd_15_restore_cpsr_too():
    for word in (0xE11FF000, 0xE13FF000, 0xE17FF000):  # tst, teq, cmn pc, r0 with Rd = 15
        case = Case(f"msr cpsr_c, #0xd1\nmsr spsr_fsxc, #0x1f\n.word {word:#x}\n")
        out = run_lifted([case])[0]
        assert out.status == "stopped"
        assert out.cpsr & 0xFF == SYS


def stm_empty(word: int) -> tuple[int, bytes]:
    """Runs an ARM STM with an empty register list on r0 = EWRAM + 0x200."""
    case = Case(f".word {word:#x}\n")
    case.regs[0] = EWRAM + 0x200
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    return out.regs[0], out.ewram


def test_an_empty_register_list_stores_r15_and_moves_the_base_by_0x40():
    stored = struct.pack("<I", CODE_ADDR + 12)  # the stm's own address + 12
    for word, base, at in (
        (0xE8A00000, 0x240, 0x200),  # stmia r0!, {}
        (0xE9A00000, 0x240, 0x204),  # stmib r0!, {}
        (0xE8200000, 0x1C0, 0x1C4),  # stmda r0!, {}: where r0-r15 would start
        (0xE9200000, 0x1C0, 0x1C0),  # stmdb r0!, {}
    ):
        r0, ram = stm_empty(word)
        assert r0 == EWRAM + base, hex(word)
        assert ram[at : at + 4] == stored, hex(word)


def test_an_ldm_with_an_empty_register_list_loads_r15_and_moves_the_base_by_0x40():
    source = (
        "adr r1, after\n"
        "str r1, [r0]\n"
        ".word 0xe8b00000\n"  # ldmia r0!, {}: jumps to after
        "mov r2, #1\n"        # skipped
        "after:\n"
        "mov r3, #2\n"
    )
    case = Case(source, entries=(CODE_ADDR + 16,))  # after: only the loaded pc leads there
    case.regs[0] = EWRAM + 0x200
    out = run_lifted([case])[0]
    assert out.status == "stopped"
    assert (out.regs[0], out.regs[2], out.regs[3]) == (EWRAM + 0x240, 0, 2)
