"""Command-line entry point: ``gbaport <command> ...``."""

import argparse
import json
import sys
from pathlib import Path

from gbaport import __version__
from gbaport.analysis.analyze import analysis_to_dict, analyze_rom, sorted_issues, summary_lines
from gbaport.analysis.config import GameConfig, default_config_path, load_config
from gbaport.analysis.traces import Trace, default_trace_paths, load_trace, save_trace
from gbaport.disasm import disassemble, format_line
from gbaport.isa.model import Mode
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import HOSTS, compile_native, generated_sources, write_sources
from gbaport.rom.header import parse_header
from gbaport.rom.image import ROM_BASE, RomImage
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, GdbError, SocketTransport
from gbaport.tracing.session import TraceSession, check_loaded_rom


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gbaport", description="GBA ROM to native C port pipeline."
    )
    parser.add_argument("--version", action="version", version=f"gbaport {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _add_info_command(commands)
    _add_disasm_command(commands)
    _add_analyze_command(commands)
    _add_trace_command(commands)
    _add_recompile_command(commands)
    _add_build_command(commands)
    return parser


def _add_info_command(commands) -> None:
    info = commands.add_parser("info", help="show ROM header, hash and save type")
    info.add_argument("rom", help="path to a .gba file")
    info.add_argument("--json", action="store_true", help="print JSON instead of text")
    info.set_defaults(handler=_run_info)


def _run_info(args: argparse.Namespace) -> int:
    summary = inspect_rom(RomImage.load(args.rom)).to_dict()
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key:<13}{value}")
    return 0


def _int_auto(text: str) -> int:
    """Parse decimal or 0x-prefixed hex."""
    return int(text, 0)


def _add_disasm_command(commands) -> None:
    disasm = commands.add_parser("disasm", help="linear-sweep disassembly of a ROM range")
    disasm.add_argument("rom", help="path to a .gba file")
    disasm.add_argument(
        "--start", type=_int_auto, default=ROM_BASE, help="bus address (default 0x08000000)"
    )
    disasm.add_argument("--count", type=int, default=32, help="instructions to show (default 32)")
    disasm.add_argument("--thumb", action="store_true", help="decode as Thumb instead of ARM")
    disasm.set_defaults(handler=_run_disasm)


def _run_disasm(args: argparse.Namespace) -> int:
    mode = Mode.THUMB if args.thumb else Mode.ARM
    for ins in disassemble(RomImage.load(args.rom), args.start, args.count, mode):
        print(format_line(ins))
    return 0


def _add_analyze_command(commands) -> None:
    analyze = commands.add_parser("analyze", help="discover functions, blocks and jump tables")
    analyze.add_argument("rom", help="path to a .gba file")
    analyze.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    analyze.add_argument("--out", help="write the full analysis as JSON to this file")
    analyze.add_argument("--issues", type=int, default=20, help="issues to list (default 20)")
    analyze.add_argument(
        "--trace",
        action="append",
        default=[],
        help="trace file to import (repeatable; games/<game_code>/traces/*.trace are read too)",
    )
    analyze.set_defaults(handler=_run_analyze)


def _analyse(args: argparse.Namespace, rom: RomImage):
    """Analyse ``rom`` with its game.toml and traces, printing which ones were used."""
    game_code = parse_header(rom).game_code
    config_path = args.config or default_config_path(game_code)
    config = load_config(config_path) if config_path else GameConfig()
    trace_paths = [*default_trace_paths(game_code), *map(Path, args.trace)]
    sha1 = inspect_rom(rom).sha1
    traces = tuple(load_trace(path, sha1) for path in trace_paths)
    analysis = analyze_rom(rom, config, traces)
    if config_path:
        print(f"{'config':<13}{config_path}")
    for path in trace_paths:
        print(f"{'trace':<13}{path}")
    return analysis


