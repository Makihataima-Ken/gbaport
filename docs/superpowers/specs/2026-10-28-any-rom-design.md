# Any ROM to Windows and Android — Design

Date: 2026-10-28 · Status: draft, awaiting review · Builds on
`2026-10-17-gba-native-port-design.md` (the base spec) and changes the parts listed under
"Changes to the base spec".

## Intent

gbaport works today for one game, Dragon Ball GT Transformation (BT4E), after hand
tuning: a list of code addresses in `games/BT4E/game.toml`, a trace, and `gbaport learn`
runs over recorded play. A new ROM stops for good at the first address the build did not
find (`runtime/runtime.c`, `gba_missing` → `gba_fail`).

The user wants gbaport to take any GBA ROM dumped from a cartridge they own and turn it
into a Windows app and an Android app that play the game from start to finish, with no
per-game hand work. Personal use only, as before.

## What the user decided

- **"Any ROM just works" matters more than "no emulated CPU in the app".** The apps ship a
  small ARM7TDMI interpreter that runs only the code the build did not recompile. Native
  recompiled code stays the fast path, and code that ran interpreted becomes native at the
  next build.
- **BT4E is the only commercial test game for now.** The builder picks the rest of the test
  corpus (within the constraints below).
- **The Windows app:** you open it and play the game natively, with keyboard keys standing
  for the GBA's buttons.
- The design as played back (interpreter fallback, a run log, rebuilds that make logged code
  native, the testing approach) was confirmed with "you are on track".

Everything else below is the designer's call and is marked as such where it matters.

## Goals

1. `gbaport port roms/<game>.gba` builds both apps from a ROM it has never seen, with no
   `game.toml` and no recorded play.
2. A game never stops because the build missed code. That code runs interpreted, its
   address is logged, and the next build makes it native.
3. Code the game runs from RAM works however it got there: copied by DMA, CpuSet or a
   software loop, decompressed, swapped in as overlays at the same address, or modified by
   the game. The runtime never runs stale recompiled code.
4. The cartridge hardware commercial games use beyond the save chip works: the real-time
   clock, rumble, gyro, tilt and solar sensors. The serial port behaves as with no link
   partner connected, so games do not hang probing for one.
5. A compatibility report over a folder of ROMs says which ones boot, how far they get and
   how much code ran interpreted.
6. On the user's phone (Samsung Galaxy A16), BT4E holds 60 fps once its code is native.

## Non-goals

- iOS (Plan 9, still blocked: no Mac) and decompilation (Plan 10, still blocked: no API key).
- Link-cable multiplayer, e-Reader, GBA Video cartridges, MultiBoot (single-cart
  multiplayer).
- Save states.
- The BIOS's own sound driver (SWI 0x1A–0x1E, 0x20–0x24, 0x28–0x2A). Few games use it; it
  keeps warning once.
- The rare hardware corners found missing in the gap analysis: green swap, DMA video
  capture, Game Pak DRQ, CPU open bus for unmapped reads, ROM mirroring tricks (Classic NES
  Series), the interrupted code's resume address in `lr_irq` while native code runs. They
  stay as they are unless a test game needs one.
- 32-bit Android phones (armeabi-v7a). The user's phone is arm64; the Android emulator
  tests stay x86_64.
- Setting up another development machine. The tools stay as installed on this PC.

## Anti-goals

These would make the work a failure even if the rest works:

- The app silently running recompiled RAM code whose bytes the game has since changed.
- Native and interpreted code disagreeing: a game must draw the same pictures whether a
  piece of its code ran native or interpreted.
- BT4E getting slower on the phone once its code is native, or `gbaport verify` getting
  worse than today for BT4E (3600 frames: 1211 pictures in the same order, at most 1 frame
  apart).
- Needing someone to play the whole game on the development PC before the apps work.
- Committing any ROM-derived bytes: ROMs, saves, RAM code bytes, recompiled code, or apps
  containing the ROM.

## Constraints (carried over)

- Never commit ROM-derived bytes. New ROM-derived outputs (`dist/`, logged RAM code) go to
  git-ignored places.
