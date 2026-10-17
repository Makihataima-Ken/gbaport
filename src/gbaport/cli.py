"""Command-line entry point: ``gbaport <command> ...``."""

import argparse
import sys

from gbaport import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gbaport", description="GBA ROM to native C port pipeline."
    )
    parser.add_argument("--version", action="version", version=f"gbaport {__version__}")
    parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
