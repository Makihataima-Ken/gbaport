"""Lift one function of the CFG to a C function.

Every block becomes a label. A branch to a block of the function is a goto;
whatever leaves the function (a return, a tail call, a jump through a register)
returns the address to continue at, with bit 0 set when execution goes on in
Thumb state. The lookup ignores that bit; a miss reports it, so the user knows
which state the missing code is in. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address. Blocks that loops
or switches jump back to check for due events, so long loops still let the
scheduler run.
"""

from gbaport.analysis.cfg import Function, Program
from gbaport.analysis.discover import Exploration
from gbaport.analysis.flow import links_to_next, writes_pc
from gbaport.isa.model import Cond, Instruction, Mode, Op
from gbaport.lift.semantics import (
    CONDITIONS,
    LiftError,
    cycles,
    hexu,
    lift_effects,
    restores_cpsr,
)


def function_name(addr: int, prefix: str = "") -> str:
    return f"{prefix}f_{addr:08x}"


def label(addr: int) -> str:
    return f"L_{addr:08x}"


def lift_function(
    fn: Function,
    program: Program,
    ex: Exploration,
    prefix: str = "",
    problems: list[str] | None = None,
) -> str:
    """C for ``fn``; instructions it cannot express are reported in ``problems``."""
    lifter = _FunctionLifter(fn, program, ex, prefix)
    code = lifter.lift()
    if problems is not None:
        problems += lifter.problems
    return code


class _FunctionLifter:
    def __init__(self, fn: Function, program: Program, ex: Exploration, prefix: str) -> None:
        self.problems: list[str] = []
        self.fn = fn
        self.program = program
        self.ex = ex
        self.prefix = prefix
        self.blocks = set(fn.blocks)
        # The entry block comes first; the rest follow in address order.
        self.order = [fn.entry] + sorted(self.blocks - {fn.entry})

    def lift(self) -> str:
        loop_heads = self._loop_heads()
        lines = [f"uint32_t {function_name(self.fn.entry, self.prefix)}(GbaCtx *ctx)", "{"]
        lines += ["    uint32_t t = 0;", "    (void)t;"]
        for i, start in enumerate(self.order):
            following = self.order[i + 1] if i + 1 < len(self.order) else None
            lines += self._block(start, following, start in loop_heads)
        lines.append("}")
        return "\n".join(lines) + "\n"

    def _loop_heads(self) -> set[int]:
        """Blocks reached by a backward branch, or by a computed jump."""
        heads = set()
        for start in self.blocks:
            block = self.program.blocks[start]
            computed = writes_pc(block.instructions[-1])  # a switch may jump anywhere
            for succ in block.successors:
                if succ in self.blocks and (succ <= start or computed):
                    heads.add(succ)
        return heads

    def _block(self, start: int, following: int | None, loop_head: bool) -> list[str]:
        block = self.program.blocks[start]
        lines = [f"{label(start)}:"]
        lines.append(f"    ctx->cycles += {sum(cycles(ins) for ins in block.instructions)};")
        if loop_head:
            lines.append("    GBA_CHECK_EVENTS();")
        prev = self._predecessor(start, block.mode)
        ended = False
        for ins in block.instructions:
            lines.append(f"    /* {ins.addr:08x} */")
            body, ended = self._instruction(ins, prev)
            if ins.cond is not Cond.AL:
                body = [f"if ({CONDITIONS[ins.cond]}) {{", *("    " + s for s in body), "}"]
                ended = False
            lines += ["    " + s for s in body]
            prev = ins
        if not ended:
            last = block.instructions[-1]
            nxt = last.addr + last.size
            if nxt != following:
                lines.append("    " + self._go(nxt, block.mode))
        return lines

    def _predecessor(self, start: int, mode: Mode) -> Instruction | None:
        before = self.ex.instructions.get(start - (4 if mode is Mode.ARM else 2))
        if before is not None and self.ex.successors.get(before.addr) == (start,):
            return before
        return None

    def _instruction(self, ins: Instruction, prev: Instruction | None) -> tuple[list[str], bool]:
        """C for ``ins`` and whether control never falls through to the next instruction."""
        op = ins.op
        if op is Op.UNDEFINED:
            return [f"gba_undefined(ctx, {hexu(ins.addr)});", f"GBA_EXIT({hexu(ins.addr)});"], True
        after = ins.addr + ins.size
        if op is Op.B:
            if ins.target == after:  # a branch to the next instruction does nothing
                return [], False
            return [self._go(ins.target, ins.mode)], True
        if op is Op.BL:
            ret = self._return_address(ins)
            set_lr = f"ctx->r[14] = {hexu(ret)};"
            if ins.target == after:  # only sets LR (a weak call, or reading the pc)
                return [set_lr], False
            return [set_lr, self._call(ins.target, ret, ins.mode)], False
        if op is Op.BL_LO:
            ret = self._return_address(ins)
            return [
                f"t = (ctx->r[14] + {hexu(ins.imm)}) | 1u;",  # stays in Thumb state
                f"ctx->r[14] = {hexu(ret)};",
                f"gba_call(ctx, t, {hexu(ret)});",
            ], False
        try:
            effects = lift_effects(ins)
        except LiftError as error:  # reported, and handled like an undefined instruction
            self.problems.append(str(error))
            return [f"gba_undefined(ctx, {hexu(ins.addr)});", f"GBA_EXIT({hexu(ins.addr)});"], True
        if not writes_pc(ins):
            return effects, False
        body = effects + self._mask(ins)
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
            return body + ["gba_call(ctx, t, ctx->r[14]);"], False
        return body + self._switch(ins) + ["GBA_EXIT(t);"], True

    def _return_address(self, ins: Instruction) -> int:
        after = ins.addr + ins.size
        return after | 1 if ins.mode is Mode.THUMB else after

    def _call(self, target: int, ret: int, mode: Mode) -> str:
        """A call to a constant target: direct when that function was recompiled."""
        if target in self.program.functions:
            return f"gba_call_direct(ctx, {function_name(target, self.prefix)}, {hexu(ret)});"
        return f"gba_call(ctx, {hexu(_in_state(target, mode))}, {hexu(ret)});"

    def _go(self, target: int, mode: Mode) -> str:
        if target in self.blocks:
            return f"goto {label(target)};"
        return f"GBA_EXIT({hexu(_in_state(target, mode))});"

    def _mask(self, ins: Instruction) -> list[str]:
        if ins.op is Op.BX:
            return []  # bit 0 selects the state; the lookup ignores it
        if restores_cpsr(ins):  # the restored T bit decides the state
            return ["t = (ctx->cpsr_ctrl & 0x20u) ? t | 1u : t & ~3u;"]
        return ["t &= ~3u;" if ins.mode is Mode.ARM else "t |= 1u;"]  # no state change

    def _switch(self, ins: Instruction) -> list[str]:
        """Jumps to known cases (jump tables, traced targets) stay inside the function."""
        after = ins.addr + ins.size
        cases = [
            s for s in self.ex.successors.get(ins.addr, ())
            if s in self.blocks and not (s == after and ins.cond is not Cond.AL)
        ]
        if not cases:
            return []
        lines = ["switch (t & ~1u) {"]
        lines += [f"case {hexu(s)}: goto {label(s)};" for s in sorted(set(cases))]
        lines += ["default: break;", "}"]
        return lines


def _in_state(target: int, mode: Mode) -> int:
    """``target`` with bit 0 telling the state execution continues in."""
    return target | 1 if mode is Mode.THUMB else target
