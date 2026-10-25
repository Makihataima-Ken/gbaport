"""Whole-ROM analysis (discovery + blocks + coverage) and its JSON and text views."""

from collections import Counter
from dataclasses import dataclass

from gbaport.analysis.cfg import Program, build_program
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.analysis.discover import Exploration, Issue, explore
from gbaport.analysis.pointers import pointer_candidates
from gbaport.analysis.space import CodeSpace
from gbaport.analysis.traces import Trace, TraceError, targets_by_site
from gbaport.isa.model import Mode
from gbaport.rom.image import HEADER_SIZE, ROM_BASE, RomImage
from gbaport.rom.info import RomInfo, inspect_rom
from gbaport.rom.savetype import SaveType

FORMAT = "gbaport-analysis/1"
RAM_REGIONS = ((0x02000000, 0x02040000), (0x03000000, 0x03008000))  # EWRAM, IWRAM


@dataclass(frozen=True)
class Coverage:
    rom_bytes: int
    code_bytes: int
    literal_bytes: int
    data_bytes: int  # the cartridge header plus [code] data ranges

    @property
    def classified_percent(self) -> float:
        known = self.code_bytes + self.literal_bytes + self.data_bytes
        return 100.0 * known / self.rom_bytes


@dataclass(frozen=True)
class Analysis:
    info: RomInfo
    exploration: Exploration
    program: Program
    coverage: Coverage
    ram_code: tuple[RamCode, ...] = ()  # every overlay used: configured, then detected
    detected: tuple[RamCode, ...] = ()  # copies the analysis found and adopted itself
    save: SaveType = SaveType.NONE  # game.toml's [rom] save, else the ROM's library ID


def analyze_rom(
    rom: RomImage, config: GameConfig | None = None, traces: tuple[Trace, ...] = ()
) -> Analysis:
    config = config or GameConfig()
    info = inspect_rom(rom)
    if config.rom_sha1 is not None and config.rom_sha1 != info.sha1:
        raise ConfigError(
            f"game.toml is for ROM sha1 {config.rom_sha1}, but this ROM is {info.sha1}"
        )
    for trace in traces:
        if trace.sha1 != info.sha1:
            raise TraceError(f"trace is for ROM sha1 {trace.sha1}, but this ROM is {info.sha1}")
    space = CodeSpace(rom, config.ram_code)
    for start, end in config.data:
        if not rom.contains(space.canonical(start), end - start):
            raise ConfigError(f"data range [{start:#x}, {end:#x}] is outside the ROM")
    seeds = [(info.header.entry_point or ROM_BASE, Mode.ARM, "seed")]
    seeds += [(addr, Mode.ARM, "seed") for addr in config.entries]
    seeds += [(addr, Mode.THUMB, "seed") for addr in config.thumb_entries]
    seeds += [(blob.ram, blob.mode, "seed") for blob in config.ram_code]
    traced = targets_by_site(list(traces))
    detected: tuple[RamCode, ...] = ()
    while True:  # each round adopts copies that hold code the last round could not reach
        space = CodeSpace(rom, config.ram_code + detected)
        candidates = pointer_candidates(space) if config.scan_pointers else []
        exploration = explore(space, seeds, config, traced=traced, candidates=candidates,
                              sweep=config.sweep)
        found = _copied_code(exploration, space, config.ram_code + detected)
        if not found:
            break
        detected += found
    coverage = _coverage(space, exploration, config)
    program = build_program(exploration)
    save = config.save or info.save.save_type
    ram_code = config.ram_code + detected
    return Analysis(info, exploration, program, coverage, ram_code, detected, save)


def _copied_code(
    ex: Exploration, space: CodeSpace, known: tuple[RamCode, ...]
) -> tuple[RamCode, ...]:
    """Copies from ROM into RAM that cover code the walk wanted to reach, as new overlays."""
    found: list[RamCode] = []
    for copy in sorted(ex.copies, key=lambda c: (c.site, c.dst)):
        end = copy.dst + copy.size
        wanted = sorted(addr for addr in ex.outside if copy.dst <= addr < end)
        if not wanted or not any(lo <= copy.dst and end <= hi for lo, hi in RAM_REGIONS):
            continue
        blob = RamCode(space.canonical(copy.src), copy.dst, copy.size, ex.outside[wanted[0]])
        try:
            CodeSpace(space.rom, (*known, *found, blob))
        except ConfigError:
            continue  # not a ROM source, or overlapping an overlay already in use
        found.append(blob)
    return tuple(found)


