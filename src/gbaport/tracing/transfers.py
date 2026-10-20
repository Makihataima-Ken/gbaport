"""Traces from gbaport's own mGBA: every indirect transfer a game took while it played.

``gbaport-mgba --trace PATH`` runs the game an instruction at a time and writes each
indirect transfer once, as ``site target mode lr`` (hex, hex, arm or thumb, hex): the
instruction at ``site`` went to ``target`` in ``mode``, with ``lr`` as it was before.
Calls are followed on a shadow stack, so ordinary returns, and returns to an outer
call's return address (which the runtime unwinds), are left out.
"""

from dataclasses import dataclass
from pathlib import Path

from gbaport.isa.model import Mode


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
