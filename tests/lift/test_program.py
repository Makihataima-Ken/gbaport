from ksasm import assemble
from progkit import CRT0, program_rom, program_space

from gbaport.analysis.cfg import build_program
from gbaport.analysis.discover import explore
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.lift import function
from gbaport.lift.program import lift_program, program_files, single_source
from gbaport.lift.semantics import LiftError

# Two functions without calls, both given as seeds.   c0 first   c8 second
TWO_FUNCTIONS = """
first:
    mov r0, #1
    b first
second:
    mov r1, #2
    b second
"""
BOTH = (0x080000C0, 0x080000C8)


def lifted(source: str, *, seeds=(0x080000C0,), thumb: bool = False, prefix: str = ""):
    mode = Mode.THUMB if thumb else Mode.ARM
    ex = explore(program_space(source, thumb=thumb), [(addr, mode, "seed") for addr in seeds])
    return lift_program(build_program(ex), ex, prefix=prefix)


def test_every_function_gets_a_prototype_and_a_sorted_dispatch_row():
    program = lifted(TWO_FUNCTIONS, seeds=BOTH[::-1])
    assert list(program.functions) == list(BOTH)
    for entry in BOTH:
        assert f"uint32_t f_{entry:08x}(GbaCtx *ctx);" in program.prototypes
    rows = [line for line in program.dispatch.splitlines() if line.strip().startswith("{0x")]
    assert rows == [f"    {{0x{e:08x}u, f_{e:08x}}}," for e in BOTH]
    assert "GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr)" in program.dispatch


def test_prefix_keeps_programs_apart():
    program = lifted(TWO_FUNCTIONS, prefix="c7_")
    assert program.lookup_name == "c7_gba_lookup"
    assert "uint32_t c7_f_080000c0(GbaCtx *ctx)" in program.functions[0x080000C0]


def test_each_code_file_holds_8_kib_of_code_and_declares_what_it_uses():
    calls_first = assemble("mov r1, #2\nbl 0x080000c0\nb 0x08002000", addr=0x08002000)
    rom = program_rom("mov r0, #1\nbx lr", size=0x4000, patches={0x2000: calls_first})
    ex = explore(CodeSpace(rom), [(0x080000C0, Mode.ARM, "seed"), (0x08002000, Mode.ARM, "seed")])
    files = program_files(lift_program(build_program(ex), ex))
    assert sorted(files) == ["gba_code_08000000.c", "gba_code_08002000.c", "gba_dispatch.c"]
    first, second = files["gba_code_08000000.c"], files["gba_code_08002000.c"]
    assert all(text.startswith('#include "gba_cpu.h"') for text in files.values())
    assert "uint32_t f_080000c0(GbaCtx *ctx);" in first and "f_08002000" not in first
    assert "uint32_t f_080000c0(GbaCtx *ctx);" in second  # it calls the first
    assert "GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);" in second
    for entry in (0x080000C0, 0x08002000):
        assert f"uint32_t f_{entry:08x}(GbaCtx *ctx);" in files["gba_dispatch.c"]
    assert single_source(lifted(TWO_FUNCTIONS, seeds=BOTH)).startswith('#include "gba_cpu.h"')


def test_an_instruction_c_cannot_express_is_reported(monkeypatch):
    effects = function.lift_effects

    def refuse_the_first(ins):  # every instruction has C now: pretend the first does not
        if ins.addr == 0x080000C0:
            raise LiftError(f"{ins.addr:#010x}: no effects for {ins.op.value}")
        return effects(ins)

    monkeypatch.setattr(function, "lift_effects", refuse_the_first)
    program = lifted("mov r0, #1\nbx lr")
    assert program.problems == ("0x080000c0: no effects for mov",)
    assert "gba_undefined(ctx, 0x080000c0u);" in program.functions[0x080000C0]


def test_calls_to_recompiled_functions_are_direct():
    code = lifted(CRT0).functions[0x080000E8]  # Thumb main calls helper with bl
    assert "gba_call_direct(ctx, f_080000f6, 0x080000efu);" in code


def test_exits_carry_the_state_execution_continues_in():
    thumb = lifted("push {lr}\n    pop {pc}", thumb=True).functions[0x080000C0]
    assert "t |= 1u;" in thumb  # pop {pc} stays in Thumb state: bit 0 says so
    arm = lifted("ldr pc, [sp], #4").functions[0x080000C0]
    assert "t &= ~3u;" in arm
    dispatch = lifted(TWO_FUNCTIONS).dispatch
    assert "uint32_t key = addr & ~1u;" in dispatch
    assert "return gba_missing(ctx, addr);" in dispatch  # the runtime sees the state bit
