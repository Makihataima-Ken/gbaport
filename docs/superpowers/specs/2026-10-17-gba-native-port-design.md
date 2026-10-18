# GBA Native Port Pipeline — Design

Date: 2026-10-17 · Status: draft, awaiting review

## Purpose

A personal-use toolchain that turns a Game Boy Advance ROM, dumped from a cartridge the
user owns, into a native Android and iOS app. No emulator ships inside the app:

1. The game's ARM7TDMI machine code is statically recompiled into C and compiled for arm64.
2. The GBA hardware (display, sound, DMA, timers, interrupts, save chip, BIOS) is replaced by
   a native C runtime plus a thin platform layer (window, input, audio, lifecycle).
3. An optional AI-assisted stage rewrites the generated C into readable C, one function at a
   time, each change gated by a differential test (functional decompilation, not matching).

## Scope

In scope:

- ROM ingest, ARMv4T (ARM + Thumb) decoding, code discovery, recompilation to C.
- Native runtime replacing the GBA hardware, desktop host for development, Android and iOS hosts.
- A verification harness that proves the native build behaves like the original.
- A per-function decompilation loop driven by an LLM agent with automated verification.

Out of scope:

- Distributing games or anything derived from a ROM. ROMs, saves and extracted data are
  never committed to the repository.
- Matching (byte-identical) decompilation.
- Zero-input support for every ROM. Each game is expected to need a small `game.toml`.
- Any runtime interpreter or JIT. Code the recompiler did not find is a build-time error
  that names the address, fixed by adding it to `game.toml` (or by importing a trace).

## Key decisions

1. **Recompile first, decompile incrementally.** Static recompilation gives a natively
   running game early; readable C replaces generated C function by function while the game
   stays playable. Stopping at any point still leaves a working native app.
2. **Functional, not matching, decompilation.** Equivalence is proven by differential tests,
   not by reproducing the original compiler's bytes. Far cheaper and far more automatable.
3. **Guest addresses stay 32-bit values.** Generated code never turns GBA addresses into
   host pointers; every memory access goes through `gba_read*/gba_write*` with a page table
   keyed by `addr >> 24`. This sidesteps the 64-bit pointer problem and the fact that iOS
   arm64 reserves the whole low 4 GB (`__PAGEZERO`), so GBA addresses cannot be mapped 1:1.
   Readable decompiled functions use the same accessors until their data is symbolized.
4. **No runtime fallback.** Unknown indirect-branch targets abort with the address. Coverage
   comes from static analysis, recorded traces and per-game overrides.
5. **Emulators are dev-time test oracles only.** Unicorn (CPU semantics) and mGBA
   (whole-game lockstep) are used by tests and tools, never linked into a shipped app.
6. **Python tooling, C11 runtime, clang everywhere.** Analysis and code generation are
   Python 3.13 (managed by uv). Generated code and runtime are C11 built with clang — the
   same compiler family the Android NDK and Xcode use.
7. **SDL3 platform layer** for window, input, audio and app lifecycle on desktop, Android
   and iOS, so one host codebase serves all three.
8. **BIOS reimplemented in C** (SWI 0x00–0x2A as used by games). No Nintendo BIOS needed.
9. **No ROM-derived bytes in git.** Tests use synthetic ROMs assembled at test time.

## Architecture

```
 user ROM (.gba)          games/<code>/game.toml  (per-game overrides)
       │                          │
       ▼                          ▼
 ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌───────────┐
 │ 1 ingest │──►│ 2 decode │──►│ 3 analyze    │──►│ 4 lift    │──► generated C
 │ header,  │   │ ARM +    │   │ CFG, funcs,  │   │ Instr→C,  │    + dispatch table
 │ save type│   │ Thumb    │   │ jump tables, │   │ functions │
 └──────────┘   └──────────┘   │ RAM code,    │   └───────────┘
                               │ traces       │          │
                               └──────────────┘          ▼
                    ┌──────────────────────────────────────────────┐
                    │ 5 runtime (C11): memory map, I/O registers,  │
                    │   BIOS HLE, DMA, timers, scheduler + IRQs,   │
                    │   renderer, audio mixer, save chips          │
                    └──────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────────────┐
              ▼                          ▼                          ▼
      6a desktop host (SDL3)     6b Android (SDL3+NDK)       6c iOS (SDL3+Xcode)
              │
              ▼
      7 verify: lockstep vs mGBA oracle on recorded inputs (dev only)
              │
              ▼
      8 decomp loop: agent rewrites one function → differential test → keep or retry
```

The stages are exposed through one CLI, `gbaport`, with subcommands such as `info`, `disasm`,
`analyze`, `recompile`, `build`, `verify` and `decomp`.

## Runtime model (detailed in Plans 3–6)

