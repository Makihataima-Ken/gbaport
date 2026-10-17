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
- **Calls.** A direct `BL` becomes a direct C call. Indirect branches (`BX reg`, `LDR pc`,
  `MOV pc`, `POP {pc}`) go through `gba_dispatch(ctx, target)`, a sorted address→function
  table. A miss aborts with the address and the hint to add it to `game.toml`.
- **Returns.** Each function records the link register at entry. An indirect branch to that
  value returns from the C function; any other indirect branch is a tail call routed through
  a trampoline loop so long state-machine chains cannot overflow the C stack.
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

[[ram_code]]                   # blobs copied from ROM to RAM and executed there
rom = 0x080F0000
ram = 0x03000000
size = 0x800
mode = "arm"

[timing]
model = "block"                # "block" (default) or "frame"
```

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
| P2 Code discovery | `gbaport analyze` → `analysis.json` (functions, blocks, modes, jump tables, literal pools, RAM-copied code); `game.toml` loader; trace import | Synthetic programs give exact expected CFGs; coverage report on a real dump | P1 |
| P3 Lifter | `gbaport recompile` → C per function + dispatch table; instruction semantics incl. flags, shifter carry, conditional execution, PC-relative rules | Unicorn differential tests for every ARMv4T operation; snippet programs match end state | P2 |
| P4 Runtime core + desktop host | C runtime (memory map, I/O, BIOS HLE, DMA, timers, scheduler/IRQ, saves) + SDL3 desktop window | Self-built test ROMs run natively with expected results; CPU test ROMs pass when recompiled | P3 |
| P5 Renderer | Scanline renderer, all modes/features, per-line latching | Reference-image tests on graphics test ROMs | P4 |
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4 |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P5, P6 |
| P8 Android | Gradle/NDK project generated per game, touch overlay, controller, lifecycle, saves | APK runs on device at 60 fps; save survives app kill | P7 |
| P9 iOS | Xcode project via CMake generator, signing, same features as Android | IPA runs on device at 60 fps | P7, needs macOS |
| P10 Decomp loop | Override mechanism, Ghidra headless export, Claude agent loop, function-level differential tester | Functions replaced with tests passing; game still verifies | P7 |
| P11 Symbolized data (optional) | ROM tables → C structs, GBA pointers → native symbols in decompiled code | Decompiled modules no longer use raw GBA addresses | P10 |

## Toolchain

Already on the development machine (Windows 11): uv 0.11.32 with CPython 3.13.14, Git 2.51,
MSVC Build Tools 14.44 (bundles CMake), OpenJDK 17, Node 26.

Needed later:

- LLVM/clang + lld (`winget install LLVM.LLVM`) — Plan 3.
- CMake ≥ 3.28 and Ninja (`winget install Kitware.CMake Ninja-build.Ninja`) — Plans 3–4.
- SDL3 (fetched by CMake `FetchContent`) — Plan 4.
- Android SDK + NDK r27 or newer (Android Studio or `sdkmanager`) — Plan 8.
- macOS with Xcode 16 or newer, or a macOS CI runner, plus an Apple developer account — Plan 9.
- Ghidra (check the release's required JDK; recent releases need a newer JDK than 17) — Plan 10.

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
- **Legal**: personal use only; ROM-derived data stays out of version control.

## Open questions

- Which game comes first (needed by Plan 7)? Does a community decompilation already exist?
- Is a Mac (or macOS CI) available for iOS builds (Plan 9)?
- Claude API key and budget for the decompilation agent (Plan 10).
