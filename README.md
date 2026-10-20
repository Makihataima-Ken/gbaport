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
`gbaport-romcache`. They also download and run jsmolka's CPU and PPU test ROMs (MIT
licence; `tests/publicroms/jsmolka` has their configs), so the first run needs a network
connection. The window tests build SDL3 the first time (see below) and run with SDL's
dummy video and sound drivers, so no window opens and nothing plays.

The renderer and sound tests compare every picture, pixel for pixel, and every sound,
sample by sample, with mGBA's: they build mGBA 0.10.5's GBA core (MPL-2.0, a development
tool only; nothing ships it) from source the first time, with the same CMake, Ninja and
clang as SDL3, into the same cache folder. Because the recompiled code's timing is an
estimate, a change in a sound may come up to two samples (61 microseconds) earlier or
later than in mGBA. A picture that differs is written next to mGBA's in
`gbaport-romcache/pictures`, a sound that differs next to mGBA's in
`gbaport-romcache/sounds` (WAV files), and the test's message names the files.

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
`games/<game_code>/build/<game_code>.exe`, which runs the game in a window. Run it with
the ROM it was built from:

    games/XXXX/build/XXXX.exe roms/mygame.gba [--save PATH] [--scale N] [--fast]

Keys: arrows, X = A, Z = B, A = L, S = R, Enter = Start, Backspace = Select. A gamepad
works too: its right face button is A, the bottom one B. The game runs at the GBA's 59.73
frames a second (`--fast`: as fast as it can), and the picture grows with the window by
whole steps (`--scale`: the starting size, 3 by default). The renderer draws every
line as the GBA does (tiled, rotating and bitmap backgrounds, sprites, windows, blending,
mosaic) from the registers as they are at the end of that line, so effects that change
them between lines work. Closing the window ends the run.

The sound (the four Game Boy channels and the two DMA sound channels, mixed 32768 times a
second as the GBA mixes them) plays on the default sound device; SDL converts it to the
device's rate. With `--fast`, or when there is no sound device, the game runs silent.

The first build also builds SDL3 3.4.18 from source, once, into `%LOCALAPPDATA%\gbaport`
(`GBAPORT_CACHE` moves it). That needs CMake and Ninja (the Visual Studio Build Tools
include both; elsewhere `winget install Kitware.CMake Ninja-build.Ninja`), a network
connection, and a minute or two.

`gbaport build --host headless` builds `<game_code>-headless.exe` instead, which runs
without a window, for tests and scripts. Both programs take:

- `--frames N`: end after N frames;
- `--save PATH`: the save file (below);
- `--press FRAME:KEYS`: hold KEYS from that frame on (repeatable). KEYS are A, B, SELECT,
  START, RIGHT, LEFT, UP, DOWN, R and L joined with `+`, or `none`;
- `--registers`: print the CPU registers when the run ends;
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second).

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
(the window waits for a key instead, unless `--frames` limits the run); 2 for bad
arguments, a different ROM or an unusable save file; 3 for a runtime error; 4 when
`--frames` runs out.

The game's save chip (SRAM, Flash or EEPROM, as its library ID string or `game.toml`'s
`[rom] save` says) lives in a save file: `--save PATH`, by default the ROM's path with
`.sav` (`roms/mygame.sav`, which git ignores). It is written once a second while the game
changes it and again when the program ends, also after a runtime error. A save file of
the wrong size is refused and left as it is.

Windows' Smart App Control judges every newly built program by its content and refuses
some of them for good ("An Application Control policy has blocked this file"). `gbaport
build` checks that the program starts and, when Windows refuses it, links it again with a
few different bytes, up to 20 times.

The most common runtime error is code the recompiler did not find:

    error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3): add it to
    game.toml [code] thumb_entries, or record a trace

Add the address to `games/<game_code>/game.toml` (`thumb_entries` or `entries`, as the
message says) and build again, or record a trace with mGBA (below).
`games/BT4E/game.toml` is an example: the entries Dragon Ball GT Transformation needs to
boot and play its first minute.

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA (0.10 or newer, dev machine only) and records where its indirect calls
and jumps go:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
2. Run `uv run gbaport trace roms/mygame.gba` and play: menus, levels, cutscenes.
   Breakpoints follow newly found code every few seconds.
3. Press Ctrl+C. The trace is saved to `games/<game_code>/traces/mgba.trace`
   (addresses only, safe to commit) and `gbaport analyze` reads it automatically.