- **CPU context.** `GbaCpu { uint32_t r[16]; bool n, z, c, v; uint32_t mode; banked regs; }`
  inside `GbaCtx`, passed to every generated function `void f_08001234(GbaCtx *ctx)`.
  Register values live in the struct; clang keeps hot ones in host registers inside a function.
- **Calls.** Every recompiled function returns the guest address execution continues at.
  A call site sets LR and runs `gba_call(ctx, next, return_address)`: a loop that looks up
  each returned address in a sorted address→function table (`gba_lookup`) and runs it, until
  the chain comes back to the call's return address. A direct `BL` to a recompiled function
  starts the loop with a direct C call. A lookup miss aborts with the address and the hint
  to add it to `game.toml`.
- **Returns.** A return is just a jump to the return address, so it ends the C call that
  made it; tail calls and jumps through registers return their target and never grow the C
  stack. Comparing against the call site's return address, rather than the LR a function was
  entered with, also handles code that sets LR itself before jumping (`ldr lr, =main; b init`).
  Calls that never come back (`bl` used as a jump inside a loop) would nest C calls without
  end, so nesting deeper than `GBA_MAX_CALL_DEPTH` (1024) aborts through the runtime's
  `gba_call_overflow` with the return address.
- **Memory.** Region page table (`addr >> 24`) with fast paths for EWRAM, IWRAM, VRAM, OAM,
  palette and ROM; I/O-register writes call handlers (DMA start, timer reload, IRQ ack).
- **Timing.** Not cycle-accurate. Each generated basic block adds a compile-time cycle
  estimate to `ctx->cycles`; loop back-edges and function returns check
  `ctx->cycles >= ctx->next_event` and run the scheduler, which advances scanlines and
  delivers HBlank/VBlank/timer/DMA interrupts by calling the recompiled IRQ handler (address
  read from 0x03007FFC). Wait points (`Halt`, `IntrWait`, `VBlankIntrWait`, and recognised
  busy-wait loops on `VCOUNT`/`DISPSTAT`/`IF`) fast-forward to the next event. VBlank start
  is the frame boundary: present the frame, sync to the display.
- **Renderer.** Scanline software renderer in C reproducing GBA compositing (modes 0–5,
  sprites, affine, windows, blending, mosaic), with per-scanline register latching so raster
  effects work. Output 240×160 RGBA, upscaled by the GPU in the host. A GPU tile renderer
  is a later optional enhancement.
- **Audio.** Four PSG channels plus the two DMA FIFOs sampled at timer overflow, mixed at
  32768 Hz and resampled to the device rate.
- **Saves.** SRAM, Flash (with its command state machine) and EEPROM (serial protocol over
  DMA) modelled at the memory-access level, because game code drives the chip protocol
  directly. Persisted to a file per game.
- **Input.** Touch overlay and game controllers write `KEYINPUT`.

## Per-game configuration

`games/<game_code>/game.toml` (committed; contains addresses, never ROM bytes):

```toml
[rom]
sha1 = "…"                     # the dump this config was written against
save = "flash128k"             # override auto-detection when needed

[code]
entries = [0x08000204, 0x080A1C30]          # extra function entry points
thumb_entries = [0x08012345]
data = [[0x08100000, 0x08180000]]           # ranges that are never code
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]  # at = the dispatch instruction
scan_pointers = true           # guess entries from ROM words pointing at function starts

[[ram_code]]                   # blobs copied from ROM to RAM and executed there
rom = 0x080F0000
ram = 0x03000000
size = 0x800
mode = "arm"

[timing]
model = "block"                # "block" (default) or "frame"
```

Traces recorded with `gbaport trace` live next to it in `games/<game_code>/traces/*.trace`
(addresses only) and are read automatically. Code the game copies into RAM with DMA or
CpuSet is detected and needs a `[[ram_code]]` entry only when detection misses it.

## Verification strategy

| Stage | Oracle | Method |
|---|---|---|
| Decoders (Plan 1) | Keystone assembler | Assemble → decode → format → re-assemble must give identical bytes; exhaustive/random totality tests |
| Analysis (Plan 2) | Hand-built test programs | Expected function/block sets for synthetic ROMs; coverage report on real dumps |
| Lifter (Plan 3) | Unicorn (ARM926 model, pre-ARMv6 semantics) | Per-instruction differential tests with random operands; snippet end-state equality |
| Runtime (Plans 4–6) | Self-built test ROMs (clang `--target=armv4t-none-eabi` + `ld.lld`) and public GBA test suites (licence checked before vendoring) | Expected outputs and reference images |
| Whole game (Plan 7+) | mGBA (dev only) | Per-frame framebuffer and RAM comparison on recorded input sequences |
| Decomp (Plan 10) | The recompiled function | Same inputs/state → same outputs/state, on states captured from real play |

## Roadmap

