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

The renderer, sound and timing tests compare every picture, pixel for pixel, every
sound, sample by sample, and the cycles kinds of code take with mGBA's: gbaport builds
mGBA 0.10.5's GBA core (MPL-2.0, a development tool only; no game ships it) from source
the first time, with the same CMake, Ninja and clang as SDL3, into the same cache folder.
Because interrupts reach recompiled code only at loops and returns, a change in a sound
may come up to two samples (61 microseconds) earlier or later than in mGBA. A picture
that differs is written next to mGBA's in `gbaport-romcache/pictures`, a sound that
differs next to mGBA's in `gbaport-romcache/sounds` (WAV files), and the test's message
names the files.

The Android tests build test ROMs' apps (the first run fetches what `gbaport build --host
android` needs, below) and run them on gbaport's own Android emulator: a 720x1280 phone
(Android 15, x86_64) with no window and no sound, drawn by the PC's graphics card and run
by Windows Hypervisor Platform. The tests boot it when it is not running (a minute or two;
it lives in `%LOCALAPPDATA%\gbaport\android-avd`) and shut it down after them. Run them
one test run at a time: two runs would drive the same emulator and app.

## Commands

    uv run gbaport info roms/mygame.gba [--json]
    uv run gbaport disasm roms/mygame.gba --start 0x080000c0 --count 40 [--thumb]
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
    uv run gbaport trace roms/mygame.gba --frames 4200 [--input FILE]
    uv run gbaport trace roms/mygame.gba [--port 2345] [--seconds 600]
    uv run gbaport recompile roms/mygame.gba [--out games/XXXX/generated]
    uv run gbaport build roms/mygame.gba [--config games/XXXX/game.toml] [--out games/XXXX]
    uv run gbaport build roms/mygame.gba --host android [--abi x86_64] [--install [--input FILE]]
    uv run gbaport verify roms/mygame.gba [--frames 600] [--input FILE] [--slack 1]

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
- `--input FILE`: hold the keys an input file names (below), any number of changes;
- `--registers`: print the CPU registers when the run ends;
- `--screenshot PATH`: save the last picture as a BMP file;
- `--audio PATH`: write the sound to a WAV file (16-bit stereo, 32768 samples a second);
- `--hashes PATH`: write a hash of each frame's picture, a line a frame (`gbaport verify`
  compares them with mGBA's).

Lines the game prints through mGBA's debug log go to stdout. The exit status is 0 when
the window is closed, or when the game executes the BIOS Stop call and nothing wakes it
(the window waits for a key instead, unless `--frames` limits the run); 2 for bad
arguments, a different ROM or an unusable save file; 3 for a runtime error; 4 when
`--frames` runs out.

The game's save chip (SRAM, Flash or EEPROM, as its library ID string or `game.toml`'s
`[rom] save` says) lives in a save file: `--save PATH`, by default the ROM's path with
`.sav` (`roms/mygame.sav`, which git ignores). It is written once a second while the game
changes it, when the game stops (the BIOS Stop call, in the window), and again when the
program ends, also after a runtime error. A save file of the wrong size is refused and
left as it is.

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
boot and play its first minute. With `games/BT4E/traces/mgba.trace`, recorded from
`games/BT4E/first-fight.input`, it plays on into its first fight.

Some games switch between tasks, each on its own stack: a task "returns" into another one,
where that one last switched away, past the calls the first task made since. The runtime
keeps each running call's return address, so when code goes to the return address of a
call further out, the recompiled functions in between return too, and the calls are as
deep as before.

The game's time is counted as mGBA counts it: each instruction costs its fetches at the
wait states WAITCNT sets for the memory it runs from, data accesses cost their memory's
wait states (through mGBA's model of the cartridge's prefetch buffer), and DMA and the
EEPROM take as long as in mGBA. So the game reaches each picture when it does in mGBA,
give or take a frame where an interrupt comes in at a loop or a return instead of at once.

## Playing on an Android phone

    uv run python -m gbaport.cli build roms/mygame.gba --host android --install

builds the game's app, installs it on the phone connected over USB and starts it. Turn on
USB debugging in the phone's developer options first, and allow this computer when the
phone asks. Without `--install`, the command builds `games/<game_code>/build/<game_code>.apk`
for phones (arm64-v8a; `--abi x86_64` builds it for the Android emulator on a PC); with
`--install` it builds for the connected device's processor. With several devices
connected, `ANDROID_SERIAL` names the one to use. `--input FILE`, with `--install`, has
the game play an input file this time. The app is `org.gbaport.<game_code>`, named with
the cartridge's title, and each build replaces the last.

The first Android build fetches about 4 GB into `%LOCALAPPDATA%\gbaport`:
- **The Android SDK** (`android-sdk`): Google's command-line tools and, through them, the
  Android 15 platform (API 35), build tools 35.0.0, NDK r29 and CMake 3.31.6. Installing
  them accepts Google's Android SDK licence (https://developer.android.com/studio/terms),
  which gbaport says when it does.
- **Gradle 8.12.1**, and through it the Android Gradle plugin 8.7.3 (`gradle-home`).
  Gradle needs a JDK 17 or newer (`JAVA_HOME`, or `java` on the PATH).
- **SDL3 3.4.18's source**, which the app builds SDL3 from.

The NDK's clang compiles a large game's code for minutes the first time (Dragon Ball GT
Transformation: about five); later builds compile only what changed. The Gradle project
stays in `games/<game_code>/build/android`, and Android Studio can open it.

The app is the window host built for Android, with the ROM inside it. It fills the
screen, held sideways, and draws the GBA's buttons over the picture:
- the D-pad on the left: slide a finger around it; a finger that came down on it keeps
  steering it wherever it goes;
- A and B on the right (a finger between them holds both);
- L and R in the top corners, Select and Start at the bottom.

A gamepad works as on the desktop. Pressing one of its buttons hides the drawn ones, and
touching the screen brings them back. The back button leaves the app as the home button
does.

The save lives in the app's own storage. It is stored once a second while the game
changes it, when the game stops (the BIOS Stop call), when the app goes to the
background, where Android may kill it at any time, and when the app ends. In the
background the game is paused. Uninstalling the app deletes its save.

What the game and the runtime print goes to Android's log, with the frame rate every ten
seconds:

    %LOCALAPPDATA%\gbaport\android-sdk\platform-tools\adb logcat -s gbaport

    59.73 frames a second; the game took 3.1 ms a frame

A runtime error shows its message on the screen; the app ends when it is closed.

## Checking a game against mGBA

`gbaport verify` builds a headless program for the game (into `build/<game_code>-verify`)
and plays it, and the game in mGBA, from power-on with a blank save, for `--frames`
frames (600 by default), holding the keys an input file names (`--input`). It compares
the pictures frame by frame:

    verified 900 frames: 472 pictures in the same order, at most 1 frame apart

A picture may come up to `--slack` frames (1 by default) earlier or later than in mGBA,
and a picture only one of them shows may last that long. Otherwise the report names the
frame where the two part, writes both pictures there side by side into a PNG file in the
same folder, and the exit status is 1. The first frame is left out: the game starts
halfway down it.

An input file holds the keys, a line each time they change, held from that frame on:

    # the title menu
    900 A
    906 none
    3900 RIGHT+A

The headless and window programs play one with `--input FILE`.

`games/BT4E/first-fight.input` plays Dragon Ball GT Transformation from power-on into its
first fight. Through the menus and the fight's first seconds, the pictures stay within a
frame of mGBA's:

    uv run gbaport verify roms/mygame.gba --frames 3600 --input games/BT4E/first-fight.input
    verified 3600 frames: 1211 pictures in the same order, at most 1 frame apart

Further on they part, at frame 3627: where the native build has come a frame early, a press
reaches the game a frame later in its own time, so the fighter it moves is one step behind
the rest of the picture; by frame 3837 the fight goes its own way.

## Recording traces with mGBA

Static analysis cannot see every function pointer. `gbaport trace` watches the game
running in mGBA and records where its indirect calls and jumps go, into
`games/<game_code>/traces/mgba.trace` (addresses only, safe to commit), which every
command reads. Each run adds to the file.

With `--frames N`, gbaport's own mGBA plays the game from power-on, holding the keys an
input file names (`--input`):

    uv run gbaport trace roms/mygame.gba --frames 4200 --input games/BT4E/first-fight.input
    played 4200 frames in mGBA: 914 indirect transfers, 729 new hits

It runs the game an instruction at a time and follows its calls on a stack of its own, so
it leaves out returns to the latest call and to calls further out (the runtime unwinds
those, above), and keeps every other jump through a register. A call through a shared
`bx rN` veneer is recorded at the `bl` that called the veneer, so each call site gets its
own targets.

Without `--frames`, it records what you play in mGBA's window (0.10 or newer, dev machine
only), through mGBA's GDB server:

1. Open the ROM in mGBA, then choose Tools > Start GDB server (port 2345).
2. Run `uv run gbaport trace roms/mygame.gba` and play: menus, levels, cutscenes.
   Breakpoints follow newly found code every few seconds.
3. Press Ctrl+C. The trace is saved to `games/<game_code>/traces/mgba.trace`
   (addresses only, safe to commit) and `gbaport analyze` reads it automatically.
