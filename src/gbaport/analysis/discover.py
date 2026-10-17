"""Recursive-descent code discovery.

From the seed entry points, walk instructions linearly and follow branches,
calls, jump tables and indirect transfers whose target is a known constant.
Each linear walk tracks register constants (reset at the start of every walk
and at every address other paths also reach), so ``ldr r0, =func; bx r0``
style transfers resolve. A constant a walk leaves in LR when it leaves for
elsewhere (``ldr lr, =main; b init``) is where that code returns to, so it
becomes an entry too. Indirect transfers the walk cannot resolve take their
targets from recorded traces when there are any. Anything else the walk
cannot follow becomes an ``Issue``; nothing in the ROM can make it raise.

Walks also record copies the game makes with constant operands (DMA register
writes, BIOS CpuSet/CpuFastSet) and the code addresses they wanted to reach
outside analysable code, so the analysis can recognise code copied into RAM.
"""

from collections import deque
from dataclasses import dataclass, field

from gbaport.analysis.config import GameConfig
from gbaport.analysis.effects import (
    LR,
    MASK,
    PC,
    RegState,
    interwork_target,
    read_registers,
    written_registers,
)
from gbaport.analysis.flow import Flow, FlowKind, classify
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.tables import JumpTable, Step, find_jump_table
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Cond, Instruction, Mode, Op

IRQ_VECTOR = 0x03007FFC  # the BIOS enters the IRQ handler stored here, in ARM state
DMA_BASE = 0x040000B0  # DMA0SAD; each of the 4 channels is SAD, DAD, CNT_L, CNT_H (12 bytes)
DMA_END = DMA_BASE + 4 * 12
_DMA_NOT_A_PLAIN_COPY = 0x31E0  # CNT_H: start timing, or a source/destination that is not +1
CPU_SET, CPU_FAST_SET = 0x0B, 0x0C
HISTORY_LIMIT = 16
_LITERAL_SIZES = {Op.LDR: 4, Op.LDRH: 2, Op.LDRSH: 2, Op.LDRB: 1, Op.LDRSB: 1}
_LEAVES = frozenset({FlowKind.BRANCH, FlowKind.JUMP, FlowKind.INDIRECT, FlowKind.RETURN})


@dataclass(frozen=True)
class Issue:
    addr: int
    kind: str
    detail: str


@dataclass(frozen=True)
class RamCopy:
    site: int  # the store or SWI that starts the copy
    src: int
    dst: int
    size: int  # bytes


@dataclass
class Exploration:
    instructions: dict[int, Instruction] = field(default_factory=dict)
    # Successors inside the function for every decoded instruction (fall-through included).
    successors: dict[int, tuple[int, ...]] = field(default_factory=dict)
    entries: dict[int, Mode] = field(default_factory=dict)
    entry_kinds: dict[int, str] = field(default_factory=dict)
    calls: dict[int, tuple[int, ...]] = field(default_factory=dict)  # call site -> callees
    jumps: dict[int, int] = field(default_factory=dict)  # jump site -> entry it leaves for
    literals: dict[int, int] = field(default_factory=dict)  # address -> size
    tables: list[JumpTable] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    # Indirect site -> targets taken from traces: callees, switch cases, or functions it leaves for.
    traced: dict[int, tuple[int, ...]] = field(default_factory=dict)
    copies: list[RamCopy] = field(default_factory=list)
    outside: dict[int, Mode] = field(default_factory=dict)  # code wanted outside the code space


Traced = dict[int, tuple[tuple[int, Mode], ...]]  # site -> (target, mode) seen in traces


