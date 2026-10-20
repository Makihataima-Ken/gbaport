"""Traces from gbaport's own mGBA: every indirect transfer a game took while it played.

``gbaport-mgba --trace PATH`` runs the game an instruction at a time and writes each
indirect transfer once, as ``site target mode lr`` (hex, hex, arm or thumb, hex): the
instruction at ``site`` went to ``target`` in ``mode``, with ``lr`` as it was before.
Calls are followed on a shadow stack, so ordinary returns, and returns to an outer
call's return address (which the runtime unwinds), are left out.

``to_trace`` keeps the transfers whose site the analysis decodes as an instruction that
writes the PC, again and again, as the traced targets lead it to more code. A transfer
through a shared ``bx rN`` call veneer is recorded at the ``bl`` that called the veneer
(found from LR), so each call site gets its own targets, as ``gbaport trace`` records
them through mGBA's GDB server.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gbaport.analysis.discover import Exploration
from gbaport.analysis.flow import writes_pc
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode, Op


class TransferError(ValueError):
    """A transfer file is malformed."""


@dataclass(frozen=True)
class Transfer:
    site: int
    target: int
    mode: Mode
    lr: int


def parse_transfers(text: str, source: str = "transfers") -> set[Transfer]:
    transfers = set()
    for number, line in enumerate(text.splitlines(), start=1):
        fields = line.split()
        if not fields:
            continue
        try:
            site, target, mode, lr = fields
            transfers.add(Transfer(int(site, 16), int(target, 16), Mode(mode), int(lr, 16)))
        except ValueError:
            raise TransferError(f"{source}, line {number}: expected 'SITE TARGET MODE LR', "
                                f"got {line!r}") from None
    return transfers


def load_transfers(path: Path) -> set[Transfer]:
    return parse_transfers(path.read_text(encoding="utf-8"), str(path))


def to_trace(transfers: set[Transfer], analyze: Callable[[Trace], Exploration],
             trace: Trace) -> int:
    """Adds to ``trace`` the transfers the analysis can place; returns how many were new."""
    added = 0
    while True:
        ex = analyze(trace)
        veneers = {addr for addr, kind in ex.entry_kinds.items() if kind == "veneer"}
        new = 0
        for transfer in sorted(transfers, key=lambda t: (t.site, t.target, t.lr)):
            ins = ex.instructions.get(transfer.site)
            if ins is None or ins.op is Op.BL or not writes_pc(ins):
                continue
            origin = transfer.site
            if origin in veneers:
                caller = ex.instructions.get((transfer.lr & ~1) - 4)
                if caller is not None and caller.op is Op.BL:
                    origin = caller.addr
            new += trace.add(Hit(origin, transfer.target, transfer.mode))
        added += new
        if not new:
            return added