def _run_analyze(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    analysis = _analyse(args, rom)
    for line in summary_lines(analysis):
        print(line)
    for issue in sorted_issues(analysis.exploration)[: args.issues]:
        print(f"  {issue.addr:08x}  {issue.kind:<16}  {issue.detail}")
    if args.out:
        document = json.dumps(analysis_to_dict(analysis), indent=1)
        Path(args.out).write_text(document, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


def _add_trace_command(commands) -> None:
    trace = commands.add_parser(
        "trace", help="record indirect branch targets from a game running in mGBA"
    )
    trace.add_argument("rom", help="path to the .gba file loaded in mGBA")
    trace.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    trace.add_argument(
        "--out", help="trace file to extend (default: games/<game_code>/traces/mgba.trace)"
    )
    trace.add_argument(
        "--trace",
        action="append",
        default=[],
        help="other trace files to import (games/<game_code>/traces/*.trace are read too)",
    )
    trace.add_argument("--host", default="127.0.0.1", help="GDB server host (default 127.0.0.1)")
    trace.add_argument("--port", type=int, default=2345, help="GDB server port (default 2345)")
    trace.add_argument("--seconds", type=float, help="stop after this long (default: Ctrl+C)")
    trace.add_argument(
        "--reanalyze-every",
        type=float,
        default=5.0,
        help="seconds between re-analyses that move breakpoints to new code (default 5)",
    )
    trace.set_defaults(handler=_run_trace)


def _run_trace(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code
    config_path = args.config or default_config_path(game_code)
    config = load_config(config_path) if config_path else GameConfig()
    out = Path(args.out) if args.out else Path("games") / game_code / "traces" / "mgba.trace"
    sha1 = inspect_rom(rom).sha1
    recorded = load_trace(out, sha1) if out.exists() else Trace(sha1)
    others = [*default_trace_paths(game_code), *map(Path, args.trace)]
    fixed = tuple(load_trace(path, sha1) for path in others if path.resolve() != out.resolve())

    def analyze(trace: Trace):
        return analyze_rom(rom, config, (*fixed, trace)).exploration

    client = GdbClient(SocketTransport.connect(args.host, args.port))
    try:
        client.handshake()
        check_loaded_rom(client, rom)
    except GdbError:
        client.close()
        raise
    print(f"connected to {args.host}:{args.port}; play the game, press Ctrl+C to stop")
    session = TraceSession(
        client,
        analyze,
        recorded,
        save=lambda trace: save_trace(trace, out),
        report=print,
        reanalyze_every=args.reanalyze_every,
    )
    try:
        session.run(args.seconds)
    finally:
        client.close()
    print(f"wrote {out} ({len(recorded.hits)} hits)")
    return 0


def _add_recompile_command(commands) -> None:
    recompile = commands.add_parser("recompile", help="lift the analysed code to C")
    recompile.add_argument("rom", help="path to a .gba file")
    recompile.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    recompile.add_argument(
        "--trace",
        action="append",
        default=[],
        help="trace file to import (repeatable; games/<game_code>/traces/*.trace are read too)",
    )
    recompile.add_argument(
        "--out", help="directory for the C sources (default: games/<game_code>/generated)"
    )
    recompile.set_defaults(handler=_run_recompile)


def _recompile(args: argparse.Namespace, rom: RomImage, out: Path) -> None:
    """Analyse and lift ``rom``, write its C sources to ``out`` and report."""
    analysis = _analyse(args, rom)
    lifted = lift_program(analysis.program, analysis.exploration)
    files = generated_sources(lifted, rom.data, analysis.save)
    write_sources(files, out)
    lines = sum(text.count("\n") for name, text in files.items() if name != HEADER)
    print(f"{'functions':<13}{len(lifted.functions)}")
    print(f"{'C files':<13}{len(files)} ({lines} lines)")
    print(f"{'lift issues':<13}{len(lifted.problems)}")
    for problem in lifted.problems[:20]:
        print(f"  {problem}")
    print(f"wrote {out}")


def _run_recompile(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    out = Path(args.out) if args.out else Path("games") / parse_header(rom).game_code / "generated"
    _recompile(args, rom, out)
    return 0


def _add_build_command(commands) -> None:
    build = commands.add_parser(
        "build", help="recompile a game and compile it with the runtime into a program"
    )
    build.add_argument("rom", help="path to a .gba file")
    build.add_argument(
        "--config", help="game.toml (default: games/<game_code>/game.toml if it exists)"
    )
    build.add_argument(
        "--trace",
        action="append",
        default=[],
        help="trace file to import (repeatable; games/<game_code>/traces/*.trace are read too)",
    )
    build.add_argument(
        "--out",
        help="folder for generated/ and build/ (default: games/<game_code>)",
    )
    build.add_argument(
        "--host",
        choices=sorted(HOSTS),
        default="sdl",
        help="sdl: a window (the default; builds SDL3 the first time); headless: no window",
    )
    build.set_defaults(handler=_run_build)


def _run_build(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code or "game"
    root = Path(args.out) if args.out else Path("games") / game_code
    _recompile(args, rom, root / "generated")
    name = game_code if args.host == "sdl" else f"{game_code}-{args.host}"
    program = compile_native(root / "generated", root / "build", name, args.host)
    print(f"built {program}")
    print(f"run it with: {program} {args.rom} [--save PATH] [--frames N]")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