Each plan is written as its own document after the previous one is finished, because each
depends on what the earlier stages reveal.

| Plan | Deliverable | Acceptance | Depends on |
|---|---|---|---|
| P1 Foundation | Repo, ROM ingest, ARMv4T ARM+Thumb decoders, formatter, `gbaport info` / `gbaport disasm` | Keystone round-trip corpus passes; decoders total over all Thumb halfwords and 200k random ARM words; CLI works on a real dump | — |
| P2 Code discovery | `gbaport analyze` → `analysis.json` (functions, blocks, modes, jump tables, literal pools, RAM-copied code); `game.toml` loader | Synthetic programs give exact expected CFGs; coverage report on a real dump | P1 |
| P2b Discovery coverage | Pointer scan, RAM-copy detection, trace files and their import, `gbaport trace` through mGBA's GDB server | Synthetic programs and a fake GDB server give exact results; dump coverage report before and after | P2 |
| P3 Lifter | `gbaport recompile` → C per function + dispatch table; instruction semantics incl. flags, shifter carry, conditional execution, PC-relative rules | Unicorn differential tests for every ARMv4T operation; snippet programs match end state | P2 |
| P4a Runtime core | C runtime (memory map, I/O registers, scanline scheduler and interrupts, timers, DMA, the BIOS calls that control the CPU), `gbaport build`, headless host | Self-built test ROMs run natively with the expected results | P3 |
| P4b BIOS and saves | The other BIOS functions (arithmetic, copies, decompression, affine), SRAM/Flash/EEPROM with save files | BIOS results match reference values; save test ROMs pass and their saves persist | P4a |
| P4c Desktop host | SDL3 window, input, frame pacing, keypad wake-up | CPU test ROMs pass when recompiled; a test ROM runs in a window | P4a |
| P5 Renderer | Scanline renderer, all modes/features, per-line latching | Reference-image tests on graphics test ROMs | P4a |
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4c |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6 |
| P8 Android | Gradle/NDK project generated per game, touch overlay, controller, lifecycle, saves | APK runs on device at 60 fps; save survives app kill | P7 |
| P9 iOS | Xcode project via CMake generator, signing, same features as Android | IPA runs on device at 60 fps | P7, needs macOS |
| P10 Decomp loop | Override mechanism, Ghidra headless export, Claude agent loop, function-level differential tester | Functions replaced with tests passing; game still verifies | P7 |
| P11 Symbolized data (optional) | ROM tables → C structs, GBA pointers → native symbols in decompiled code | Decompiled modules no longer use raw GBA addresses | P10 |

## Toolchain

Already on the development machine (Windows 11): uv 0.11.32 with CPython 3.13.14, Git 2.51,
MSVC Build Tools 14.44 (bundles CMake), OpenJDK 17, Node 26, LLVM 23.1.3 (clang + lld,
installed for Plan 3).

Needed later:

- Unicorn 2.1.3 (Python dev dependency, the lifter's oracle) — added in Plan 3.
- CMake ≥ 3.28 and Ninja (bundled with the MSVC Build Tools; elsewhere
  `winget install Kitware.CMake Ninja-build.Ninja`) — Plan 4c. Plan 4a builds with clang
  directly.
- SDL3 (fetched by CMake `FetchContent`) — Plan 4c.
- Android SDK + NDK r27 or newer (Android Studio or `sdkmanager`) — Plan 8.
- macOS with Xcode 16 or newer, or a macOS CI runner, plus an Apple developer account — Plan 9.
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.
- mGBA 0.10 or newer with its GDB server, dev machine only (`gbaport trace`) — Plan 2b.

## Risks

- **Timing-sensitive games** (raster effects, audio streaming, VCOUNT polling): mitigated by
  the block-cycle scheduler and per-game timing knobs; some titles will need tuning.
- **Code created at runtime** (RAM-copied or self-modifying): trace import plus `ram_code`
  entries; unknown blobs fail loudly at build time.
- **Indirect-branch coverage**: jump-table recognition, traces, overrides.
- **Non-standard control flow** (tail calls, returns to non-LR addresses, lone Thumb BL
  halves used as long calls): trampoline dispatcher and explicit decoder support.
- **Performance**: per-access memory dispatch; mitigated by region fast paths. The GBA
  workload (16.78 MHz CPU) is small for a modern phone.
- **Windows Smart App Control** refuses some freshly built, unsigned programs for good,
  judged by their content: `gbaport build` re-links a refused program with a random
  unused string until Windows takes it.
- **Legal**: personal use only; ROM-derived data stays out of version control.

## Open questions

- Which game comes first (needed by Plan 7)? Does a community decompilation already exist?
- Is a Mac (or macOS CI) available for iOS builds (Plan 9)?
- Claude API key and budget for the decompilation agent (Plan 10).
