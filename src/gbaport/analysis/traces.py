"""Execution traces: where indirect branches and calls went while the game ran.

A trace is a text file with one observation per line, so runs merge by
concatenation and diffs stay readable::

    gbaport-trace/1 8dd4b6e95dca4554a919bff55128481a9a95b611
    # comments and blank lines are ignored
    080359de 0800a1c4 thumb

The header names the sha1 of the ROM the trace was recorded on. Each line is
``site target mode``: the indirect branch or call at ``site`` went to
``target``, running in ``mode``. Traces hold addresses only, never ROM bytes.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from gbaport.isa.model import Mode

FORMAT = "gbaport-trace/1"


class TraceError(ValueError):
    """A trace file is malformed or was recorded on a different ROM."""


@dataclass(frozen=True)
class Hit:
    site: int  # the indirect branch or call instruction
    target: int  # where it went
    mode: Mode  # the state the target ran in


@dataclass
class Trace:
    sha1: str
    hits: set[Hit] = field(default_factory=set)

    def add(self, hit: Hit) -> bool:
        """Record ``hit``; True when it was not seen before."""
        if hit in self.hits:
            return False
        self.hits.add(hit)
        return True

    def merge(self, other: "Trace") -> None:
        if other.sha1 != self.sha1:
            raise TraceError(f"cannot merge a trace of ROM {other.sha1} into one of {self.sha1}")
        self.hits |= other.hits


def sorted_hits(hits: set[Hit]) -> list[Hit]:
    return sorted(hits, key=lambda hit: (hit.site, hit.target, hit.mode.value))


def targets_by_site(traces: list[Trace]) -> dict[int, tuple[tuple[int, Mode], ...]]:
    """Every traced target of each site, in a stable order."""
    sites: dict[int, list[tuple[int, Mode]]] = {}
    for hit in sorted_hits({hit for trace in traces for hit in trace.hits}):
        sites.setdefault(hit.site, []).append((hit.target, hit.mode))
    return {site: tuple(targets) for site, targets in sites.items()}


def format_trace(trace: Trace) -> str:
    lines = [f"{FORMAT} {trace.sha1}"]
    lines += [f"{h.site:08x} {h.target:08x} {h.mode.value}" for h in sorted_hits(trace.hits)]
    return "\n".join(lines) + "\n"


def parse_trace(text: str, source: str = "trace") -> Trace:
    rows = [
        (number, line.split())
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not rows:
        raise TraceError(f"{source}: empty file, expected a '{FORMAT} <sha1>' header")
    number, header = rows[0]
    if len(header) != 2 or header[0] != FORMAT or not _is_sha1(header[1]):
        raise TraceError(f"{source}:{number}: expected a '{FORMAT} <sha1>' header")
    trace = Trace(header[1].lower())
    for number, fields in rows[1:]:
        trace.add(_hit(fields, f"{source}:{number}"))
    return trace


def load_trace(path: str | Path) -> Trace:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise TraceError(f"{path}: not a UTF-8 text file") from None
    return parse_trace(text, str(path))


def save_trace(trace: Trace, path: str | Path) -> None:
    """Write ``trace`` to ``path`` atomically, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(format_trace(trace), encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def default_trace_paths(game_code: str, root: Path = Path(".")) -> list[Path]:
    """``games/<game_code>/traces/*.trace`` under ``root``, sorted."""
    return sorted((root / "games" / game_code / "traces").glob("*.trace"))


def _is_sha1(text: str) -> bool:
    return len(text) == 40 and all(c in "0123456789abcdefABCDEF" for c in text)


def _hit(fields: list[str], where: str) -> Hit:
    if len(fields) != 3:
        raise TraceError(f"{where}: expected 'site target mode', got {' '.join(fields)!r}")
    site, target = (_address(text, where) for text in fields[:2])
    if fields[2] not in ("arm", "thumb"):
        raise TraceError(f'{where}: mode must be "arm" or "thumb", got {fields[2]!r}')
    mode = Mode(fields[2])
    if target % (2 if mode is Mode.THUMB else 4):
        raise TraceError(f"{where}: {mode.value} target {target:#010x} is misaligned")
    return Hit(site, target, mode)


def _address(text: str, where: str) -> int:
    try:
        value = int(text, 16)
    except ValueError:
        raise TraceError(f"{where}: {text!r} is not a hex address") from None
    if not 0 <= value <= 0xFFFFFFFF:
        raise TraceError(f"{where}: {text!r} is not a 32-bit address")
    return value