def sorted_issues(ex: Exploration) -> list[Issue]:
    return sorted(ex.issues, key=lambda issue: (issue.addr, issue.kind))


def analysis_to_dict(analysis: Analysis) -> dict:
    ex, program, coverage = analysis.exploration, analysis.program, analysis.coverage
    header = analysis.info.header
    return {
        "format": FORMAT,
        "rom": {"title": header.title, "game_code": header.game_code, "sha1": analysis.info.sha1},
        "functions": [
            {
                "entry": _hex(f.entry),
                "mode": f.mode.value,
                "kind": f.kind,
                "blocks": [_hex(b) for b in f.blocks],
                "calls": [_hex(c) for c in f.calls],
                "tail_calls": [_hex(t) for t in f.tail_calls],
            }
            for f in sorted(program.functions.values(), key=lambda f: f.entry)
        ],
        "blocks": [
            {
                "start": _hex(b.start),
                "end": _hex(b.end),
                "mode": b.mode.value,
                "successors": [_hex(s) for s in b.successors],
            }
            for b in sorted(program.blocks.values(), key=lambda b: b.start)
        ],
        "jump_tables": [
            {
                "dispatch": _hex(t.dispatch),
                "table": _hex(t.table),
                "mode": t.mode.value,
                "data": t.data,
                "targets": [_hex(target) for target in t.targets],
            }
            for t in ex.tables
        ],
        "literals": [{"addr": _hex(a), "size": size} for a, size in sorted(ex.literals.items())],
        "traced": [
            {"site": _hex(site), "targets": [_hex(t) for t in targets]}
            for site, targets in sorted(ex.traced.items())
        ],
        "ram_code": [
            {
                "rom": _hex(blob.rom),
                "ram": _hex(blob.ram),
                "size": blob.size,
                "mode": blob.mode.value,
                "detected": blob in analysis.detected,
            }
            for blob in analysis.ram_code
        ],
        "issues": [
            {"addr": _hex(i.addr), "kind": i.kind, "detail": i.detail} for i in sorted_issues(ex)
        ],
        "coverage": {
            "rom_bytes": coverage.rom_bytes,
            "code_bytes": coverage.code_bytes,
            "literal_bytes": coverage.literal_bytes,
            "data_bytes": coverage.data_bytes,
        },
    }


def summary_lines(analysis: Analysis) -> list[str]:
    ex, program, coverage = analysis.exploration, analysis.program, analysis.coverage
    veneers = sum(1 for f in program.functions.values() if f.kind == "veneer")
    configured = len(analysis.ram_code) - len(analysis.detected)
    rows = [
        ("functions", f"{len(program.functions)} ({veneers} veneers)"),
        ("found by", _breakdown(f.kind for f in program.functions.values())),
        ("blocks", str(len(program.blocks))),
        ("jump tables", str(len(ex.tables))),
        ("ram code", f"{configured} configured, {len(analysis.detected)} detected"),
        ("code", f"{coverage.code_bytes} bytes"),
        ("literals", f"{coverage.literal_bytes} bytes"),
        ("data", f"{coverage.data_bytes} bytes"),
        ("classified", f"{coverage.classified_percent:.1f}% of {coverage.rom_bytes} bytes"),
        ("issues", f"{len(ex.issues)} ({_breakdown(issue.kind for issue in ex.issues)})"),
    ]
    return [f"{label:<13}{value}" for label, value in rows]


def _breakdown(kinds) -> str:
    counts = Counter(kinds)
    return ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items())) or "none"


def _hex(value: int) -> str:
    return f"{value:#010x}"


def _coverage(space: CodeSpace, ex: Exploration, config: GameConfig) -> Coverage:
    kinds = bytearray(len(space.rom.data))  # 0 unknown, 1 code, 2 literal, 3 data
    for ins in ex.instructions.values():
        _mark(kinds, space.rom_offset(ins.addr, ins.size), ins.size, 1)
    for addr, size in ex.literals.items():
        _mark(kinds, space.rom_offset(addr, size), size, 2)
    for start, end in [(ROM_BASE, ROM_BASE + HEADER_SIZE), *config.data]:
        offset = space.rom_offset(start, end - start)
        if offset is not None:
            stop = offset + (end - start)
            kinds[offset:stop] = kinds[offset:stop].replace(b"\x00", b"\x03")
    return Coverage(len(kinds), kinds.count(1), kinds.count(2), kinds.count(3))


def _mark(kinds: bytearray, offset: int | None, size: int, kind: int) -> None:
    if offset is None:
        return
    for i in range(offset, offset + size):
        if kinds[i] == 0:
            kinds[i] = kind
