"""Recursive-descent code discovery.

From the seed entry points, walk instructions linearly and follow branches,
calls, jump tables and indirect transfers whose target is a known constant.
Each linear walk tracks register constants (reset at the start of every walk
and at every address other paths also reach), so ``ldr r0, =func; bx r0``
style transfers resolve. A constant a walk leaves in LR when it leaves for
elsewhere (``ldr lr, =main; b init``) is where that code returns to, so it
becomes an entry too. Anything the walk cannot follow becomes an ``Issue``;
nothing in the ROM can make it raise.
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
from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Cond, Instruction, Mode, Op
from gbaport.isa.thumb import decode_thumb

IRQ_VECTOR = 0x03007FFC  # the BIOS enters the IRQ handler stored here, in ARM state
HISTORY_LIMIT = 16
_LITERAL_SIZES = {Op.LDR: 4, Op.LDRH: 2, Op.LDRSH: 2, Op.LDRB: 1, Op.LDRSB: 1}
_LEAVES = frozenset({FlowKind.BRANCH, FlowKind.JUMP, FlowKind.INDIRECT, FlowKind.RETURN})


@dataclass(frozen=True)
class Issue:
    addr: int
    kind: str
    detail: str


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


def explore(
    space: CodeSpace, seeds: list[tuple[int, Mode, str]], config: GameConfig | None = None
) -> Exploration:
    """Discover the code reachable from ``seeds`` of (address, mode, entry kind).

    Walks forget their constants at branch targets and entries, because other
    paths reach those too. Which addresses those are is only known after a
    pass, so discovery repeats with every target found so far until a pass
    finds no new one (the set only grows, so this ends).
    """
    config = config or GameConfig()
    leaders: frozenset[int] = frozenset()
    while True:
        explorer = _Explorer(space, config, leaders)
        for addr, mode, kind in seeds:
            explorer.add_entry(addr, mode, kind, origin=addr)
        explorer.drain()
        if explorer.targets <= leaders:
            return explorer.ex
        leaders |= explorer.targets


class _Explorer:
    def __init__(self, space: CodeSpace, config: GameConfig, leaders: frozenset[int]) -> None:
        self.space = space
        self.data = config.data
        self.overrides = {table.at: table for table in config.jump_tables}
        self.leaders = leaders  # join points: walks reaching them forget their constants
        self.targets: set[int] = set()  # every branch target and entry found in this pass
        self.ex = Exploration()
        self.work: deque[tuple[int, Mode]] = deque()

    def drain(self) -> None:
        while self.work:
            self.walk(*self.work.popleft())

    def issue(self, addr: int, kind: str, detail: str) -> None:
        self.ex.issues.append(Issue(addr, kind, detail))

    def add_entry(self, addr: int, mode: Mode, kind: str, origin: int) -> int | None:
        addr = self.space.canonical(addr)
        if not self.space.contains(addr, 2):
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
        while True:
            if addr != start and addr in self.leaders:
                state, history, prev, lr_set = RegState(), [], None, False
            ins = self._take(addr, mode)
            if ins is None:
                return
            self._note_literal(ins)
            self._note_irq_vector(ins, state)
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
        ins = self._decode(addr, mode)
        if ins is None:
            self.issue(addr, "outside_code", "walked off the end of analysable code")
            return None
        if self._overlaps(ins):
            self.issue(addr, "overlap", "instruction overlaps one decoded earlier")
            return None
        self.ex.instructions[addr] = ins
        return ins

    def _decode(self, addr: int, mode: Mode) -> Instruction | None:
        if mode is Mode.ARM:
            if not self.space.contains(addr, 4):
                return None
            return decode_arm(self.space.read32(addr), addr)
        if not self.space.contains(addr, 2):
            return None
        following = self.space.read16(addr + 2) if self.space.contains(addr + 2, 2) else None
        return decode_thumb(self.space.read16(addr), addr, following)

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
            self.issue(ins.addr, "unresolved_call", f"{format_instruction(ins)}: target unknown")
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
        ins = self._decode(self.space.canonical(target), mode)
        if ins is not None and ins.op is Op.BX and ins.cond is Cond.AL and ins.rm not in (LR, PC):
            return ins.rm
        return None

    def _call_through(self, register: int, ins: Instruction, state: RegState) -> int | None:
        value = state.value(register, ins)
        if value is None:
            self.issue(
                ins.addr,
                "unresolved_call",
                f"call through a bx r{register} veneer with r{register} unknown",
            )
            return None
        target, mode = interwork_target(value)
        return self.add_entry(target, mode, "call", origin=ins.addr)

    def _indirect(self, ins: Instruction, history: list[Step]) -> tuple[int, ...]:
        match = find_jump_table(ins, history, self.space, self.overrides)
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
