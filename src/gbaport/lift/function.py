"""Lift one function of the CFG to a C function.

Every block becomes a label. A branch to a block of the function is a goto;
a branch or fall-through anywhere else leaves the function by returning that
address. (Calls, returns and computed jumps come with the control-flow task.)
"""

from gbaport.analysis.cfg import Function, Program
from gbaport.analysis.discover import Exploration
from gbaport.isa.model import Cond, Instruction, Op
from gbaport.lift.semantics import CONDITIONS, cycles, hexu, lift_effects


def function_name(addr: int, prefix: str = "") -> str:
    return f"{prefix}f_{addr:08x}"


def label(addr: int) -> str:
    return f"L_{addr:08x}"


def lift_function(fn: Function, program: Program, ex: Exploration, prefix: str = "") -> str:
    return _FunctionLifter(fn, program, ex, prefix).lift()


class _FunctionLifter:
    def __init__(self, fn: Function, program: Program, ex: Exploration, prefix: str) -> None:
        self.fn = fn
        self.program = program
        self.ex = ex
        self.prefix = prefix
        self.blocks = set(fn.blocks)
        # The entry block comes first; the rest follow in address order.
        self.order = [fn.entry] + sorted(self.blocks - {fn.entry})

    def lift(self) -> str:
        lines = [f"uint32_t {function_name(self.fn.entry, self.prefix)}(GbaCtx *ctx)", "{"]
        lines += ["    uint32_t t = 0;", "    (void)t;"]
        for i, start in enumerate(self.order):
            following = self.order[i + 1] if i + 1 < len(self.order) else None
            lines += self._block(start, following)
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _block(self, start: int, following: int | None) -> list[str]:
        block = self.program.blocks[start]
        lines = [f"{label(start)}:"]
        lines.append(f"    ctx->cycles += {sum(cycles(ins) for ins in block.instructions)};")
        ended = False
        for ins in block.instructions:
            lines.append(f"    /* {ins.addr:08x} */")
            body, ended = self._instruction(ins)
            if ins.cond is not Cond.AL:
                body = [f"if ({CONDITIONS[ins.cond]}) {{", *("    " + s for s in body), "}"]
                ended = False
            lines += ["    " + s for s in body]
        if not ended:
            last = block.instructions[-1]
            nxt = last.addr + last.size
            if nxt != following:
                lines.append("    " + self._go(nxt))
        return lines

    def _instruction(self, ins: Instruction) -> tuple[list[str], bool]:
        """C for ``ins`` and whether control never falls through to the next instruction."""
        if ins.op is Op.UNDEFINED:
            return [f"gba_undefined(ctx, {hexu(ins.addr)});", f"GBA_EXIT({hexu(ins.addr)});"], True
        if ins.op is Op.B:
            return [self._go(ins.target)], True
        return lift_effects(ins), False

    def _go(self, target: int) -> str:
        if target in self.blocks:
            return f"goto {label(target)};"
        return f"GBA_EXIT({hexu(target)});"