def explore(
    space: CodeSpace,
    seeds: list[tuple[int, Mode, str]],
    config: GameConfig | None = None,
    *,
    traced: Traced | None = None,
    candidates: list[tuple[int, Mode, str]] | None = None,
) -> Exploration:
    """Discover the code reachable from ``seeds`` of (address, mode, entry kind).

    Walks forget their constants at branch targets and entries, because other
    paths reach those too. Which addresses those are is only known after a
    pass, so discovery repeats with every target found so far until a pass
    finds no new one (the set only grows, so this ends).

    ``traced`` resolves the indirect sites a walk reaches; targets of traced
    sites no walk reaches become entries of their own. ``candidates`` are
    guessed entries (pointer scan), walked one by one after all of that, and
    skipped when they land in code or data already found.
    """
    config = config or GameConfig()
    traced = {space.canonical(site): hits for site, hits in (traced or {}).items()}
    leaders: frozenset[int] = frozenset()
    while True:
        explorer = _Explorer(space, config, leaders, traced)
        for addr, mode, kind in seeds:
            explorer.add_entry(addr, mode, kind, origin=addr)
        explorer.drain()
        explorer.drain_traces()
        explorer.drain_candidates(candidates or [])
        if explorer.targets <= leaders:
            return explorer.ex
        leaders |= explorer.targets


