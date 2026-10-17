"""Command-line entry point: ``gbaport <command> ...``."""

import argparse
import json
import sys
from pathlib import Path

from gbaport import __version__
from gbaport.analysis.analyze import analysis_to_dict, analyze_rom, sorted_issues, summary_lines
from gbaport.analysis.config import GameConfig, default_config_path, load_config
from gbaport.analysis.traces import default_trace_paths, load_trace
from gbaport.disasm import disassemble, format_line
from gbaport.isa.model import Mode
from gbaport.rom.header import parse_header
from gbaport.rom.image import ROM_BASE, RomImage
from gbaport.rom.info import inspect_rom


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gbaport", description="GBA ROM to native C port pipeline."
    )
    parser.add_argument("--version", action="version", version=f"gbaport {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    _add_info_command(commands)
    _add_disasm_command(commands)
    _add_analyze_command(commands)
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


def _run_analyze(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code
    config_path = args.config or default_config_path(game_code)
    config = load_config(config_path) if config_path else GameConfig()
    trace_paths = [*default_trace_paths(game_code), *map(Path, args.trace)]
    analysis = analyze_rom(rom, config, tuple(load_trace(path) for path in trace_paths))
    if config_path:
        print(f"{'config':<13}{config_path}")
    for path in trace_paths:
        print(f"{'trace':<13}{path}")
    for line in summary_lines(analysis):
        print(line)
    for issue in sorted_issues(analysis.exploration)[: args.issues]:
        print(f"  {issue.addr:08x}  {issue.kind:<16}  {issue.detail}")
    if args.out:
        document = json.dumps(analysis_to_dict(analysis), indent=1)
        Path(args.out).write_text(document, encoding="utf-8")
        print(f"wrote {args.out}")
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