- Public test ROMs are downloaded at a pinned commit into the temp ROM cache and never
  committed. Their licence is checked first.
- mGBA and Unicorn are development-time oracles only. Neither is linked into an app.
- The development machine is Windows with Smart App Control on. Smart App Control blocks
  `uv.exe` and `gbaport.exe`, so tools run as `.venv\Scripts\python.exe -m gbaport.cli`.
  Freshly built programs may be refused, so the salted rebuilds stay.
- Each plan is written as its own document, validated, and approved by the user before
  it is carried out. The user picks inline execution.

## Changes to the base spec

- "Out of scope: zero-input support for every ROM. Each game is expected to need a small
  `game.toml`" is replaced by goal 1: `game.toml` becomes optional, a place for overrides.
- "Out of scope: any runtime interpreter or JIT" and key decision 4 ("No runtime fallback")
  are replaced by the interpreter fallback below. There is still no JIT.
- Key decision 5 stands: emulators remain development-time oracles. The shipped
  interpreter is gbaport's own C code, not an emulator core taken from elsewhere.
- The desktop host stops being only a development host: the Windows app is a deliverable.

## Design

### 1. The fallback interpreter

A C11 interpreter for ARMv4T (ARM and Thumb) inside the runtime (designer's call:
`runtime/interp.c`). It works on the same `GbaCtx` as recompiled code: the same registers,
flags, banked registers and modes, the same `gba_read*`/`gba_write*` memory accessors, the
same BIOS calls, and the same helpers in `lift/gba_cpu.h` for mode switches, MSR and
exception returns.

**Where it starts.** At present, `gba_missing` either unwinds to an outer call or fails. It
fails instead of running the interpreter only for an undefined instruction. `gba_missing`
returns a `GbaFn`, so it can return an interpreter entry that starts at the missing
address. The `gba_call` protocol does not change.

**Where it stops.** The interpreter follows the same call and return rules as recompiled
code, so the C stack, `call_depth`, `rets[]` and the unwinding of task switches behave the
same:

- a call (`bl`, `mov lr, pc` + jump) runs a nested `gba_call`, as lifted code does;
- a jump to the current call's return address returns it, as a lifted return does;
- a jump to an address that has recompiled code returns that address, so the dispatcher
  runs native code again;
- any other jump keeps interpreting.

A jump into the middle of a recompiled function is not an entry in the dispatch table, so
the interpreter runs the rest of that function. It is slower but correct, and the address
is logged.

**Modes.** The dispatch table is keyed by `addr & ~1`. When a recompiled function's state
(ARM or Thumb) differs from the state the jump asks for, that is treated as missing code,
so the dispatch table needs to know each entry's state.

**Interrupts.** The interpreter checks `ctx->cycles >= ctx->next_event` wherever lifted
code would: at loop heads (targets of taken backward branches and of computed jumps) and
at exits. Interrupts delivered while interpreting run the game's handler through
`gba_call`, as now.

**Timing.** Each interpreted instruction costs exactly the cycles its recompiled version
would. Today the lifter computes fetch costs at build time (`lift/function.py`) and the C
helpers add data waits. The interpreter computes the same fetch costs at run time, so
moving code between native and interpreted does not shift the game's timing.

**Risk (Plan 12):** recompiled code checks for due events at loop heads and function exits,
and both depend on where functions begin and end. Learning a new entry moves them. To
match exactly, recompiled code may have to place its checks by a rule that does not depend
on function boundaries, for example at every backward-branch target and computed-jump
target in the ROM. The interpreter then uses the same rule. Plan 12 settles this first,
with the native/interpreted picture-hash oracle below as its test.

**Speed target.** On the PC, headless, BT4E with every function interpreted runs at least
as fast as the GBA does (60 frames a second). There is no target on the phone: interpreted
code is expected to be 10–30× slower than native, and a part of a game played for the
first time may stutter there until the next build. The builder picks the techniques, for
example caching decoded instructions per address. Any such cache must be invalidated by
the RAM write tracking in section 3.

**Testing.** The interpreter has the same oracles as the lifter, and one more:

- Unicorn's per-instruction differential tests run through the interpreter too.
- jsmolka's CPU test ROMs pass fully interpreted (only the entry point recompiled) and
  mixed (a subset of functions recompiled).
- **New oracle:** a game gives the same picture hash each frame, and the same cycle count,
  native and fully interpreted. This is checked on test ROMs exactly and on BT4E for 3600
  frames. A build switch (designer's call: `--interpret-all`) makes the runtime treat every
  address as missing, so this can be tested.
- An undefined instruction still stops the game with the message it gives today.

### 2. The run log, and learning from it

Every address the interpreter enters from the dispatcher is logged once per run. That
includes jumps into the middle of functions, interrupt handlers and code in RAM. For code
in RAM, the entry also carries the bytes it ran, because they are not in the ROM. RAM
bytes are ROM-derived, so they stay next to the save file and never go into git.

- The log sits next to the save, alongside today's `.session.input` recording: on the PC
  in the save's folder, on the phone in the app's storage. It is written at the same moments
  the save is: once a second while it changes, when the game stops, and when the phone app
  goes to the background. The builder decides the file format. Designer's call: a text
  file of `arm|thumb <address>` lines, plus one binary file per RAM blob, named by its
  hash.
- When it closes, the window prints how many places ran interpreted and that `gbaport
  learn` or `gbaport port` makes them native.
- `gbaport learn roms/<game>.gba` with no `--input` reads the PC's log.
  - `--device` pulls the phone's log and RAM blobs, as it pulls recordings today.
  - ROM addresses go into `games/<code>/learned.toml`, which holds addresses only and is
    committed, as now.
  - RAM blobs are copied to `games/<code>/build/ramcode/` (git-ignored). `learned.toml`
    refers to them by address, state and hash. A blob missing locally is skipped with a
    note.
  - There is no replay, so one rebuild covers every logged address.
- The current replay-based `learn` (`--input`/`--save`) stays for recordings.
- `gbaport port` and `gbaport build` first learn from the PC's log when one exists, so
  playing and then rebuilding is enough on the PC (designer's call).

### 3. Code in RAM, by content

Recompiled RAM code is trusted only while RAM still holds the bytes it was compiled from.

- **At build time.** Each recompiled function in EWRAM or IWRAM records the byte ranges
  its blocks cover and a hash of those bytes. Several functions may now exist for the same
  RAM address, one per set of bytes (overlays). `analysis/space.py`'s rule that rejects
  overlapping `ram_code` blobs is lifted for blobs that come from the run log, and the
  dispatcher picks among them by hash.
- **At run time.** The runtime keeps a per-page "holds recompiled code" map for EWRAM and
  IWRAM (the builder picks the page size). Every write into such a page marks it dirty.
  That covers CPU stores, DMA, and the BIOS copy and decompression calls (CpuSet,
  CpuFastSet, LZ77, Huffman, RLE, Diff filters).
- **Before running RAM code from a dirty page,** the runtime hashes the function's bytes:
  - if they match, the page is marked clean and the native code runs;
  - otherwise, if another compiled variant for that address matches, that one runs;
  - otherwise the interpreter runs it and logs the bytes.
- Static detection of RAM copies (DMA and CpuSet with constant operands) stays, as an
  optimisation. It is no longer needed for correctness: devkitARM- and Butano-style
  start-up code that copies `.iwram` code with a software loop gets interpreted on the
  first run and recompiled after `learn`.
- **Known limit:** a recompiled function that rewrites its own instructions while it runs
  is not caught mid-function. The builder may send functions whose own pages get written
  while they run to the interpreter. Either way, this is documented.

### 4. No per-game setup

- The sweep is on by default (`config.py`: `sweep` defaults to true). The pointer scan
  stays on. A `game.toml` can still turn either off.
- **Save type.** The ROM string scan stays (`rom/savetype.py`). When no marker string is
  found, the runtime detects the type from the game's first access, as mGBA does: Flash by
  its command sequence, SRAM by plain accesses, EEPROM by DMA to its address. The config
  override stays.
- **Cartridge hardware detection.** The real-time clock is detected by the Nintendo
  library's `SIIRTC_V` marker string. The gyro, tilt, solar and rumble devices are detected
  by a small table of game codes. A table of codes is metadata, not ROM bytes; it may be
  taken from mGBA's override list, crediting it.
- **Per-game folder.** The per-game folder stays `games/<code>/` and is created when first
  needed. A blank or invalid game code (common in homebrew) uses `games/H<first 8 hex of
  sha1>/` instead (designer's call).
- **BT4E.** Its `game.toml` loses its list of entry addresses (goal 1 acceptance) and keeps
  only `sha1` and `sweep`.

### 5. Cartridge hardware and the serial port

Each of these is checked against mGBA (as the timing and sound are) with self-built test
ROMs. The `mgbaref` reference may need hooks to set the sensor values.

- **The GPIO port at 0x080000C4–0x080000C9.**
  - **Real-time clock** (Seiko S-3511A protocol): the time comes from the host's clock.
  - **Rumble:** the phone vibrates, or a gamepad rumbles through SDL.
  - **Gyro** (WarioWare: Twisted!): the phone's gyroscope; two keys on the PC.
  - **Solar sensor** (Boktai): a light level the player sets. Designer's call: two keys
    raise and lower it, on the PC and on a gamepad.
- **Tilt sensor** (Kirby Tilt 'n' Tumble; at 0x0E008000–0x0E0085FF): the phone's
  accelerometer, with keys on the PC.
- **Serial port.** With no link partner: transfers end as mGBA ends them with nothing
  connected, including the serial interrupt, and multiplayer mode reports no partner.
- **Flash.** More chip IDs, for example Macronix, may be added if a test game needs them.

### 6. The apps

**`gbaport port roms/<game>.gba [--windows] [--android] [--install]`** builds both apps by
default. It first learns from the PC's run log, then writes them to `dist/<code>/`, which
is git-ignored because the apps contain the ROM.

**Windows app:**
- A GUI program with no console window. The ROM is embedded, so a double-click starts the
  game. The current command-line options stay for development builds.
- Saves, the run log and the play recording go in `%APPDATA%\gbaport\<code>\`.
- Keys: today's layout (arrows; X = A, Z = B, A = L, S = R, Enter = Start,
  Backspace = Select), plus gamepads. F11 or Alt+Enter switches to fullscreen. An optional
  key file beside the save remaps keys (designer's call).
- The window title is the game's title.
- An error before or during play is shown in a message box instead of on a console.

**Android app:**
- A release-signed APK. The key is made once on this PC, stored in
  `%LOCALAPPDATA%\gbaport\android\`, and never committed. So the APK installs by copying
  it to the phone, and an update keeps the save.
- The app stays debuggable (designer's call; personal use), because `learn --device`
  reads the app's storage with `run-as`, and Android allows that only for debuggable apps.
- Moving an installed app from the debug key to the release key needs one uninstall, which
  deletes the save. `gbaport port --install` backs the save up from the phone first and
  restores it after the new install.
- `versionCode` goes up with each build.
- A plain gbaport icon (no game art). arm64-v8a, plus x86_64 for the emulator tests.
- The run log goes in the app's storage, where `learn --device` finds it.

### 7. The compatibility report and the test corpus

**`gbaport survey <folder> [--frames N] [--verify]`** ports each ROM headless and runs it
twice for N frames: once with no input, and once with a simple script that presses Start
and A now and then (the builder picks the script). For each ROM it reports:
- the number of functions built;
- frames run, and why it stopped if it did;
- whether the picture ever changed (it boots);
- the share of instructions that ran interpreted, and the places logged;
- with `--verify`, agreement with mGBA over the first frames.

It prints a table and writes JSON under `build/survey/`.

**The corpus**, within the constraints (licence checked, pinned, untracked):
- BT4E;
- jsmolka's ROMs (already used);
- the mGBA test suite, if its licence allows;
- self-built C test ROMs for each pattern this design adds:
  - a devkitARM-style start-up that copies IWRAM code with a software loop;
  - two code overlays at the same IWRAM address;
  - code decompressed into EWRAM with LZ77;
  - code the game modifies in RAM;
  - a ROM whose save type has no marker string;
  - one ROM per new hardware piece;
- open-source homebrew ROMs if suitable ones with clear licences can be found. The builder
  decides, and may leave them out.

### 8. Phone speed

The drafted Plan 8b, "Phone speed and fixes", goes first. It was prototyped and validated
on 2026-10-25 (968 tests), and has not been executed. It speeds up the renderer, splits the
phone's frame report into running, drawing and showing, and fixes the minor findings
deferred from Plans 8 and 7c. Its document and prototype exist outside the repository; the
document is moved into `docs/superpowers/plans/` and revalidated on today's main before it
is approved.

The interpreter adds no cost to native code: its checks run only on a miss and on writes
to pages that hold recompiled RAM code. The phone's 60 fps is measured after learning.

## Acceptance for the whole roadmap, on BT4E

1. With `games/BT4E/game.toml` reduced to `sha1` and `sweep`, `gbaport port
   roms/mygame.gba` builds both apps.
2. On that first build, `walk-right.input` (60000 frames) and `first-fight.input` play to
   their ends without stopping. The interpreter may run.
3. After `gbaport learn` from that run's log and a rebuild, the same two replays run with
   no interpreted instructions, and `gbaport verify` is no worse than today.
4. Native and fully interpreted (`--interpret-all`) give the same picture hash each frame
   for 3600 frames.
5. On the user's phone, after learning: 59.5 fps or better in the first fight.
6. The Windows app starts with a double-click and plays with the keyboard, and the save
   survives a restart. The APK installs by copying it to the phone, and the save survives
   an update.
7. `gbaport survey` runs over the corpus and writes its report.

## Roadmap

Each plan is written after the previous one is finished. The order is the designer's call:
speed first, so the interpreter is measured against a fast native build; the user-facing
apps come after the game never stops.

| Plan | Deliverable | Acceptance |
|---|---|---|
| 8b Phone speed and fixes (drafted) | Faster renderer, frame report split, deferred minors | As in its document; suite green; BT4E verify unchanged |
| 12 Fallback interpreter | `runtime/interp.c`, state-aware dispatch, `--interpret-all`, the run log, `learn` from logs (PC and `--device`) | Acceptance items 2–4 on test ROMs and BT4E (with BT4E's entry list removed for the test) |
| 13 Code in RAM by content, no per-game setup | Hashed RAM functions and variants, write tracking, sweep on by default, runtime save detection, BT4E's entry list deleted | Corpus RAM-code test ROMs pass first run interpreted and second run native; item 1 |
| 14 Compatibility report | `gbaport survey`, the corpus downloads and the remaining test ROMs | Item 7 |
| 15 Cartridge hardware | GPIO (clock, rumble, gyro, solar), tilt sensor, serial port with no partner, phone sensors and rumble | Each matches mGBA on its test ROM; phone sensors drive them on the emulator |
| 16 The apps | `gbaport port`, Windows GUI app with the ROM embedded, release-signed APK | Items 5 and 6 |

## Left to the builder

- The interpreter's internals (decoding, any decode cache, how the event checks are
  placed), as long as timing matches recompiled code exactly.
- The page size and hash of the RAM write tracking.
- The run log's file format, and when RAM bytes are captured.
- The survey's input script and its JSON format.
- The PC keys for the gyro, tilt and solar sensors, and the format of the remapping file.
- What the serial port returns with no partner: whatever mGBA does.
- The homebrew part of the corpus.

## Designer's calls, for the user to check

- Plan 8b goes first, before the interpreter.
- `gbaport port` and `build` learn from the PC's run log by themselves.
- The sweep is on by default for every game.
- A blank game code uses a folder named after the ROM's sha1.
- The Windows app embeds the ROM and keeps saves in `%APPDATA%`, not beside the ROM.
- The Android app gets a release key made on this PC, so APKs install by copying. It
  stays debuggable so `learn --device` can read its log.
- The BIOS sound driver, link multiplayer, save states and 32-bit phones are out.