class _Explorer:
    def __init__(
        self, space: CodeSpace, config: GameConfig, leaders: frozenset[int], traced: Traced
    ) -> None:
        self.space = space
        self.traced = traced
        self.data = config.data
        self.overrides = {table.at: table for table in config.jump_tables}
        self.leaders = leaders  # join points: walks reaching them forget their constants
        self.targets: set[int] = set()  # every branch target and entry found in this pass
        self.ex = Exploration()
        self.work: deque[tuple[int, Mode]] = deque()

    def drain(self) -> None:
        while self.work:
            self.walk(*self.work.popleft())

    def drain_traces(self) -> None:
        """Targets of traced sites no walk reached become entries themselves."""
        done: set[int] = set()
        while True:
            pending = [
                site
                for site in sorted(self.traced)
                if site not in done and site not in self.ex.instructions
            ]
            if not pending:
                return
            for site in pending:
                done.add(site)
                for target, mode in self.traced[site]:
                    self.add_entry(target, mode, "trace", origin=site)
            self.drain()

    def drain_candidates(self, candidates: list[tuple[int, Mode, str]]) -> None:
        """Walk each guessed entry on its own, unless it lands in code or data already found."""
        for addr, mode, kind in candidates:
            addr = self.space.canonical(addr)
            covering = self.ex.instructions.get(addr - 2)
            if (
                addr in self.ex.instructions
                or (covering is not None and covering.size == 4)
                or self._is_data(addr)
            ):
                continue
            self.add_entry(addr, mode, kind, origin=addr)
            self.drain()

    def issue(self, addr: int, kind: str, detail: str) -> None:
        self.ex.issues.append(Issue(addr, kind, detail))

    def add_entry(self, addr: int, mode: Mode, kind: str, origin: int) -> int | None:
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.ex.outside.setdefault(addr, mode)
            self.issue(
                origin,
                "outside_code",
                f"{kind} target {addr:#010x} is not in analysable code; "
                "add a [[ram_code]] entry if the game copies code there",
            )
            return None
        self.targets.add(addr)
        if addr not in self.ex.entries:
            self.ex.entries[addr] = mode
            self.ex.entry_kinds[addr] = kind
            self.work.append((addr, mode))
        return addr

    def add_branch(self, addr: int, mode: Mode, origin: int) -> int | None:
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
            self.ex.outside.setdefault(addr, mode)
            self.issue(origin, "outside_code", f"branch target {addr:#010x} is outside the ROM")
            return None
        self.targets.add(addr)
        self.work.append((addr, mode))
        return addr

    def walk(self, addr: int, mode: Mode) -> None:
        start = addr
        state = RegState()
        history: list[Step] = []
        prev: Instruction | None = None
        lr_set = False  # LR holds a constant this walk wrote and nothing has read since
        dma: dict[int, int] = {}  # DMA register halfwords this walk wrote with constants
        while True:
            if addr != start and addr in self.leaders:
                state, history, prev, lr_set, dma = RegState(), [], None, False, {}
            ins = self._take(addr, mode)
            if ins is None:
                return
            self._note_literal(ins)
            self._note_irq_vector(ins, state)
            self._note_copy(ins, state, dma)
            flow = classify(ins, state, prev, self.space)
            if lr_set and flow.kind in _LEAVES and not flow.falls_through:
                self._note_return_site(ins, state)
            successors, keep_going = self._follow(ins, flow, state, history)
            self.ex.successors[addr] = tuple(dict.fromkeys(successors))
            if not keep_going:
                return
            history.append(Step(ins, dict(state.consts)))
            del history[:-HISTORY_LIMIT]
            if LR in read_registers(ins):
                lr_set = False
            state.step(ins, self.space)
            if flow.kind is FlowKind.CALL:
                state.forget_call_clobbered()
            if LR in written_registers(ins):
                lr_set = LR in state.consts
            prev = ins
            addr += ins.size

    def _take(self, addr: int, mode: Mode) -> Instruction | None:
        """Decode and record the instruction at ``addr``, or report why the walk stops."""
        known = self.ex.instructions.get(addr)
        if known is not None:
            if known.mode is not mode:
                self.issue(
                    addr,
                    "mode_conflict",
                    f"reached as {mode.value} code but already decoded as {known.mode.value}",
                )
            return None
        if addr % (4 if mode is Mode.ARM else 2):
            self.issue(addr, "misaligned", f"{mode.value} code at an unaligned address")
            return None
        if self._is_data(addr):
            self.issue(addr, "enters_data", "walked into a [code] data range or a literal pool")
            return None
        ins = self.space.decode(addr, mode)
        if ins is None:
            self.issue(addr, "outside_code", "walked off the end of analysable code")
            return None
        if self._overlaps(ins):
            self.issue(addr, "overlap", "instruction overlaps one decoded earlier")
            return None
        self.ex.instructions[addr] = ins
        return ins


    def _is_data(self, addr: int) -> bool:
        if any(start <= addr < end for start, end in self.data):
            return True
        return any(self.ex.literals.get(addr - back, 0) > back for back in range(4))

    def _overlaps(self, ins: Instruction) -> bool:
        inside = any(a in self.ex.instructions for a in range(ins.addr + 2, ins.addr + ins.size, 2))
        before = self.ex.instructions.get(ins.addr - 2)
        return inside or (before is not None and before.size == 4)

    def _note_literal(self, ins: Instruction) -> None:
        size = _LITERAL_SIZES.get(ins.op)
        if size is not None and ins.rn == PC and ins.target is not None:
            self.ex.literals.setdefault(self.space.canonical(ins.target), size)

    def _note_irq_vector(self, ins: Instruction, state: RegState) -> None:
        """``str rV, [rA]`` with rA == 0x03007FFC installs rV as the IRQ handler."""
        if ins.op is not Op.STR or ins.rm is not None or not ins.pre or ins.cond is not Cond.AL:
            return
        base, value = state.value(ins.rn, ins), state.value(ins.rd, ins)
        if base is None or value is None:
            return
        offset = ins.imm if ins.up else -ins.imm
        if (base + offset) & MASK == IRQ_VECTOR:
            self.add_entry(value & ~3, Mode.ARM, "irq", origin=ins.addr)

    def _note_copy(self, ins: Instruction, state: RegState, dma: dict[int, int]) -> None:
        """Record copies started by DMA register writes or CpuSet/CpuFastSet with known operands.

        Conditional stores count as made: start-up code guards the DMA start with
        ``strne`` on the count, and adoption still needs code wanted inside the copy.
        """
        if ins.op is Op.SWI:
            if ins.cond is Cond.AL:
                self._note_cpu_set(ins, state)
            return
        started = []
        for addr, value, size in _stores(ins, state):
            for offset in range(0, size, 2):
                half = addr + offset
                if not DMA_BASE <= half < DMA_END:
                    continue
                if value is None:
                    dma.pop(half, None)
                else:
                    dma[half] = (value >> (8 * offset)) & 0xFFFF
                if (half - DMA_BASE) % 12 == 10:  # CNT_H: this write may start the channel
                    started.append(half - 10)
        for base in started:
            self._note_dma(ins, base, dma)

    def _note_dma(self, ins: Instruction, base: int, dma: dict[int, int]) -> None:
        """Record the transfer of the channel at ``base`` if every register is a known constant."""
        halves = [dma.get(base + offset) for offset in range(0, 12, 2)]
        if None in halves:
            return
        sad_lo, sad_hi, dad_lo, dad_hi, count, control = halves
        if not control & 0x8000 or control & _DMA_NOT_A_PLAIN_COPY:
            return
        limit = 0x10000 if base == DMA_BASE + 3 * 12 else 0x4000  # DMA3 has a 16-bit count
        count = count & (limit - 1) or limit
        unit = 4 if control & 0x0400 else 2
        src, dst = sad_lo | sad_hi << 16, dad_lo | dad_hi << 16
        self.ex.copies.append(RamCopy(ins.addr, src, dst, count * unit))

    def _note_cpu_set(self, ins: Instruction, state: RegState) -> None:
        number = ins.imm >> 16 if ins.mode is Mode.ARM else ins.imm
        if number not in (CPU_SET, CPU_FAST_SET):
            return
        src, dst, control = (state.value(reg, ins) for reg in (0, 1, 2))
        if src is None or dst is None or control is None or control & 0x01000000:
            return  # unknown operands, or a fill
        count = control & 0x1FFFFF
        if number == CPU_FAST_SET:
            size = -(-count // 8) * 32  # whole blocks of eight words
        else:
            size = count * (4 if control & 0x04000000 else 2)
        if size:
            self.ex.copies.append(RamCopy(ins.addr, src, dst, size))

    def _note_return_site(self, ins: Instruction, state: RegState) -> None:
        """A code address left in LR is where the code this walk leaves for returns to."""
        value = state.consts.get(LR)
        if value is None:
            return
        target, mode = interwork_target(value)
        if self.space.contains(self.space.canonical(target), 2):
            self.add_entry(target, mode, "return", origin=ins.addr)

    def _follow(
        self, ins: Instruction, flow: Flow, state: RegState, history: list[Step]
    ) -> tuple[tuple[int, ...], bool]:
        """Successors of ``ins`` inside its function, and whether the walk goes on."""
        after = (ins.addr + ins.size,)
        kind = flow.kind
        if kind is FlowKind.NEXT:
            return after, True
        if kind is FlowKind.CALL:
            self._call(ins, flow, state)
            return after, True
        if kind is FlowKind.BRANCH:
            target = self.add_branch(*flow.target, origin=ins.addr)
            here = () if target is None else (target,)
        elif kind is FlowKind.JUMP:
            entry = self.add_entry(*flow.target, "jump", origin=ins.addr)
            if entry is not None:
                self.ex.jumps[ins.addr] = entry
            here = ()
        elif kind is FlowKind.INDIRECT:
            here = self._indirect(ins, history)
        elif kind is FlowKind.RETURN:
            here = ()
        else:  # STOP
            if ins.op is Op.UNDEFINED:
                self.issue(
                    ins.addr,
                    "undefined",
                    f"undefined instruction {format_instruction(ins)} (data, or the wrong mode?)",
                )
            return (), False
        if flow.falls_through:
            return here + after, True
        return here, False

    def _call(self, ins: Instruction, flow: Flow, state: RegState) -> None:
        if flow.target is None:
            if not self._traced_call(ins):
                self.issue(
                    ins.addr, "unresolved_call", f"{format_instruction(ins)}: target unknown"
                )
            return
        target, mode = flow.target
        register = self._veneer_register(target, mode)
        if register is None:
            callee = self.add_entry(target, mode, "call", origin=ins.addr)
        else:
            self.add_entry(target, mode, "veneer", origin=ins.addr)
            callee = self._call_through(register, ins, state)
        if callee is not None:
            self.ex.calls[ins.addr] = (callee,)

    def _veneer_register(self, target: int, mode: Mode) -> int | None:
        """N if ``target`` is a ``bx rN`` call veneer (like agbcc's ``_call_via_rN``)."""
        ins = self.space.decode(self.space.canonical(target), mode)
        if ins is not None and ins.op is Op.BX and ins.cond is Cond.AL and ins.rm not in (LR, PC):
            return ins.rm
        return None

    def _call_through(self, register: int, ins: Instruction, state: RegState) -> int | None:
        value = state.value(register, ins)
        if value is None:
            if not self._traced_call(ins):
                self.issue(
                    ins.addr,
                    "unresolved_call",
                    f"call through a bx r{register} veneer with r{register} unknown",
                )
            return None
        target, mode = interwork_target(value)
        return self.add_entry(target, mode, "call", origin=ins.addr)

    def _traced_call(self, ins: Instruction) -> bool:
        """Take an unknown call's callees from the traces; False when no trace saw it."""
        added = [
            self.add_entry(target, mode, "trace", origin=ins.addr)
            for target, mode in self.traced.get(ins.addr, ())
        ]
        callees = tuple(sorted({entry for entry in added if entry is not None}))
        if callees:
            self.ex.calls[ins.addr] = callees
            self.ex.traced[ins.addr] = callees
        return bool(callees)

    def _indirect(self, ins: Instruction, history: list[Step]) -> tuple[int, ...]:
        match = find_jump_table(ins, history, self.space, self.overrides)
        hits = self.traced.get(ins.addr, ())
        if hits and (match is None or match.table is None):
            return self._traced_jump(ins, hits, switch=match is not None)
        if match is None:
            if self.ex.entry_kinds.get(ins.addr) != "veneer":
                self.issue(
                    ins.addr,
                    "unresolved_jump",
                    f"{format_instruction(ins)}: target unknown; "
                    "list possible targets as [code] entries or thumb_entries",
                )
            return ()
        if match.table is None:
            self.issue(ins.addr, "unbounded_table", match.problem)
            return ()
        table = match.table
        self.ex.tables.append(table)
        if table.data:
            for i in range(len(table.targets)):
                self.ex.literals.setdefault(table.table + 4 * i, 4)
        targets = (self.add_branch(t, table.mode, origin=ins.addr) for t in table.targets)
        return tuple(t for t in targets if t is not None)

    def _traced_jump(
        self, ins: Instruction, hits: tuple[tuple[int, Mode], ...], switch: bool
    ) -> tuple[int, ...]:
        """Traced targets of an indirect jump: cases of a ``switch``, or entries it leaves for.

        Returns the successors inside the function (none when the jump leaves it).
        """
        if switch:
            found = [self.add_branch(target, mode, origin=ins.addr) for target, mode in hits]
        else:
            found = [
                self.add_entry(target, mode, "trace", origin=ins.addr) for target, mode in hits
            ]
        targets = tuple(sorted({t for t in found if t is not None}))
        self.ex.traced[ins.addr] = targets
        return targets if switch else ()


def _stores(ins: Instruction, state: RegState) -> list[tuple[int, int | None, int]]:
    """(address, value or None, size) for each word or halfword store at a known address."""
    if ins.op in (Op.STR, Op.STRH) and ins.rm is None:
        base = state.value(ins.rn, ins)
        if base is None:
            return []
        offset = ins.imm if ins.up else -ins.imm
        size = 4 if ins.op is Op.STR else 2
        value = state.value(ins.rd, ins)
        if value is not None and size == 2:
            value &= 0xFFFF
        return [((base + offset if ins.pre else base) & MASK & -size, value, size)]
    if ins.op is Op.STM and not ins.pre and ins.up:  # stmia
        base = state.value(ins.rn, ins)
        if base is None:
            return []
        return [((base + 4 * i) & MASK, state.value(r, ins), 4) for i, r in enumerate(ins.reglist)]
    return []
