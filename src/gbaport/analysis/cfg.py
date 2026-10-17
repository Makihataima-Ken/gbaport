"""Group discovered instructions into basic blocks and functions.

A block may belong to several functions (shared tails); the recompiler emits
it in each. A successor that is another function's entry is a tail call, not a
block of the function.
"""

from dataclasses import dataclass

from gbaport.analysis.discover import Exploration
from gbaport.isa.model import Instruction, Mode


@dataclass(frozen=True)
class Block:
    start: int
    mode: Mode
    instructions: tuple[Instruction, ...]
    successors: tuple[int, ...]  # block starts control may reach next, inside the function

    @property
    def end(self) -> int:
        last = self.instructions[-1]
        return last.addr + last.size


@dataclass(frozen=True)
class Function:
    entry: int
    mode: Mode
    kind: str  # how it was found: seed, call, veneer, jump, irq, return or trace
    blocks: tuple[int, ...]
    calls: tuple[int, ...]
    tail_calls: tuple[int, ...]


@dataclass(frozen=True)
class Program:
    blocks: dict[int, Block]
    functions: dict[int, Function]


def build_program(ex: Exploration) -> Program:
    blocks = _blocks(ex)
    functions = {
        entry: _function(ex, blocks, entry)
        for entry in sorted(ex.entries)
        if entry in blocks and blocks[entry].mode is ex.entries[entry]
    }
    return Program(blocks, functions)


def _leaders(ex: Exploration) -> set[int]:
    leaders = set(ex.entries)
    for addr, successors in ex.successors.items():
        after = addr + ex.instructions[addr].size
        if successors != (after,):
            leaders.update(successors)
            leaders.add(after)  # whatever follows a control transfer starts a new block
    return leaders & set(ex.instructions)


def _blocks(ex: Exploration) -> dict[int, Block]:
    leaders = _leaders(ex)
    blocks = {}
    for start in sorted(leaders):
        run, addr = [], start
        while True:
            ins = ex.instructions[addr]
            run.append(ins)
            after = addr + ins.size
            nxt = ex.instructions.get(after)
            if (
                ex.successors.get(addr) != (after,)
                or after in leaders
                or nxt is None
                or nxt.mode is not ins.mode
            ):
                break
            addr = after
        successors = tuple(
            s
            for s in ex.successors.get(addr, ())
            if s in leaders and ex.instructions[s].mode is ins.mode
        )
        blocks[start] = Block(start, run[0].mode, tuple(run), successors)
    return blocks


def _function(ex: Exploration, blocks: dict[int, Block], entry: int) -> Function:
    seen: set[int] = set()
    tails: set[int] = set()
    todo = [entry]
    while todo:
        start = todo.pop()
        if start in seen:
            continue
        seen.add(start)
        for successor in blocks[start].successors:
            if successor != entry and successor in ex.entries:
                tails.add(successor)
            elif successor in blocks:
                todo.append(successor)
    addrs = [ins.addr for start in seen for ins in blocks[start].instructions]
    calls = {callee for addr in addrs for callee in ex.calls.get(addr, ())}
    tails |= {ex.jumps[addr] for addr in addrs if addr in ex.jumps}
    jumped = [addr for addr in addrs if addr in ex.traced and addr not in ex.calls]
    tails |= {t for addr in jumped for t in ex.traced[addr] if t in ex.entries}
    return Function(
        entry=entry,
        mode=ex.entries[entry],
        kind=ex.entry_kinds[entry],
        blocks=tuple(sorted(seen)),
        calls=tuple(sorted(calls)),
        tail_calls=tuple(sorted(tails)),
    )
