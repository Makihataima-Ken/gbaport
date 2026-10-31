"""Lift one function of the CFG to a C function.

Every block becomes a label. A branch to a block of the function is a goto;
whatever leaves the function (a return, a tail call, a jump through a register)
returns the address to continue at, with bit 0 set when execution goes on in
Thumb state. The lookup ignores that bit; a miss reports it, so the user knows
which state the missing code is in. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address; after it,
``GBA_UNWOUND`` returns too when code went back to a call further out (a task
switch). Code checks for due events at every taken branch back to an address at or
before the branch and at every jump through a register that is not a call, and nowhere
else: every loop has one of those, so long loops still let the scheduler run, and the
rule does not depend on where functions begin and end, so the interpreter
(runtime/interp.c) checks at the same instructions.

Time is counted as mGBA counts it (gba_cpu.h): each instruction costs the fetch of
the next one at the wait states of the memory the code is in (set by WAITCNT),
plus its internal cycles. Those costs are added to ``ctx->cycles`` in pieces, just
before each memory access and before control leaves the block, so an access sees
the time the instructions before it took, as in mGBA. Data accesses, multiplies
and jumps add their own waits where they happen.
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
        prev = self._predecessor(start, block.mode)
        ended = False
        pending = (0, 0, 0)  # the cost of instructions run but not yet added to ctx->cycles
        for ins in block.instructions:
            lines.append(f"    /* {ins.addr:08x} */")
            own = self._static(ins)
            if _leaves(ins):  # its own cost too, before control goes elsewhere
                pending, own = _plus(pending, own), (0, 0, 0)
            if _leaves(ins) or _accesses(ins):
                lines += self._charge(pending, ins)
                pending = (0, 0, 0)
            pending = _plus(pending, own)
            body, ended = self._instruction(ins, prev)
            body = self._extra(ins) + body
            if ins.cond is not Cond.AL:
                body = [f"if ({CONDITIONS[ins.cond]}) {{", *("    " + s for s in body), "}"]
                ended = False
            lines += ["    " + s for s in body]
            prev = ins
        if not ended:
            lines += self._charge(pending, block.instructions[-1])
            last = block.instructions[-1]
            nxt = last.addr + last.size
            if nxt != following:
                lines.append("    " + self._fall(nxt, block.mode))
        return lines

    def _static(self, ins: Instruction) -> tuple[int, int, int]:
        """The cost of ``ins`` known before it runs (see ``semantics.cycles``)."""
        if ins.cond is not Cond.AL and ins.mode is Mode.ARM:
            return 1, 1, 0  # the rest is added if the condition holds
        return cycles(ins)

    def _charge(self, cost: tuple[int, int, int], ins: Instruction) -> list[str]:
        if cost == (0, 0, 0):
            return []
        return [f"    ctx->cycles += {_cost_expr(*cost, ins.addr, ins.mode)};"]

    def _extra(self, ins: Instruction) -> list[str]:
        """What a conditional ARM instruction costs beyond its fetch, when it runs."""
        if ins.cond is Cond.AL or ins.mode is not Mode.ARM:
            return []
        k, s, n = cycles(ins)
        if (k, s, n) == (1, 1, 0):
            return []
        return [f"ctx->cycles += {_cost_expr(k - 1, s - 1, n, ins.addr, ins.mode)};"]

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
            refill = f"gba_jumped(ctx, {_refill_expr(ins.target, ins.mode)});"
            if ins.target == after:  # a branch to the next instruction only refills
                return [refill], False
            return [refill, *self._branch(ins)], True
        if op is Op.BL:
            ret = self._return_address(ins)
            set_lr = f"ctx->r[14] = {hexu(ret)};"
            refill = f"gba_jumped(ctx, {_refill_expr(ins.target, ins.mode)});"
            if ins.target == after:  # only sets LR (a weak call, or reading the pc)
                return [set_lr, refill], False
            call = self._call(ins.target, ret, ins.mode)
            return [set_lr, refill, call, "GBA_UNWOUND();"], False
        if op is Op.BL_LO:
            ret = self._return_address(ins)
            return [
                f"t = (ctx->r[14] + {hexu(ins.imm)}) | 1u;",  # stays in Thumb state
                f"ctx->r[14] = {hexu(ret)};",
                "gba_jumped(ctx, gba_refill(ctx, t));",
                f"gba_call(ctx, t, {hexu(ret)});",
                "GBA_UNWOUND();",
            ], False
        try:
            effects = lift_effects(ins)
        except LiftError as error:  # reported, and handled like an undefined instruction
            self.problems.append(str(error))
            return [f"gba_undefined(ctx, {hexu(ins.addr)});", f"GBA_EXIT({hexu(ins.addr)});"], True
        if not writes_pc(ins):
            return effects, False
        body = effects + self._mask(ins) + ["gba_jumped(ctx, gba_refill(ctx, t));"]
        if links_to_next(prev):  # mov lr, pc just before: a call through a register
            return body + ["gba_call(ctx, t, ctx->r[14]);", "GBA_UNWOUND();"], False
        switch = self._switch(ins)
        if switch:  # the jump's one check, then a case of the function or the dispatcher
            return body + ["GBA_CHECK_EVENTS();", *switch, "GBA_LEAVE(t);"], True
        return body + ["GBA_EXIT(t);"], True

    def _return_address(self, ins: Instruction) -> int:
        after = ins.addr + ins.size
        return after | 1 if ins.mode is Mode.THUMB else after

    def _call(self, target: int, ret: int, mode: Mode) -> str:
        """A call to a constant target: direct when that function was recompiled."""
        if target in self.program.functions:
            return f"gba_call_direct(ctx, {function_name(target, self.prefix)}, {hexu(ret)});"
        return f"gba_call(ctx, {hexu(_in_state(target, mode))}, {hexu(ret)});"

    def _branch(self, ins: Instruction) -> list[str]:
        """A taken B: a backward one checks for due events (every loop has one)."""
        target, back = ins.target, ins.target <= ins.addr
        if target in self.blocks:
            return ["GBA_CHECK_EVENTS();", f"goto {label(target)};"] if back else [f"goto {label(target)};"]
        exit_ = "GBA_EXIT" if back else "GBA_LEAVE"
        return [f"{exit_}({hexu(_in_state(target, ins.mode))});"]

    def _fall(self, target: int, mode: Mode) -> str:
        """Running on into the next block: no check."""
        if target in self.blocks:
            return f"goto {label(target)};"
        return f"GBA_LEAVE({hexu(_in_state(target, mode))});"

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


def _plus(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[int, int, int]:
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _leaves(ins: Instruction) -> bool:
    """Control may go elsewhere after ``ins``: a branch, call or write to pc."""
    return ins.op in (Op.B, Op.BL, Op.BL_LO) or writes_pc(ins)


def _accesses(ins: Instruction) -> bool:
    """``ins`` reads or writes memory, or calls the BIOS: it may see the time."""
    return ins.op in (Op.LDR, Op.LDRB, Op.LDRH, Op.LDRSB, Op.LDRSH, Op.STR, Op.STRB, Op.STRH,
                      Op.LDM, Op.STM, Op.SWP, Op.SWPB, Op.SWI)


def _cost_expr(k: int, s: int, n: int, addr: int, mode: Mode) -> str:
    """C for k cycles plus s sequential and n nonsequential fetches of code at ``addr``."""
    width = "16" if mode is Mode.THUMB else "32"
    region = addr >> 24 if addr >> 24 < 16 else 0  # as gba_region()
    terms = [f"{k}u"]
    if s:
        terms.append(f"{s} * ctx->s{width}[{region}]")
    if n:
        terms.append(f"{n} * ctx->n{width}[{region}]")
    return " + ".join(terms)


def _refill_expr(target: int, mode: Mode) -> str:
    """Refilling the pipeline at a constant target: 2 + N + S of its code."""
    return _cost_expr(2, 1, 1, target, mode)


def _in_state(target: int, mode: Mode) -> int:
    """``target`` with bit 0 telling the state execution continues in."""
    return target | 1 if mode is Mode.THUMB else target
