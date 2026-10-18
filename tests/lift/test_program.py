from progkit import program_space

from gbaport.analysis.cfg import build_program
from gbaport.analysis.discover import explore
from gbaport.isa.model import Mode
from gbaport.lift.program import lift_program, program_files, single_source

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


def test_program_files_split_the_code():
    program = lifted(TWO_FUNCTIONS, seeds=BOTH)
    files = program_files(program, chunk=1)
    assert sorted(files) == ["gba_code_000.c", "gba_code_001.c", "gba_dispatch.c", "gba_program.h"]
    assert '#include "gba_cpu.h"' in files["gba_program.h"]
    code = [text for name, text in files.items() if name.endswith(".c")]
    assert all(text.startswith('#include "gba_program.h"') for text in code)
    assert single_source(program).startswith('#include "gba_cpu.h"')
