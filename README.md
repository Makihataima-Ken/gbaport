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

The lifter tests compile C with clang (`winget install LLVM.LLVM`) and compare against
Unicorn; their test binaries are cached in the system temp folder (`gbaport-liftcache`).
The runtime tests build small GBA test ROMs from C (`tests/gbaroms`) with clang and
ld.lld, recompile them and run them natively; ROMs and builds are cached in
`gbaport-romcache`.

## Commands

    uv run gbaport info roms/mygame.gba [--json]
    uv run gbaport disasm roms/mygame.gba --start 0x080000c0 --count 40 [--thumb]
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]
    uv run gbaport recompile roms/mygame.gba [--out games/XXXX/generated]
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]

If Windows Application Control blocks the `gbaport.exe` launcher, run the same commands
as `uv run python -m gbaport.cli ...`.

## Running a recompiled game

`gbaport build` recompiles the game and compiles it with the runtime into
`games/<game_code>/build/<game_code>.exe`. Run it with the ROM it was built from:

    games/XXXX/build/XXXX.exe roms/mygame.gba [--frames N]

It runs without a window for now (the desktop window comes in Plan 4c). Lines the game
prints through mGBA's debug log go to stdout. It exits with 0 when the game executes the
BIOS Stop call, 2 for bad arguments or a different ROM, 3 for a runtime error, and 4 when
`--frames` runs out. With Windows' Smart App Control on, a program that was just built is
sometimes blocked the first time it starts ("An Application Control policy has blocked
this file"); starting it again works.

The most common runtime error is code the recompiler did not find:

    error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3): add it to
    game.toml [code] thumb_entries, or record a trace

Add the address to `games/<game_code>/game.toml` (`thumb_entries` or `entries`, as the
message says) and build again, or record a trace with mGBA (below).

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA (0.10 or newer, dev machine only) and records where its indirect calls
and jumps go:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
2. Run `uv run gbaport trace roms/mygame.gba` and play: menus, levels, cutscenes.
   Breakpoints follow newly found code every few seconds.
3. Press Ctrl+C. The trace is saved to `games/<game_code>/traces/mgba.trace`
   (addresses only, safe to commit) and `gbaport analyze` reads it automatically.
