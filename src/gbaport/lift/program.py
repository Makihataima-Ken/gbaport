"""Lift a whole analysed program: functions, their prototypes and the dispatch table.

The dispatch table maps each recompiled function's address to its C function;
``gba_find`` (prefixed in tests, so several programs can share one binary)
finds the function for an address with a binary search, or NULL, also when bit 0
asks for the other CPU state than the function was recompiled in; ``gba_lookup`` hands anything it does not find to the
runtime's ``gba_missing``, bit 0 included, which runs it in the interpreter.
"""

import re
from dataclasses import dataclass

from gbaport.analysis.cfg import Program
from gbaport.analysis.discover import Exploration
from gbaport.isa.model import Mode
from gbaport.lift.function import function_name, lift_function

HEADER = "gba_cpu.h"
BUCKET = 0x2000  # bytes of guest code per generated .c file


@dataclass(frozen=True)
class LiftedProgram:
    prefix: str
    prototypes: str  # a declaration for every function
    functions: dict[int, str]  # entry address -> C definition
    dispatch: str  # the sorted table and the lookup function
    problems: tuple[str, ...] = ()  # instructions lifted as undefined because C cannot express them

    @property
    def lookup_name(self) -> str:
        return f"{self.prefix}gba_lookup"


def lift_program(program: Program, ex: Exploration, prefix: str = "") -> LiftedProgram:
    entries = sorted(program.functions)
    prototypes = "".join(f"uint32_t {function_name(a, prefix)}(GbaCtx *ctx);\n" for a in entries)
    prototypes += f"GbaFn {prefix}gba_find(GbaCtx *ctx, uint32_t addr);\n"
    prototypes += f"GbaFn {prefix}gba_lookup(GbaCtx *ctx, uint32_t addr);\n"
    problems: list[str] = []
    functions = {
        a: lift_function(program.functions[a], program, ex, prefix, problems) for a in entries
    }
    unique = tuple(dict.fromkeys(problems))  # a block shared by several functions reports once
    thumb = [program.functions[a].mode is Mode.THUMB for a in entries]
    return LiftedProgram(prefix, prototypes, functions, _dispatch(entries, thumb, prefix), unique)


def single_source(lifted: LiftedProgram) -> str:
    """One C file holding the whole program (it includes gba_cpu.h)."""
    parts = [f'#include "{HEADER}"\n', lifted.prototypes, *lifted.functions.values()]
    return "\n".join([*parts, lifted.dispatch])


def program_files(lifted: LiftedProgram) -> dict[str, str]:
    """The generated sources by file name: the code files and the dispatch table.

    Functions go into files by address, one file per BUCKET bytes of guest code (named
    after the bucket's address), each declaring only the functions it uses, so finding one
    more function changes its file and the dispatch table: a rebuild compiles only those.
    The dispatch table declares every function."""
    files: dict[str, str] = {}
    buckets: dict[int, list[str]] = {}
    for addr, body in lifted.functions.items():
        buckets.setdefault(addr & ~(BUCKET - 1), []).append(body)
    name = re.compile(rf"\b{re.escape(lifted.prefix)}f_[0-9a-f]{{8}}\b")
    for start, bodies in sorted(buckets.items()):
        text = "\n".join(bodies)
        used = sorted(set(name.findall(text)))
        declarations = "".join(f"uint32_t {n}(GbaCtx *ctx);\n" for n in used)
        declarations += f"GbaFn {lifted.lookup_name}(GbaCtx *ctx, uint32_t addr);\n"
        files[f"gba_code_{start:08x}.c"] = f'#include "{HEADER}"\n\n{declarations}\n{text}'
    files["gba_dispatch.c"] = f'#include "{HEADER}"\n\n{lifted.prototypes}\n{lifted.dispatch}'
    return files


def _dispatch(entries: list[int], thumb: list[bool], prefix: str) -> str:
    lines = []
    if entries:
        lines.append(f"static const struct {{ uint32_t addr, thumb; GbaFn fn; }} {prefix}table[] = {{")
        lines += [f"    {{0x{a:08x}u, {int(t)}, {function_name(a, prefix)}}},"
                  for a, t in zip(entries, thumb, strict=True)]
        lines.append("};")
    lines += [
        "",
        f"GbaFn {prefix}gba_find(GbaCtx *ctx, uint32_t addr)",
        "{",
        "    uint32_t key = addr & ~1u;",
        "    (void)ctx;",
    ]
    if entries:
        lines += [
            f"    uint32_t lo = 0, hi = {len(entries)};",
            "    while (lo < hi) {",
            "        uint32_t mid = (lo + hi) / 2;",
            f"        uint32_t found = {prefix}table[mid].addr;",
            "        if (found == key)  /* in the other state it is code that was not recompiled */",
            f"            return {prefix}table[mid].thumb == (addr & 1u) ? {prefix}table[mid].fn : 0;",
            "        if (found < key)",
            "            lo = mid + 1;",
            "        else",
            "            hi = mid;",
            "    }",
        ]
    lines += [
        "    return 0;",
        "}",
        "",
        f"GbaFn {prefix}gba_lookup(GbaCtx *ctx, uint32_t addr)",
        "{",
        f"    GbaFn fn = {prefix}gba_find(ctx, addr);",
        "    return fn ? fn : gba_missing(ctx, addr);",
        "}",
    ]
    return "\n".join(lines) + "\n"
