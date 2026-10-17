# gbaport

Personal-use pipeline that turns a Game Boy Advance ROM dumped from your own cartridge
into native C, and from there into Android and iOS apps — with no emulator in the app.

Design: `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Never commit ROMs, saves, or anything extracted from them.** Put dumps in `roms/`
(gitignored).

## Setup

    uv sync

## Tests

    uv run pytest
    uv run ruff check src tests

## Commands

    uv run gbaport info roms/mygame.gba [--json]
    uv run gbaport disasm roms/mygame.gba --start 0x080000c0 --count 40 [--thumb]
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA (0.10 or newer, dev machine only) and records where its indirect calls
and jumps go:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
2. Run `uv run gbaport trace roms/mygame.gba` and play: menus, levels, cutscenes.
   Breakpoints follow newly found code every few seconds.
3. Press Ctrl+C. The trace is saved to `games/<game_code>/traces/mgba.trace`
   (addresses only, safe to commit) and `gbaport analyze` reads it automatically.
