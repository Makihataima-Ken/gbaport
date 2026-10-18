# Plan 4a: Runtime Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompiled games run natively without a window. A C runtime replaces the GBA's memory map, I/O registers, scanline timing, interrupts, timers, DMA and the BIOS calls that control the CPU. `gbaport build` compiles a game together with that runtime into a program. Self-checking test ROMs, built from C at test time, prove each part.

**Architecture:**
- **Runtime** (`src/gbaport/runtime/`, C11). A `GbaRuntime` holds the guest CPU state (`GbaCtx`), the memory and I/O registers, and the scheduler, timer and DMA state. It implements every hook `gba_cpu.h` declares:
  - `runtime.c`: start-up, the run loop, resets and runtime errors;
  - `memory.c`: the memory map;
  - `io.c`: the I/O registers;
  - `scheduler.c`: scanlines, timed events, interrupt delivery and Halt;
  - `timers.c` and `dma.c`;
  - `bios.c`: the SWI calls;
  - `host_headless.c`: the `main` of a program that runs without a window.
- **Timing.** Recompiled blocks add cycle estimates to `ctx->cycles`. The scheduler turns cycles into scanlines: 1232 cycles a line, the HBlank flag and interrupt at cycle 1008, and 228 lines a frame. Events are due times. `gba_events` runs the due events, then delivers an interrupt the way the BIOS does: switch to IRQ mode, push r0-r3, r12 and lr, call `[0x03007FFC]` with lr = 0x138, pop, and set CPSR = SPSR.
- **Build.** `gbaport.native` adds `gba_rom.c` to the generated sources. That file records the entry point and the ROM's size and CRC32, and the runtime refuses any other ROM. `gbaport.native` then compiles the generated sources with the runtime and a host, using clang with parallel jobs. `gbaport build ROM` = recompile + compile, into `games/<code>/build/<code>.exe`.
- **Misses name the CPU state.** Exits from Thumb code carry bit 0 of the target address, so "no recompiled code at X" can say "(Thumb state) ... add it to thumb_entries".
- **Tests.** Test ROMs in `tests/gbaroms` are C plus a small crt0, built with `clang --target=armv4t-none-eabi` and `ld.lld`. Their game.toml is written from the ELF's function symbols, so the tests depend on the runtime, not on what discovery finds. Each ROM checks itself against GBATEK's values, prints `PASS`/`FAIL` lines through mGBA's debug-log registers and ends with the BIOS Stop call. The headless program prints the log and exits with a status.

**Scope:** the spec's P4 row is split into three plans. Each is its own subsystem with its own tests, and together they would make a plan three times this size. Task 6 records the split in the spec's roadmap.
- **P4a (this plan):** the runtime core.
- **P4b:** the BIOS functions 0x06-0x2A, and saves (SRAM, Flash, EEPROM) with persistence.
- **P4c:** the SDL3 desktop host (window, input, pacing, keypad wake) and the public CPU test ROMs.

**Tech Stack:** C11 (clang `-std=c11 -O2 -Wall -Werror`), Python 3.13 (stdlib at runtime), pytest. LLVM 23.1.3 provides clang, ld.lld and llvm-objcopy, which build the test ROMs.

**Spec:** `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`. The parts this plan implements are the roadmap row P4, the "Runtime model" section (Memory, Timing) and the Runtime row of "Verification strategy" (self-built test ROMs).

## Global Constraints

- Work on branch `feat/plan-04a-runtime-core`, cut from `main`.
- **Dependencies.** The Python runtime uses only the standard library; this plan adds no dependencies.
- **C code.** Generated code and the runtime are C11 and compile warning-free with `clang -std=c11 -O2 -Wall -Werror -Wno-unused-label`.
  - The runtime itself uses only `<stdint.h>`, `<string.h>`, `<setjmp.h>`, `<stdarg.h>` and `<stdio.h>` (for messages).
  - Hosts may use the rest of the C library.
- **Guest addresses stay 32-bit values.** Generated code reaches guest memory only through the `gba_read*`/`gba_write*` accessors (spec, key decision 3).
- **No runtime fallback.** Code the recompiler did not find ends the run with an error that names the address and says how to add it to `game.toml` (spec, key decision 4).
- **No ROM-derived bytes in git.** Test ROMs are compiled from C at test time. Build outputs go to `games/*/generated/` and `build/` (both git-ignored) or to the system temp folder.
- **Commits** are plain, authored as `Ken <ahmadsoud63@gmail.com>`, with no trailer of any kind.
- **This machine.** Windows Application Control blocks the `gbaport.exe` launcher that uv creates, so steps run the CLI as `uv run python -m gbaport.cli ...` (the same code). The programs `gbaport build` compiles are not blocked.

## Review Focus

1. **Interrupt handlers that let other interrupts in.** Sound engines and Nintendo's multiple-interrupt sample code do this. The nested interrupt must arrive, and both handlers must return to the right place with SPSR and lr intact. Pinned in Task 3 (`nesting_handler` in `gbaroms/interrupts.c`).
2. **SoftReset called from inside an interrupt handler.** Games check the reset key combination in their VBlank handler. The game must start again in system mode, and no stale C frames may run. Pinned in Task 3 (`gbaroms/reset_in_irq.c`).
3. **One 32-bit store that covers two registers.** Examples are IE+IF at 0x04000200 and a DMA channel's count and control. Each half must follow its own register's rules. Pinned in Task 3 (the `32-bit store` checks) and Task 5 (every DMA start is one 32-bit store of count and control).
4. **BIOS interrupt waits called with IME off.** The BIOS turns IME on itself, so a game that relies on that must not hang. Pinned in Task 3 (`vblank wait turns IME on`).
5. **Timer reads after an overflow is due but before the scheduler has run.** Fast timers are common in sound and timing code. The count must stay inside the reload period. Pinned in Task 4 (`a fast timer never reads below its reload value`).

## Known limitations (deliberate; later plans)

- The HLE interrupt entry pushes 0 as lr_irq, because C code does not know the resume address. Handlers that read or rewrite the stacked lr (thread switchers) are not supported. A lockstep comparison (P7) must mask those IRQ-stack words.
- **Busy-waits are not fast-forwarded.** Loops that wait on VCOUNT or DISPSTAT run at full cost; skipping ahead to the next event is performance work for P7.
- **Stop always ends a headless run**, because there is no keypad yet to wake it. Keypad wake-up and KEYCNT interrupts come in P4c.
- **Missing BIOS functions and saves.** The BIOS functions 0x06-0x2A end the run with an error, and the cartridge save area reads 0. Both come in P4b.
- **Special-timing DMA.** Sound-FIFO and video-capture DMA are never triggered; the sound FIFOs come in P6.
- **Code rewritten in RAM.** Code that the game rewrites in RAM while it runs keeps running as the recompiled version.
- **No wait states.** Memory wait states are not modelled; cycle estimates are per instruction.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/gbaport/runtime/gba_runtime.h` (new) | `GbaRuntime`, `GbaHost`, `GbaEnd`, register and interrupt constants, the runtime's internal API |
| `src/gbaport/runtime/runtime.c` (new) | `gba_init` (ROM check), `gba_run` (power-on, SoftReset loop), `gba_end`, `gba_fail`, the miss, undefined-instruction and call-overflow hooks |
| `src/gbaport/runtime/memory.c` (new) | `gba_read8/16/32`, `gba_write8/16/32`: regions, mirrors, byte-write rules, ROM open bus, BIOS reads, the mGBA debug log |
| `src/gbaport/runtime/io.c` (new) | Register reset values, `gba_io_read`, `gba_io_write` |
| `src/gbaport/runtime/scheduler.c` (new) | Scanlines, DISPSTAT/VCOUNT, events, `gba_events`, interrupt delivery, `gba_halt` |
| `src/gbaport/runtime/timers.c` (new) | Timer counters, overflow events, count-up cascade |
| `src/gbaport/runtime/dma.c` (new) | DMA start, immediate/VBlank/HBlank transfers, repeat |
| `src/gbaport/runtime/bios.c` (new) | `gba_swi`: SoftReset, RegisterRamReset, Halt, Stop, IntrWait, VBlankIntrWait |
| `src/gbaport/runtime/host_headless.c` (new) | `main`: `game ROM [--frames N]`, debug log to stdout, exit status |
| `src/gbaport/native/toolchain.py` (new) | `find_clang`, `llvm_tool`, `ToolchainError` |
| `src/gbaport/native/build.py` (new) | `rom_identity`, `generated_sources`, `write_sources`, `compile_native` |
| `src/gbaport/lift/function.py`, `program.py` | Exits carry the Thumb state in bit 0; the lookup passes it to `gba_missing` |
| `src/gbaport/cli.py` | `gbaport build`; `recompile` writes `gba_rom.c` too |
| `tests/gbaroms/*` (new) | crt0, linker script, testlib, and one C file per test ROM |
| `tests/romtest.py` (new) | Build a test ROM and its game.toml; build and run it natively (`Run`) |
| `tests/runtime/test_*.py` (new) | One test module per part of the runtime |
| `tests/test_build_cli.py` (new) | The `build` command |

---

### Task 1: Test-ROM toolchain

**Files:**
- Create: `src/gbaport/native/__init__.py`, `src/gbaport/native/toolchain.py`
- Create: `tests/gbaroms/crt0.s`, `tests/gbaroms/gba.ld`, `tests/gbaroms/testlib.h`, `tests/gbaroms/testlib.c`, `tests/gbaroms/hello.c`, `tests/romtest.py`
- Modify: `tests/liftkit.py` (its `clang()` becomes `gbaport.native.toolchain.find_clang`)
- Test: `tests/runtime/test_romkit.py`

**Interfaces:**
- Consumes: `parse_config` (`gbaport.analysis.config`), `parse_header` (`gbaport.rom.header`), `RomImage`.
- Produces:
  - `find_clang() -> str` and `llvm_tool(name) -> str`, which raise `ToolchainError(OSError)` when a tool is missing.
  - In `tests/romtest.py`:
    - constants `ROMS`, `CACHE`, `TARGET`, `CFLAGS`;
    - `TestRom(data: bytes, config: str)`;
    - `build_test_rom(name) -> TestRom`, which builds `gbaroms/<name>.c` with crt0 and testlib;
    - `elf_symbols(elf) -> {name: (value, type)}` and `config_for(symbols) -> str`.
  - The testlib API (`testlib.h`):
    - logging and checks: `print`, `check`, `expect`, `test_end`;
    - interrupts: `irq_init`, plus the counters `irq_count[14]` and `irq_cpsr`;
    - CPU and timing helpers: `get_cpsr`, `set_cpsr_control`, `wait_vcount`, `bios_halt`, `bios_vblank_wait`, `bios_intr_wait`;
    - register macros (`REG_*`, `MEM*`, `BIOS_IF`, `IRQ_VECTOR`) and `IRQ_*` bits.
- **Test ROM layout:**
  - **Header:** game code `ATST`, entry point 0x080000C0.
  - **Memory:** code and constants live in ROM. ARM code and data go in an `.iwram` section that crt0 copies to 0x03000000. BSS is in IWRAM.
  - **Stacks:** system 0x03007F00, IRQ 0x03007FA0.
  - **Pass/fail counts:** kept at 0x03007F00/04, an area RegisterRamReset never clears.

- [ ] **Step 1: Create the branch**

```bash
cd /c/Users/J-ASUS/Dev/GBA
git checkout -b feat/plan-04a-runtime-core
```

- [ ] **Step 2: Write the failing tests**

Create `tests/runtime/test_romkit.py`:
```python
from romtest import build_test_rom

from gbaport.analysis.config import parse_config
from gbaport.rom.header import parse_header
from gbaport.rom.image import RomImage


def test_a_test_rom_has_a_valid_header_and_entry_branch():
    rom = build_test_rom("hello")
    header = parse_header(RomImage(rom.data))
    assert header.game_code == "ATST"
    assert header.checksum_ok
    assert header.entry_point == 0x080000C0  # crt0's start, after the 0xC0-byte header


def test_the_config_lists_every_function_and_the_iwram_code():
    config = parse_config(build_test_rom("hello").config)
    assert config.scan_pointers is False
    assert len(config.thumb_entries) >= 8  # main, print, check, expect, ... are Thumb
    assert all(0x08000000 <= addr < 0x08010000 for addr in config.thumb_entries)
    assert 0x03000000 in config.entries  # the IRQ handler: ARM code in IWRAM
    (blob,) = config.ram_code
    assert (blob.ram, blob.mode.value) == (0x03000000, "arm")
    assert 0x08000000 < blob.rom < 0x08010000 and blob.size > 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/runtime/test_romkit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'romtest'`

- [ ] **Step 4: Write the toolchain, the test-ROM sources and the kit**

Create `src/gbaport/native/__init__.py`:
```python
"""Compiling recompiled games into native programs."""
```

Create `src/gbaport/native/toolchain.py`:
```python
"""Finding clang: $GBAPORT_CLANG, then PATH, then the LLVM installer's Windows location."""

import os
import shutil
from pathlib import Path

WINDOWS_LLVM = Path(r"C:\Program Files\LLVM\bin\clang.exe")


class ToolchainError(OSError):
    """A compiler or tool the build needs is missing or failed."""


def find_clang() -> str:
    found = os.environ.get("GBAPORT_CLANG") or shutil.which("clang")
    if found:
        return found
    if WINDOWS_LLVM.exists():
        return str(WINDOWS_LLVM)
    raise ToolchainError("clang not found: install LLVM (winget install LLVM.LLVM) or set GBAPORT_CLANG")


def llvm_tool(name: str) -> str:
    """Another LLVM tool (ld.lld, llvm-objcopy) from the directory clang is in."""
    folder = Path(find_clang()).parent
    for candidate in (folder / f"{name}.exe", folder / name):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise ToolchainError(f"{name} not found next to clang ({folder})")
```

Create `tests/gbaroms/crt0.s`:
```asm
@ Start-up code for the runtime test ROMs: header, stacks, IWRAM copy, BSS, then main.
@ The header fields after the entry branch are filled in by tests/romtest.py.

    .section .crt0, "ax"
    .arm
    .global _start
_start:
    b       start
    .space  0xBC                @ header: logo (left zero), title, codes, checksum

start:
    mov     r0, #0xD2           @ IRQ mode, interrupts off
    msr     cpsr_c, r0
    ldr     sp, =0x03007FA0
    mov     r0, #0x1F           @ system mode, interrupts on
    msr     cpsr_c, r0
    ldr     sp, =0x03007F00

    ldr     r0, =__iwram_lma    @ copy the IWRAM sections (code and data) from ROM
    ldr     r1, =__iwram_start
    ldr     r2, =__iwram_end
1:  cmp     r1, r2
    ldrlo   r3, [r0], #4
    strlo   r3, [r1], #4
    blo     1b

    ldr     r1, =__bss_start    @ clear BSS
    ldr     r2, =__bss_end
    mov     r3, #0
2:  cmp     r1, r2
    strlo   r3, [r1], #4
    blo     2b

    ldr     r0, =main
    mov     lr, pc
    bx      r0
    swi     #0x030000           @ main returned: Stop
3:  b       3b
```

Create `tests/gbaroms/gba.ld`:
```ld
/* Linker script for the runtime test ROMs: code and constants in ROM, IWRAM sections
 * (ARM code and data) copied there by crt0, BSS in IWRAM below the stacks. */
ENTRY(_start)

MEMORY {
    rom   (rx)  : ORIGIN = 0x08000000, LENGTH = 32M
    iwram (rwx) : ORIGIN = 0x03000000, LENGTH = 0x7000
}

SECTIONS {
    .text : {
        KEEP(*(.crt0))
        *(.text .text.*)
        *(.rodata .rodata.*)
        . = ALIGN(4);
    } > rom

    .iwram : {
        __iwram_start = .;
        *(.iwram .iwram.*)
        *(.data .data.*)
        . = ALIGN(4);
        __iwram_end = .;
    } > iwram AT > rom
    __iwram_lma = LOADADDR(.iwram);

    .bss (NOLOAD) : {
        __bss_start = .;
        *(.bss .bss.* COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > iwram

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}
```

Create `tests/gbaroms/testlib.h`:
```c
/* testlib.h - registers, logging and checks for the runtime test ROMs.
 *
 * Results go to mGBA's debug log (0x04FFF600), which the native runtime prints and mGBA
 * shows too, so a test ROM can run on both. A test ends with test_end(): it prints the
 * summary line and executes the BIOS Stop call, which ends a headless run. */
#ifndef TESTLIB_H
#define TESTLIB_H

#include <stdint.h>

#define REG16(addr) (*(volatile uint16_t *)(addr))
#define REG32(addr) (*(volatile uint32_t *)(addr))
#define MEM8(addr) (*(volatile uint8_t *)(addr))
#define MEM16(addr) (*(volatile uint16_t *)(addr))
#define MEM32(addr) (*(volatile uint32_t *)(addr))

#define REG_DISPCNT  REG16(0x04000000)
#define REG_DISPSTAT REG16(0x04000004)
#define REG_VCOUNT   REG16(0x04000006)
#define REG_DMA_SAD(n) REG32(0x040000B0 + 12 * (n))
#define REG_DMA_DAD(n) REG32(0x040000B4 + 12 * (n))
#define REG_DMA_CNT(n) REG32(0x040000B8 + 12 * (n))
#define REG_DMA_CNT_H(n) REG16(0x040000BA + 12 * (n))
#define REG_TM_CNT_L(n) REG16(0x04000100 + 4 * (n))
#define REG_TM_CNT_H(n) REG16(0x04000102 + 4 * (n))
#define REG_KEYINPUT REG16(0x04000130)
#define REG_IE       REG16(0x04000200)
#define REG_IF       REG16(0x04000202)
#define REG_WAITCNT  REG16(0x04000204)
#define REG_IME      REG16(0x04000208)
#define BIOS_IF      MEM16(0x03007FF8)
#define IRQ_VECTOR   MEM32(0x03007FFC)

enum {
    IRQ_VBLANK = 1, IRQ_HBLANK = 2, IRQ_VCOUNT = 4, IRQ_TIMER0 = 8,
    IRQ_DMA0 = 0x100, IRQ_KEYPAD = 0x1000,
};

/* Counted by the IRQ handler that irq_init() installs; irq_cpsr is the CPSR it ran with. */
extern volatile uint32_t irq_count[14];
extern volatile uint32_t irq_cpsr;

void print(const char *fmt, ...);      /* %d %u %x %08x %s */
void check(const char *name, int ok);  /* PASS/FAIL line */
void expect(const char *name, uint32_t got, uint32_t want);
void test_end(void);                   /* summary line, then Stop */
void irq_init(void);                   /* install the counting handler, IME = 1 */
uint32_t get_cpsr(void);               /* ARM code: MRS and MSR do not exist in Thumb */
void set_cpsr_control(uint32_t value);  /* MSR cpsr_c */
void wait_vcount(uint32_t line);       /* busy-wait until VCOUNT == line */

static inline void bios_halt(void) { __asm__ volatile("svc #2" ::: "r0", "r1", "r2", "r3", "memory"); }
static inline void bios_vblank_wait(void)
{
    __asm__ volatile("svc #5" ::: "r0", "r1", "r2", "r3", "memory");
}
static inline void bios_intr_wait(uint32_t discard, uint32_t flags)
{
    register uint32_t r0 __asm__("r0") = discard;
    register uint32_t r1 __asm__("r1") = flags;
    __asm__ volatile("svc #4" : "+r"(r0), "+r"(r1) :: "r2", "r3", "memory");
}

#endif
```

Create `tests/gbaroms/testlib.c`:
```c
#include <stdarg.h>

#include "testlib.h"

#define DEBUG_STRING ((volatile char *)0x04FFF600)
#define DEBUG_FLAGS  REG16(0x04FFF700)
#define DEBUG_ENABLE REG16(0x04FFF780)

volatile uint32_t irq_count[14];
volatile uint32_t irq_cpsr;
/* The counts sit just above the system stack (it grows down from 0x03007F00) and far
 * below the IRQ stack's top (0x03007FA0): RegisterRamReset never clears this area, and
 * SoftReset clears it before a test has counted anything. */
#define passed MEM32(0x03007F00)
#define failed MEM32(0x03007F04)

/* ---- what clang may call on its own in freestanding ARMv4T code ------------------ */

void *memcpy(void *dst, const void *src, unsigned n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *memset(void *dst, int value, unsigned n)
{
    uint8_t *d = dst;
    while (n--) *d++ = (uint8_t)value;
    return dst;
}

typedef struct { unsigned quot, rem; } udiv_t;

static udiv_t udivmod(unsigned n, unsigned d)
{
    udiv_t r = {0, 0};
    for (int bit = 31; bit >= 0; bit--) {
        r.rem = (r.rem << 1) | ((n >> bit) & 1);
        if (r.rem >= d) { r.rem -= d; r.quot |= 1u << bit; }
    }
    return r;
}

unsigned __aeabi_uidiv(unsigned n, unsigned d) { return udivmod(n, d).quot; }

int __aeabi_idiv(int n, int d)
{
    unsigned q = udivmod(n < 0 ? -(unsigned)n : (unsigned)n, d < 0 ? -(unsigned)d : (unsigned)d).quot;
    return (n < 0) != (d < 0) ? -(int)q : (int)q;
}

/* ---- the mGBA debug log ----------------------------------------------------------- */

static void emit(const char *text)
{
    DEBUG_ENABLE = 0xC0DE;
    int i = 0;
    for (; text[i] && i < 255; i++) DEBUG_STRING[i] = text[i];
    DEBUG_STRING[i] = 0;
    DEBUG_FLAGS = 0x100 | 3;  /* print at "info" level */
}

static char *put_number(char *out, uint32_t value, unsigned base, int width)
{
    char digits[11];
    int n = 0;
    do { digits[n++] = "0123456789abcdef"[value % base]; value /= base; } while (value);
    while (n < width) digits[n++] = '0';
    while (n) *out++ = digits[--n];
    return out;
}

void print(const char *fmt, ...)
{
    char line[256], *out = line, *end = line + sizeof line - 12;
    va_list args;
    va_start(args, fmt);
    for (const char *p = fmt; *p && out < end; p++) {
        if (*p != '%') { *out++ = *p; continue; }
        int width = 0;
        while (p[1] >= '0' && p[1] <= '9') width = width * 10 + (*++p - '0');
        switch (*++p) {
        case 'd': {
            int v = va_arg(args, int);
            if (v < 0) { *out++ = '-'; v = -v; }
            out = put_number(out, (uint32_t)v, 10, width);
            break;
        }
        case 'u': out = put_number(out, va_arg(args, uint32_t), 10, width); break;
        case 'x': out = put_number(out, va_arg(args, uint32_t), 16, width); break;
        case 's':
            for (const char *s = va_arg(args, const char *); *s && out < end; s++) *out++ = *s;
            break;
        default: *out++ = *p; break;
        }
    }
    va_end(args);
    *out = 0;
    emit(line);
}

void check(const char *name, int ok)
{
    if (ok) passed++; else failed++;
    print("%s %s", ok ? "PASS" : "FAIL", name);
}

void expect(const char *name, uint32_t got, uint32_t want)
{
    if (got == want) {
        passed++;
        print("PASS %s", name);
    } else {
        failed++;
        print("FAIL %s: got 0x%08x, want 0x%08x", name, got, want);
    }
}

void test_end(void)
{
    print("DONE %u passed, %u failed", passed, failed);
    __asm__ volatile("svc #3");  /* Stop: the end of a headless run */
}

/* ---- interrupts ------------------------------------------------------------------- */

/* Called by the BIOS in ARM state, in IRQ mode; it must acknowledge what it handled. */
__attribute__((target("arm"), section(".iwram"), noinline)) static void irq_handler(void)
{
    uint32_t cpsr;
    __asm__ volatile("mrs %0, cpsr" : "=r"(cpsr));
    irq_cpsr = cpsr;
    uint16_t flags = REG_IE & REG_IF;
    for (int i = 0; i < 14; i++)
        if (flags & (1u << i)) irq_count[i]++;
    REG_IF = flags;
    BIOS_IF |= flags;
}

void irq_init(void)
{
    for (int i = 0; i < 14; i++) irq_count[i] = 0;
    IRQ_VECTOR = (uint32_t)irq_handler;
    REG_IME = 1;
}

__attribute__((target("arm"), noinline)) uint32_t get_cpsr(void)
{
    uint32_t value;
    __asm__ volatile("mrs %0, cpsr" : "=r"(value));
    return value;
}

__attribute__((target("arm"), noinline)) void set_cpsr_control(uint32_t value)
{
    __asm__ volatile("msr cpsr_c, %0" ::"r"(value) : "memory");
}

void wait_vcount(uint32_t line)
{
    while (REG_VCOUNT != line) {}
}
```

Create `tests/gbaroms/hello.c`:
```c
/* The smallest test ROM: one log line, one check, then Stop. */
#include "testlib.h"

int main(void)
{
    print("hello from the GBA");
    expect("arithmetic", 6u * 7u, 42u);
    test_end();
    return 0;
}
```

Create `tests/romtest.py`:
```python
"""Build the runtime test ROMs from C.

A test ROM is ``gbaroms/crt0.s`` + ``gbaroms/testlib.c`` + one test file from
``gbaroms``, compiled with clang for the ARM7TDMI (Thumb, like games) and linked with
ld.lld. Its game.toml lists every function symbol in the ELF as an entry and the IWRAM
section as RAM code, so tests that run it depend on the runtime and the lifter, not on
how much code discovery finds by itself.

ROMs are cached in the system temp folder by the hash of their sources.
"""

import hashlib
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gbaport.native.toolchain import find_clang, llvm_tool

ROMS = Path(__file__).parent / "gbaroms"
CACHE = Path(tempfile.gettempdir()) / "gbaport-romcache"
TARGET = ["--target=armv4t-none-eabi", "-mcpu=arm7tdmi"]
# No jump tables: clang's Thumb switch tables are a pattern discovery does not know (games are
# built with GCC or ARM's compiler), and these ROMs test the runtime, not discovery.
CFLAGS = [*TARGET, "-mthumb", "-O2", "-ffreestanding", "-fno-builtin", "-fno-jump-tables",
          "-Wall", "-Werror"]
STT_FUNC = 2


@dataclass(frozen=True)
class TestRom:
    data: bytes
    config: str  # game.toml text


def _digest(*parts: bytes | str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode() if isinstance(part, str) else part)
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{Path(command[0]).name} failed:\n{result.stderr[-4000:]}")


def elf_symbols(elf: bytes) -> dict[str, tuple[int, int]]:
    """Name -> (value, type) for every named symbol of a little-endian ELF32 file."""
    shoff, = struct.unpack_from("<I", elf, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", elf, 0x2E)
    sections = [struct.unpack_from("<10I", elf, shoff + i * shentsize) for i in range(shnum)]
    symbols = {}
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        strtab = sections[section[6]]
        for offset in range(section[4], section[4] + section[5], 16):
            name, value, _, info = struct.unpack_from("<IIIB", elf, offset)
            start = strtab[4] + name
            text = elf[start : elf.index(b"\0", start)].decode()
            if text:
                symbols[text] = (value, info & 0xF)
    return symbols


def config_for(symbols: dict[str, tuple[int, int]]) -> str:
    """game.toml: every function as an entry (odd values are Thumb), IWRAM as RAM code."""
    functions = [value for value, kind in symbols.values() if kind == STT_FUNC]
    arm = sorted(v for v in functions if not v & 1)
    thumb = sorted(v - 1 for v in functions if v & 1)
    start, end = symbols["__iwram_start"][0], symbols["__iwram_end"][0]
    lines = [
        "[code]",
        f"entries = [{', '.join(hex(v) for v in arm)}]",
        f"thumb_entries = [{', '.join(hex(v) for v in thumb)}]",
        "scan_pointers = false",
    ]
    if end > start:
        lines += [
            "", "[[ram_code]]", f"rom = {symbols['__iwram_lma'][0]:#x}", f"ram = {start:#x}",
            f"size = {end - start:#x}", 'mode = "arm"',
        ]
    return "\n".join(lines) + "\n"


def _with_header(image: bytes) -> bytes:
    rom = bytearray(image)
    rom[0xA0:0xAC] = b"GBAPORTTEST\0"
    rom[0xAC:0xB0] = b"ATST"
    rom[0xB0:0xB2] = b"01"
    rom[0xB2] = 0x96
    rom[0xBD] = (-(sum(rom[0xA0:0xBD]) + 0x19)) & 0xFF
    return bytes(rom)


def build_test_rom(name: str) -> TestRom:
    """Compile ``gbaroms/<name>.c`` with crt0 and testlib into a ROM and its game.toml."""
    sources = [ROMS / "crt0.s", ROMS / "testlib.c", ROMS / f"{name}.c"]
    inputs = [ROMS / "gba.ld", ROMS / "testlib.h", *sources]
    folder = CACHE / "roms" / _digest(*(path.read_bytes() for path in inputs), *CFLAGS)
    rom_path, config_path = folder / "game.gba", folder / "game.toml"
    if not rom_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        objects = []
        for source in sources:
            obj = folder / f"{source.stem}.o"
            flags = TARGET if source.suffix == ".s" else CFLAGS
            _run([find_clang(), *flags, f"-I{ROMS}", "-c", str(source), "-o", str(obj)])
            objects.append(str(obj))
        elf = folder / "game.elf"
        _run([llvm_tool("ld.lld"), "-T", str(ROMS / "gba.ld"), *objects, "-o", str(elf)])
        binary = folder / "game.bin"
        _run([llvm_tool("llvm-objcopy"), "-O", "binary", str(elf), str(binary)])
        config_path.write_text(config_for(elf_symbols(elf.read_bytes())), encoding="utf-8")
        rom_path.write_bytes(_with_header(binary.read_bytes()))
    return TestRom(rom_path.read_bytes(), config_path.read_text(encoding="utf-8"))
```

In `tests/liftkit.py`, replace:
```python
import shutil
import struct
```
with:
```python
import struct
```

In `tests/liftkit.py`, replace:
```python
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage
```
with:
```python
from gbaport.lift.program import lift_program
from gbaport.native.toolchain import find_clang as clang
from gbaport.rom.image import RomImage
```

In `tests/liftkit.py`, replace:
```python
def clang() -> str:
    found = shutil.which("clang") or r"C:\Program Files\LLVM\bin\clang.exe"
    if not Path(found).exists():
        raise RuntimeError("clang not found: install LLVM (winget install LLVM.LLVM)")
    return found


def lift_cases(cases: list[Case]) -> str:
```
with:
```python
def lift_cases(cases: list[Case]) -> str:
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/runtime/test_romkit.py -v && uv run pytest && uv run ruff check src tests`
Expected: 2 passed; the whole suite is 536 passed; ruff clean. The first run compiles the hello ROM, which takes about 2 s.

- [ ] **Step 6: Commit**

```bash
git add src/gbaport/native tests/gbaroms tests/romtest.py tests/runtime/test_romkit.py tests/liftkit.py
git commit -m "feat: test ROMs built from C with clang and ld.lld"
```

---

### Task 2: Runtime core, native build and the headless host

**Files:**
- Create the runtime:
  - `src/gbaport/runtime/__init__.py`, `gba_runtime.h`, `runtime.c`, `memory.c`, `io.c`, `scheduler.c`, `bios.c`, `host_headless.c`.
  - `io.c`, `scheduler.c` and `bios.c` grow in Tasks 3-5.
- Create: `src/gbaport/native/build.py`
- Create test ROMs: `tests/gbaroms/mem_map.c`, `bios_calls.c`, `err_swi.c`, `err_missing.c`, `forever.c`
- Modify:
  - `src/gbaport/lift/function.py`, `src/gbaport/lift/program.py` (the CPU state in bit 0);
  - `src/gbaport/cli.py` (`build`; `recompile` uses `gbaport.native.build`);
  - `tests/romtest.py` (running ROMs natively);
  - `tests/test_recompile_cli.py`, `tests/lift/test_program.py`.
- Test: `tests/runtime/test_core.py`, `tests/test_build_cli.py`

**Interfaces:**
- Consumes:
  - Task 1's `find_clang` and `build_test_rom`;
  - `lift_program`, `program_files`, `HEADER` (`gbaport.lift.program`);
  - `gba_cpu.h` (`GbaCtx`, `gba_call`, the hooks it declares);
  - `analyze_rom`, `parse_config`, `parse_header`.
- **Produces, in C** (`gba_runtime.h`):
  - Types: `GbaRuntime`, `GbaHost {frame, log, diag, user}`, `GbaEnd` (`GBA_END_STOPPED = 0`, `GBA_END_ERROR = 3`, `GBA_END_HOST = 4`).
  - For hosts: `gba_init(rt, rom, size, host) -> int`, `gba_run(rt) -> GbaEnd`, `gba_end(rt, why)`, `gba_set_keys`, `gba_crc32`.
  - Inside the runtime:
    - control: `gba_fail(rt, fmt, ...)`, `gba_reset(rt)`, `gba_reset_io(rt)`;
    - registers: `gba_io_read(rt, offset)`, `gba_io_write(rt, offset, value, mask)`;
    - scheduling: `gba_scheduler_start`, `gba_reschedule`, `gba_request_irq(rt, bits)`;
    - declared now but defined in later tasks: `gba_irq_changed`, `gba_halt` (Task 3), `gba_timer_*` (Task 4), `gba_dma_*` (Task 5).
  - Generated by recompile (`gba_rom.c`): `gba_rom_entry`, `gba_rom_size`, `gba_rom_crc32`.
- **Produces, in Python** (`gbaport.native.build`): `rom_identity(data)`, `generated_sources(lifted, rom_data) -> {name: text}`, `write_sources(files, out)`, `compile_native(sources, out, name, host="headless") -> Path`, `RUNTIME`, `RUNTIME_SOURCES`, `CFLAGS`.
- **Produces, test side** (`tests/romtest.py`): `Run(status, lines, stderr)` with `failures` and `assert_passed()`; `native_program(rom)`, `run_rom(rom, frames=600, rom_file=None)`, `run_test(name, frames=600)`.
- **Headless program:**
  - Command line: `<program> ROM [--frames N]`.
  - Output: debug-log lines go to stdout; warnings and errors go to stderr.
  - Exit status:

    | Status | Meaning |
    |---|---|
    | 0 | Stop |
    | 2 | bad arguments or the wrong ROM |
    | 3 | runtime error |
    | 4 | frame limit |
- `gbaport build ROM [--config] [--trace]... [--out DIR]` writes `DIR/generated/` and `DIR/build/<game_code>(.exe)`. The default `DIR` is `games/<game_code>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/gbaroms/mem_map.c`:
```c
/* The memory map: mirrors, byte-write rules, ROM open bus, BIOS reads, I/O register rules.
 * Expected values are GBATEK's. */
#include "testlib.h"

int main(void)
{
    /* The BIOS area reads as the last opcode the BIOS fetched: 0xE129F000 after start-up,
     * 0xE3A02004 after a BIOS call (here RegisterRamReset with nothing selected). */
    expect("bios read after start-up", MEM32(0x00000000), 0xE129F000);
    __asm__ volatile("movs r0, #0\n svc #1" ::: "r0", "r1", "r2", "r3", "memory");
    expect("bios read after a SWI", MEM32(0x00000100), 0xE3A02004);
    expect("bios halfword read", MEM16(0x00000002), 0xE3A0);

    MEM32(0x02000010) = 0x11223344;
    expect("ewram mirror (256 KiB)", MEM32(0x02040010), 0x11223344);
    expect("ewram mirror (end of page)", MEM32(0x02FC0010), 0x11223344);
    MEM32(0x03000100) = 0x55667788;
    expect("iwram mirror (32 KiB)", MEM32(0x03008100), 0x55667788);
    MEM32(0x03007FF0) = 0xCAFEF00D;
    expect("iwram top mirror (0x03FFFFxx)", MEM32(0x03FFFFF0), 0xCAFEF00D);

    MEM8(0x05000003) = 0x12;
    expect("palette byte write fills the halfword", MEM16(0x05000002), 0x1212);
    expect("palette mirror", MEM16(0x05000402), 0x1212);

    REG_DISPCNT = 0;  /* tile mode: BG VRAM is 0x06000000-0x0600FFFF */
    MEM8(0x06000001) = 0x34;
    expect("bg vram byte write fills the halfword", MEM16(0x06000000), 0x3434);
    MEM16(0x06010000) = 0xAAAA;
    MEM8(0x06010000) = 0x55;
    expect("obj vram ignores byte writes", MEM16(0x06010000), 0xAAAA);
    REG_DISPCNT = 3;  /* bitmap mode: BG VRAM reaches 0x06013FFF */
    MEM8(0x06010000) = 0x55;
    expect("bitmap mode bg vram takes bytes", MEM16(0x06010000), 0x5555);
    MEM16(0x06014000) = 0xBBBB;
    MEM8(0x06014000) = 0x66;
    expect("bitmap mode obj vram ignores bytes", MEM16(0x06014000), 0xBBBB);
    REG_DISPCNT = 0x80;
    expect("vram mirror of obj vram (0x06018000)", MEM16(0x06018000), 0x5555);
    expect("vram mirror (128 KiB)", MEM16(0x06020000), 0x3434);

    MEM16(0x07000010) = 0x1357;
    MEM8(0x07000010) = 0x99;
    expect("oam ignores byte writes", MEM16(0x07000010), 0x1357);
    expect("oam mirror", MEM16(0x07000410), 0x1357);

    uint32_t first = MEM32(0x08000000);
    expect("rom starts with the entry branch", first >> 24, 0xEA);
    expect("rom mirror (wait state 1)", MEM32(0x0A000000), first);
    expect("rom mirror (wait state 2)", MEM32(0x0C000000), first);
    MEM16(0x08000000) = 0;
    expect("rom ignores writes", MEM32(0x08000000), first);
    expect("open bus past the rom (halfword)", MEM16(0x08FFFFF0), 0xFFF8);
    expect("open bus past the rom (word)", MEM32(0x08FFFFF0), 0xFFF9FFF8);
    expect("open bus past the rom (byte)", MEM8(0x08FFFFF3), 0xFF);
    expect("unmapped region reads 0", MEM32(0x01000000), 0);

    expect("keyinput: no keys pressed", REG_KEYINPUT, 0x03FF);
    expect("keyinput low byte", MEM8(0x04000130), 0xFF);
    expect("keyinput high byte", MEM8(0x04000131), 0x03);
    REG_IE = 0xFFFF;
    expect("ie has 14 bits", REG_IE, 0x3FFF);
    MEM8(0x04000200) = 0x01;
    expect("byte write to ie keeps the other byte", REG_IE, 0x3F01);
    REG_IE = 0;
    REG_IME = 0xFFFF;
    expect("ime has 1 bit", REG_IME, 1);
    REG_IME = 0;
    REG_WAITCNT = 0xFFFF;
    expect("waitcnt bit 15 reads 0", REG_WAITCNT, 0x7FFF);
    REG_WAITCNT = 0;
    REG_DMA_SAD(3) = 0x02000000;
    expect("dma source is write-only", REG_DMA_SAD(3), 0);
    REG16(0x04000008) = 0x1F83;  /* BG0CNT reads back */
    expect("32-bit read of two registers", REG32(0x04000008), 0x00001F83);

    REG_DISPSTAT = 0xFFFF;
    expect("dispstat: writable bits and lyc", REG_DISPSTAT & 0xFF38, 0xFF38);
    REG_DISPSTAT = 0;
    uint16_t line = REG_VCOUNT;
    REG16(0x04000006) = 0x50;
    check("vcount is read-only", REG_VCOUNT < 228 && (REG_VCOUNT == line || REG_VCOUNT == line + 1));

    /* IF: a request stays until written back as 1. Enable the VBlank request but not IE. */
    REG_DISPSTAT = 0x0008;
    wait_vcount(161);
    expect("vblank requested in IF", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IF = 0;
    expect("writing 0 to IF keeps the request", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IF = IRQ_VBLANK;
    expect("writing 1 to IF clears it", REG_IF & IRQ_VBLANK, 0);
    REG_DISPSTAT = 0;

    test_end();
    return 0;
}
```

Create `tests/gbaroms/bios_calls.c`:
```c
/* The BIOS calls the runtime has so far: SoftReset, RegisterRamReset, and SWI numbers the
 * BIOS does not have (ignored). Halt, Stop and the interrupt waits are in interrupts.c. */
#include "testlib.h"

#define MARKER MEM32(0x0203FFF0)
#define MAGIC 0x52534554u

static void ram_reset(uint32_t flags)
{
    register uint32_t r0 __asm__("r0") = flags;
    __asm__ volatile("svc #1" : "+r"(r0) :: "r1", "r2", "r3", "memory");
}

int main(void)
{
    /* SoftReset starts the game again from its entry; the first run sets the stage. */
    if (MARKER != MAGIC) {
        MARKER = MAGIC;
        MEM32(0x02000100) = 0xA5A5A5A5;
        MEM32(0x03006000) = 0x87654321;
        MEM32(0x03007E40) = 0x12345678;
        set_cpsr_control(0x9F);  /* interrupts off: the reset turns them on again */
        __asm__ volatile("svc #0");
        print("FAIL SoftReset returned");
    }
    MARKER = 0;
    expect("soft reset keeps ewram", MEM32(0x02000100), 0xA5A5A5A5);
    expect("soft reset keeps iwram below 0x03007E00", MEM32(0x03006000), 0x87654321);
    expect("soft reset clears 0x03007E00-0x03007FFF", MEM32(0x03007E40), 0);
    expect("soft reset: system mode, interrupts on", get_cpsr() & 0xFF, 0x1F);

    MEM32(0x02000100) = 1;
    MEM32(0x03006000) = 2;
    MEM32(0x03007E40) = 3;
    MEM16(0x05000000) = 4;
    MEM16(0x06000000) = 5;
    MEM16(0x07000000) = 6;
    ram_reset(0x1F);
    expect("ram reset clears ewram", MEM32(0x02000100), 0);
    expect("ram reset clears iwram", MEM32(0x03006000), 0);
    expect("ram reset keeps 0x03007E00-0x03007FFF", MEM32(0x03007E40), 3);
    expect("ram reset clears palette", MEM16(0x05000000), 0);
    expect("ram reset clears vram", MEM16(0x06000000), 0);
    expect("ram reset clears oam", MEM16(0x07000000), 0);

    REG_IE = IRQ_VBLANK;
    REG_DISPCNT = 0x0403;
    REG16(0x04000080) = 0x1234;  /* SOUNDCNT_L */
    ram_reset(0x80);
    expect("register reset: forced blank", REG_DISPCNT, 0x0080);
    expect("register reset clears ie", REG_IE, 0);
    expect("register reset keeps sound registers", REG16(0x04000080), 0x1234);
    ram_reset(0x40);
    expect("sound reset clears sound registers", REG16(0x04000080), 0);

    __asm__ volatile("svc #0x2b");
    check("a SWI the BIOS does not have is ignored", 1);

    test_end();
    return 0;
}
```

Create `tests/gbaroms/err_swi.c`:
```c
/* Calls a BIOS function the runtime does not have yet (Div). */
#include "testlib.h"

int main(void)
{
    print("before");
    __asm__ volatile("svc #6" ::: "r0", "r1", "r2", "r3");
    print("after");
    test_end();
    return 0;
}
```

Create `tests/gbaroms/err_missing.c`:
```c
/* Calls an address where the recompiler found no code. */
#include "testlib.h"

int main(void)
{
    print("before");
    ((void (*)(void))0x08100001)();
    print("after");
    test_end();
    return 0;
}
```

Create `tests/gbaroms/forever.c`:
```c
/* Never stops, like a game's main loop. */
#include "testlib.h"

int main(void)
{
    for (;;) {}
    return 0;
}
```

Create `tests/runtime/test_core.py`:
```python
from romtest import build_test_rom, run_rom, run_test


def test_a_test_rom_runs_natively_and_reports_through_the_debug_log():
    run = run_test("hello")
    assert run.lines == ("hello from the GBA", "PASS arithmetic", "DONE 1 passed, 0 failed")
    run.assert_passed()


def test_the_memory_map():
    run_test("mem_map").assert_passed()


def test_bios_resets_and_unknown_calls():
    run = run_test("bios_calls")
    run.assert_passed()
    assert "ignoring SWI 0x2b" in run.stderr


def test_a_missing_bios_function_ends_the_run_with_its_number():
    run = run_test("err_swi")
    assert run.status == 3
    assert run.lines == ("before",)
    assert "BIOS function 0x06 is not implemented yet" in run.stderr


def test_a_jump_to_code_that_was_not_recompiled_names_the_address():
    run = run_test("err_missing")
    assert run.status == 3
    assert "no recompiled code at 0x08100000 (Thumb state" in run.stderr
    assert "thumb_entries" in run.stderr


def test_the_frame_limit_ends_a_game_that_never_stops():
    run = run_test("forever", frames=3)
    assert run.status == 4
    assert "stopped after 3 frames" in run.stderr


def test_a_build_refuses_a_different_rom():
    rom = build_test_rom("hello")
    other = bytearray(rom.data)
    other[-1] ^= 0xFF
    run = run_rom(rom, rom_file=bytes(other))
    assert run.status == 2
    assert "recompiled from a different ROM" in run.stderr
```

Create `tests/test_build_cli.py`:
```python
from romtest import build_test_rom, run_program

from gbaport.cli import main


def test_build_writes_sources_and_a_program_that_runs(tmp_path, capsys):
    rom = build_test_rom("hello")
    rom_path, config = tmp_path / "hello.gba", tmp_path / "game.toml"
    rom_path.write_bytes(rom.data)
    config.write_text(rom.config, encoding="utf-8")
    out = tmp_path / "out"
    assert main(["build", str(rom_path), "--config", str(config), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "lift issues  0" in printed
    assert (out / "generated" / "gba_rom.c").exists()
    (program,) = [p for p in (out / "build").iterdir() if p.stem == "ATST" and p.is_file()]
    assert f"built {program}" in printed
    result = run_program([str(program), str(rom_path)])
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "DONE 1 passed, 0 failed"
```

In `tests/test_recompile_cli.py`, replace:
```python
    names = sorted(path.name for path in generated.iterdir())
    assert names == ["gba_code_000.c", "gba_cpu.h", "gba_dispatch.c", "gba_program.h"]
    for source in ("gba_code_000.c", "gba_dispatch.c"):
        command = [clang(), "-std=c11", "-Wall", "-Werror", "-Wno-unused-label", "-c",
```
with:
```python
    names = sorted(path.name for path in generated.iterdir())
    assert names == ["gba_code_000.c", "gba_cpu.h", "gba_dispatch.c", "gba_program.h", "gba_rom.c"]
    for source in ("gba_code_000.c", "gba_dispatch.c", "gba_rom.c"):
        command = [clang(), "-std=c11", "-Wall", "-Werror", "-Wno-unused-label", "-c",
```

Append to `tests/lift/test_program.py`:
```python
def test_exits_carry_the_state_execution_continues_in():
    thumb = lifted("push {lr}\n    pop {pc}", thumb=True).functions[0x080000C0]
    assert "t |= 1u;" in thumb  # pop {pc} stays in Thumb state: bit 0 says so
    arm = lifted("ldr pc, [sp], #4").functions[0x080000C0]
    assert "t &= ~3u;" in arm
    dispatch = lifted(TWO_FUNCTIONS).dispatch
    assert "uint32_t key = addr & ~1u;" in dispatch
    assert "return gba_missing(ctx, addr);" in dispatch  # the runtime sees the state bit
```

In `tests/romtest.py`, replace:
```python
"""Build the runtime test ROMs from C.

A test ROM is ``gbaroms/crt0.s`` + ``gbaroms/testlib.c`` + one test file from
``gbaroms``, compiled with clang for the ARM7TDMI (Thumb, like games) and linked with
ld.lld. Its game.toml lists every function symbol in the ELF as an entry and the IWRAM
section as RAM code, so tests that run it depend on the runtime and the lifter, not on
how much code discovery finds by itself.

ROMs are cached in the system temp folder by the hash of their sources.
"""

import hashlib
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gbaport.native.toolchain import find_clang, llvm_tool
```
with:
```python
"""Build the runtime test ROMs from C, recompile them and run them natively.

A test ROM is ``gbaroms/crt0.s`` + ``gbaroms/testlib.c`` + one test file from
``gbaroms``, compiled with clang for the ARM7TDMI (Thumb, like games) and linked with
ld.lld. Its game.toml lists every function symbol in the ELF as an entry and the IWRAM
section as RAM code, so these tests depend on the runtime and the lifter, not on how
much code discovery finds by itself. A test ROM reports through mGBA's debug log (one
``PASS name`` or ``FAIL name: ...`` line per check, then ``DONE n passed, m failed``)
and ends with the BIOS Stop call.

ROMs and native builds are cached in the system temp folder by the hash of their sources.
"""

import hashlib
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.native.toolchain import find_clang, llvm_tool
from gbaport.rom.image import RomImage
```

Append to `tests/romtest.py`:
```python
# ---- running a test ROM natively --------------------------------------------------------


@dataclass(frozen=True)
class Run:
    status: int
    lines: tuple[str, ...]  # the debug log
    stderr: str

    @property
    def failures(self) -> list[str]:
        return [line for line in self.lines if line.startswith("FAIL")]

    def assert_passed(self) -> None:
        assert self.status == 0, f"exit status {self.status}: {self.stderr}\n" + "\n".join(self.lines)
        assert self.failures == [], "\n".join(self.lines)
        assert self.lines and self.lines[-1].startswith("DONE "), "\n".join(self.lines)


def native_program(rom: TestRom) -> Path:
    """Recompile ``rom`` and build it with the headless host (cached by the C sources)."""
    image = RomImage(rom.data)
    analysis = analyze_rom(image, parse_config(rom.config), ())
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    runtime = [path.read_bytes() for path in sorted(native.RUNTIME.glob("*.[ch]"))]
    flags = " ".join([*native.CFLAGS, *native.RUNTIME_SOURCES])
    sources = (f"{name}\n{text}" for name, text in sorted(files.items()))
    folder = CACHE / "native" / _digest(*sources, *runtime, flags)
    built = folder / "program.txt"  # written last: the build finished
    if not built.exists():
        native.write_sources(files, folder / "generated")
        program = native.compile_native(folder / "generated", folder / "build", "game")
        built.write_text(str(program), encoding="utf-8")
    return Path(built.read_text(encoding="utf-8"))


def run_program(command: list[str]) -> subprocess.CompletedProcess:
    """Run a native program. Windows' Smart App Control sometimes blocks a program the
    first time it starts after being built (WinError 4551); a later start works."""
    for attempt in range(5):
        try:
            return subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except OSError as error:
            if getattr(error, "winerror", None) != 4551 or attempt == 4:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def run_rom(rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set)."""
    program = native_program(rom)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    result = run_program([str(program), str(path), "--frames", str(frames)])
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)


def run_test(name: str, *, frames: int = 600) -> Run:
    return run_rom(build_test_rom(name), frames=frames)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/runtime tests/test_build_cli.py`
Expected: FAIL — 3 errors during collection: `ModuleNotFoundError: No module named 'gbaport.native.build'` (raised while importing `romtest`).

Run: `uv run pytest tests/test_recompile_cli.py tests/lift/test_program.py`
Expected: FAIL — 2 failed:
- `test_recompile_writes_sources_that_compile`, because `gba_rom.c` is not written;
- `test_exits_carry_the_state_execution_continues_in`, because `t |= 1u;` is not in the code.

- [ ] **Step 3: Write the runtime, the native build and the `build` command**

Create `src/gbaport/runtime/__init__.py`:
```python
"""The native runtime C sources (packaged with gbaport; compiled by gbaport.native)."""
```

Create `src/gbaport/runtime/gba_runtime.h`:
```c
/* gba_runtime.h - the native runtime that replaces the GBA hardware for recompiled code.
 *
 * A GbaRuntime owns the guest CPU state (GbaCtx), the memory, the I/O registers, the
 * scheduler, timers, DMA and the BIOS replacement. Recompiled code calls the hooks that
 * gba_cpu.h declares (memory accessors, gba_swi, gba_events, ...); the host creates one
 * runtime, gives it the ROM and its callbacks, and calls gba_run().
 *
 * Timing is estimated: every recompiled block adds its cycle estimate to ctx->cycles, and
 * the scheduler turns cycles into scanlines (1232 cycles each, 228 per frame), timer ticks
 * and interrupts. VBlank start is the frame boundary, where the host's frame callback runs.
 * Interrupts are delivered the way the BIOS does it: switch to IRQ mode, push r0-r3, r12
 * and lr on the IRQ stack, call the handler whose address is at 0x03007FFC with lr =
 * 0x138, then pop and return to the interrupted code. */
#ifndef GBA_RUNTIME_H
#define GBA_RUNTIME_H

#include <setjmp.h>
#include <stdint.h>

#include "gba_cpu.h"

enum {
    GBA_CYCLES_HDRAW = 1008,  /* the HBlank flag and interrupt come this far into a line */
    GBA_CYCLES_LINE = 1232,
    GBA_LINES = 228,
    GBA_VISIBLE_LINES = 160,
    GBA_CYCLES_FRAME = GBA_CYCLES_LINE * GBA_LINES,
};

enum {  /* interrupt request bits (IE, IF) */
    GBA_IRQ_VBLANK = 1 << 0, GBA_IRQ_HBLANK = 1 << 1, GBA_IRQ_VCOUNT = 1 << 2,
    GBA_IRQ_TIMER0 = 1 << 3, GBA_IRQ_SERIAL = 1 << 7, GBA_IRQ_DMA0 = 1 << 8,
    GBA_IRQ_KEYPAD = 1 << 12, GBA_IRQ_GAMEPAK = 1 << 13,
};

enum {  /* I/O register offsets from 0x04000000 */
    GBA_REG_DISPCNT = 0x000, GBA_REG_DISPSTAT = 0x004, GBA_REG_VCOUNT = 0x006,
    GBA_REG_SOUND_FIRST = 0x060, GBA_REG_SOUND_LAST = 0x0AE,
    GBA_REG_DMA0SAD = 0x0B0, GBA_REG_DMA3CNT_H = 0x0DE,
    GBA_REG_TM0CNT_L = 0x100, GBA_REG_TM3CNT_H = 0x10E,
    GBA_REG_SIO_FIRST = 0x120, GBA_REG_KEYINPUT = 0x130, GBA_REG_KEYCNT = 0x132,
    GBA_REG_RCNT = 0x134, GBA_REG_SIO_LAST = 0x15A,
    GBA_REG_IE = 0x200, GBA_REG_IF = 0x202, GBA_REG_WAITCNT = 0x204, GBA_REG_IME = 0x208,
    GBA_REG_POSTFLG = 0x300, GBA_REG_HALTCNT = 0x301,
};

typedef enum {
    GBA_END_STOPPED = 0,  /* the game executed Stop and nothing can wake it (headless) */
    GBA_END_ERROR = 3,    /* see GbaRuntime.error */
    GBA_END_HOST = 4,     /* the host asked to end the run (gba_end) */
} GbaEnd;

typedef struct GbaRuntime GbaRuntime;

typedef struct {
    void (*frame)(GbaRuntime *rt, void *user);             /* at every VBlank start */
    void (*log)(GbaRuntime *rt, int level, const char *text, void *user);  /* mGBA debug log */
    void (*diag)(GbaRuntime *rt, const char *text, void *user);  /* runtime warnings */
    void *user;
} GbaHost;

typedef struct {
    uint16_t reload, control;
    uint16_t counter;  /* the value at `start` (or the frozen value when not ticking) */
    uint64_t start;    /* cycle the counter last held `counter` */
} GbaTimer;

typedef struct {
    uint32_t src, dst, count;  /* the internal registers, latched when the channel starts */
} GbaDma;

enum { GBA_EVENT_HBLANK, GBA_EVENT_LINE, GBA_EVENT_TIMER0, GBA_EVENT_COUNT = GBA_EVENT_TIMER0 + 4 };

struct GbaRuntime {
    GbaCtx cpu;
    GbaHost host;
    const uint8_t *rom;
    uint32_t rom_size;

    uint8_t ewram[0x40000];
    uint8_t iwram[0x8000];
    uint8_t palette[0x400];
    uint8_t vram[0x18000];
    uint8_t oam[0x400];
    uint16_t io[0x200];  /* the I/O registers by halfword, as the game reads them */
    uint32_t bios_bus;   /* what reads from the BIOS area return (the last BIOS opcode) */

    uint64_t event_at[GBA_EVENT_COUNT];  /* cycle each event is due; UINT64_MAX = off */
    uint64_t line_start;                 /* cycle the current scanline began */
    uint64_t frames;                     /* VBlanks so far */
    GbaTimer timer[4];
    GbaDma dma[4];
    uint16_t keys_pressed;               /* GBA key bits, 1 = pressed */

    char debug_text[0x101];
    int debug_enabled;
    int warned_swi;

    jmp_buf end_jump;
    int resetting;
    GbaEnd end;
    char error[256];
};

/* Provided by the generated code (`gbaport recompile`). */
extern const uint32_t gba_rom_entry;  /* where the cartridge's entry branch leads */
extern const uint32_t gba_rom_size;
extern const uint32_t gba_rom_crc32;
GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);

/* For the host. */
int gba_init(GbaRuntime *rt, const uint8_t *rom, uint32_t size, const GbaHost *host);
GbaEnd gba_run(GbaRuntime *rt);
void gba_end(GbaRuntime *rt, GbaEnd why);  /* from a callback: ends gba_run */
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);
uint32_t gba_crc32(const uint8_t *data, uint32_t size);

/* Inside the runtime. */
static inline GbaRuntime *gba_rt(GbaCtx *ctx) { return (GbaRuntime *)ctx->runtime; }
void gba_fail(GbaRuntime *rt, const char *fmt, ...);  /* runtime error: ends the run */
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_reset_io(GbaRuntime *rt);

uint16_t gba_io_read(GbaRuntime *rt, uint32_t offset);   /* offset is halfword-aligned */
void gba_io_write(GbaRuntime *rt, uint32_t offset, uint16_t value, uint16_t mask);

void gba_scheduler_start(GbaRuntime *rt);
void gba_reschedule(GbaRuntime *rt);       /* after an event time changed */
void gba_request_irq(GbaRuntime *rt, uint16_t bits);
void gba_irq_changed(GbaRuntime *rt);      /* IE, IF or IME written */
void gba_halt(GbaRuntime *rt);             /* until IE & IF, then deliver the interrupt */

void gba_timer_write(GbaRuntime *rt, int n, uint16_t control);
uint16_t gba_timer_counter(GbaRuntime *rt, int n);
void gba_timer_overflow(GbaRuntime *rt, int n, uint64_t when);

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
void gba_dma_trigger(GbaRuntime *rt, int timing);  /* 1 = VBlank, 2 = HBlank */

#endif
```

Create `src/gbaport/runtime/runtime.c`:
```c
/* runtime.c - start-up, the run loop, resets and runtime errors. */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"

#define EWRAM_ENTRY 0x02000000u
#define BIOS_RESET 0x00000000u  /* never a return address: reaching it is an error */

uint32_t gba_crc32(const uint8_t *data, uint32_t size)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < size; i++) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return ~crc;
}

int gba_init(GbaRuntime *rt, const uint8_t *rom, uint32_t size, const GbaHost *host)
{
    memset(rt, 0, sizeof *rt);
    rt->host = *host;
    rt->rom = rom;
    rt->rom_size = size;
    if (size != gba_rom_size || gba_crc32(rom, size) != gba_rom_crc32) {
        snprintf(rt->error, sizeof rt->error,
                 "this build was recompiled from a different ROM (want %u bytes with CRC32 "
                 "%08x, got %u bytes with CRC32 %08x)",
                 (unsigned)gba_rom_size, (unsigned)gba_rom_crc32, (unsigned)size,
                 (unsigned)gba_crc32(rom, size));
        return -1;
    }
    return 0;
}

/* The CPU state the BIOS leaves for the game: system mode, its stacks set, r0-r12 zero. */
static void reset_cpu(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint64_t cycles = ctx->cycles;
    memset(ctx, 0, sizeof *ctx);
    ctx->cycles = cycles;
    ctx->lookup = gba_lookup;
    ctx->runtime = rt;
    ctx->cpsr_ctrl = GBA_MODE_SYS;
    ctx->r[13] = 0x03007F00u;
    ctx->bank_r13_14[gba_bank(GBA_MODE_IRQ)][0] = 0x03007FA0u;
    ctx->bank_r13_14[gba_bank(GBA_MODE_SVC)][0] = 0x03007FE0u;
}

static void power_on(GbaRuntime *rt)
{
    memset(rt->ewram, 0, sizeof rt->ewram);
    memset(rt->iwram, 0, sizeof rt->iwram);
    memset(rt->palette, 0, sizeof rt->palette);
    memset(rt->vram, 0, sizeof rt->vram);
    memset(rt->oam, 0, sizeof rt->oam);
    rt->cpu.cycles = 0;
    reset_cpu(rt);
    gba_reset_io(rt);
    rt->bios_bus = 0xE129F000u;  /* the opcode the BIOS fetches last before starting the game */
    gba_scheduler_start(rt);
}

/* SoftReset: clear the top 0x200 bytes of IWRAM (stacks, IRQ vector and flags), reset the
 * CPU registers, and start again at the ROM, or at EWRAM if [0x03007FFA] is non-zero.
 * Memory and I/O registers are kept. */
static uint32_t soft_reset(GbaRuntime *rt)
{
    uint32_t entry = rt->iwram[0x7FFA] ? EWRAM_ENTRY : gba_rom_entry;
    memset(rt->iwram + 0x7E00, 0, 0x200);
    reset_cpu(rt);
    gba_reschedule(rt);
    return entry;
}

GbaEnd gba_run(GbaRuntime *rt)
{
    power_on(rt);
    volatile uint32_t entry = gba_rom_entry;
    for (;;) {
        if (setjmp(rt->end_jump) == 0) {
            gba_call(&rt->cpu, entry, BIOS_RESET);
            gba_fail(rt, "the game jumped to the BIOS reset vector (0x00000000)");
        }
        if (!rt->resetting)
            return rt->end;
        rt->resetting = 0;
        entry = soft_reset(rt);
    }
}

void gba_end(GbaRuntime *rt, GbaEnd why)
{
    rt->end = why;
    longjmp(rt->end_jump, 1);
}

void gba_reset(GbaRuntime *rt)
{
    rt->resetting = 1;
    longjmp(rt->end_jump, 1);
}

void gba_fail(GbaRuntime *rt, const char *fmt, ...)
{
    va_list args;
    va_start(args, fmt);
    vsnprintf(rt->error, sizeof rt->error, fmt, args);
    va_end(args);
    gba_end(rt, GBA_END_ERROR);
}

void gba_set_keys(GbaRuntime *rt, uint16_t pressed) { rt->keys_pressed = pressed & 0x3FF; }

/* ---- hooks from gba_cpu.h: what recompiled code cannot handle itself -------------- */

/* addr has bit 0 set when execution was to go on in Thumb state. */
GbaFn gba_missing(GbaCtx *ctx, uint32_t addr)
{
    int thumb = addr & 1;
    gba_fail(gba_rt(ctx),
             "no recompiled code at 0x%08x (%s state, lr = 0x%08x): add it to game.toml "
             "[code] %s, or record a trace",
             (unsigned)(addr & ~1u), thumb ? "Thumb" : "ARM", (unsigned)ctx->r[14],
             thumb ? "thumb_entries" : "entries");
    return 0;
}

void gba_undefined(GbaCtx *ctx, uint32_t addr)
{
    gba_fail(gba_rt(ctx), "undefined instruction at 0x%08x", (unsigned)addr);
}

void gba_call_overflow(GbaCtx *ctx, uint32_t ret)
{
    gba_fail(gba_rt(ctx),
             "calls nested deeper than %u (return address 0x%08x): code that calls "
             "without ever returning",
             (unsigned)GBA_MAX_CALL_DEPTH, (unsigned)ret);
}
```

Create `src/gbaport/runtime/memory.c`:
```c
/* memory.c - the GBA memory map behind gba_read8/16/32 and gba_write8/16/32.
 *
 * Addresses arrive aligned to the access size (gba_cpu.h applies the ARM7TDMI rules for
 * misaligned loads and stores first). Every region mirrors across its 16 MiB page.
 * Byte writes follow the hardware: palette and BG VRAM write the byte to both halves of
 * the halfword, OBJ VRAM and OAM ignore them. Reads past the end of the ROM return the
 * cartridge bus's open-bus pattern (each halfword reads as its address / 2); other
 * unmapped reads return 0. */
#include <string.h>

#include "gba_runtime.h"

#define DEBUG_TEXT 0x04FFF600u   /* mGBA's debug log: a 256-byte string, */
#define DEBUG_FLAGS 0x04FFF700u  /* a print register (level | 0x100), */
#define DEBUG_ENABLE 0x04FFF780u /* and an enable register (write 0xC0DE, reads 0x1DEA) */

static uint32_t get16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }
static uint32_t get32(const uint8_t *p) { return get16(p) | get16(p + 2) << 16; }
static void put16(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, uint32_t v) { put16(p, v); put16(p + 2, v >> 16); }

static uint32_t vram_offset(uint32_t addr)
{
    uint32_t offset = addr & 0x1FFFF;  /* 96 KiB, mirrored in 128 KiB steps; */
    return offset >= 0x18000 ? offset - 0x8000 : offset;  /* the last 32 KiB repeat OBJ VRAM */
}

/* Plain memory for a region, with its mirror mask; NULL for the regions with handlers. */
static uint8_t *plain(GbaRuntime *rt, uint32_t addr, uint32_t *offset)
{
    switch (addr >> 24) {
    case 0x02: *offset = addr & 0x3FFFF; return rt->ewram;
    case 0x03: *offset = addr & 0x7FFF; return rt->iwram;
    case 0x05: *offset = addr & 0x3FF; return rt->palette;
    case 0x06: *offset = vram_offset(addr); return rt->vram;
    case 0x07: *offset = addr & 0x3FF; return rt->oam;
    default: return NULL;
    }
}

/* The ROM bytes behind a cartridge read of `size` bytes, or NULL past the end of the ROM
 * (and outside 0x08000000-0x0DFFFFFF, where the three wait-state mirrors are). */
static const uint8_t *rom_at(const GbaRuntime *rt, uint32_t addr, uint32_t size)
{
    uint32_t offset = addr & 0x01FFFFFF;
    if (addr < 0x08000000u || addr >= 0x0E000000u || offset + size > rt->rom_size)
        return NULL;
    return rt->rom + offset;
}

static int is_rom(uint32_t addr) { return addr >= 0x08000000u && addr < 0x0E000000u; }

/* ---- the mGBA debug log ------------------------------------------------------------ */

static int is_debug(uint32_t addr) { return addr >= DEBUG_TEXT && addr < DEBUG_ENABLE + 2; }

static uint32_t debug_read16(GbaRuntime *rt, uint32_t addr)
{
    return addr == DEBUG_ENABLE && rt->debug_enabled ? 0x1DEA : 0;
}

static void debug_write16(GbaRuntime *rt, uint32_t addr, uint32_t value)
{
    if (addr < DEBUG_FLAGS) {
        uint32_t i = addr - DEBUG_TEXT;
        rt->debug_text[i] = (char)value;
        rt->debug_text[i + 1] = (char)(value >> 8);
    } else if (addr == DEBUG_FLAGS && (value & 0x100) && rt->debug_enabled) {
        if (rt->host.log)
            rt->host.log(rt, (int)(value & 7), rt->debug_text, rt->host.user);
        memset(rt->debug_text, 0, sizeof rt->debug_text);
    } else if (addr == DEBUG_ENABLE) {
        rt->debug_enabled = value == 0xC0DE;
    }
}

/* ---- reads ------------------------------------------------------------------------ */

uint32_t gba_read16(GbaCtx *ctx, uint32_t addr)
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get16(mem + offset);
    const uint8_t *rom = rom_at(rt, addr, 2);
    if (rom)
        return get16(rom);
    if (is_rom(addr))
        return (addr >> 1) & 0xFFFF;  /* open bus past the end of the ROM */
    switch (addr >> 24) {
    case 0x00:
        return addr < 0x4000 ? (rt->bios_bus >> ((addr & 2) * 8)) & 0xFFFF : 0;
    case 0x04:
        if (addr < 0x04000400u)
            return gba_io_read(rt, addr & 0x3FE);
        return is_debug(addr) ? debug_read16(rt, addr) : 0;
    default:
        return 0;
    }
}

uint32_t gba_read8(GbaCtx *ctx, uint32_t addr)
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return mem[offset];
    const uint8_t *rom = rom_at(rt, addr, 1);
    if (rom)
        return *rom;
    return (gba_read16(ctx, addr & ~1u) >> ((addr & 1) * 8)) & 0xFF;
}

uint32_t gba_read32(GbaCtx *ctx, uint32_t addr)
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        return get32(mem + offset);
    const uint8_t *rom = rom_at(rt, addr, 4);  /* literal pools: the most common case */
    if (rom)
        return get32(rom);
    return gba_read16(ctx, addr) | gba_read16(ctx, addr + 2) << 16;
}

/* ---- writes ----------------------------------------------------------------------- */

static void write16(GbaRuntime *rt, uint32_t addr, uint32_t value, uint16_t mask)
{
    switch (addr >> 24) {
    case 0x04:
        if (addr < 0x04000400u)
            gba_io_write(rt, addr & 0x3FE, (uint16_t)value, mask);
        else if (is_debug(addr) && mask == 0xFFFF)  /* bytes reach the string only */
            debug_write16(rt, addr, value);
        break;
    default:
        break;  /* BIOS and ROM are read-only; nothing else is mapped */
    }
}

void gba_write16(GbaCtx *ctx, uint32_t addr, uint32_t value)
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem)
        put16(mem + offset, value);
    else
        write16(rt, addr, value & 0xFFFF, 0xFFFF);
}

void gba_write32(GbaCtx *ctx, uint32_t addr, uint32_t value)
{
    GbaRuntime *rt = gba_rt(ctx);
    uint32_t offset;
    uint8_t *mem = plain(rt, addr, &offset);
    if (mem) {
        put32(mem + offset, value);
    } else {
        write16(rt, addr, value & 0xFFFF, 0xFFFF);
        write16(rt, addr + 2, value >> 16, 0xFFFF);
    }
}

void gba_write8(GbaCtx *ctx, uint32_t addr, uint32_t value)
{
    GbaRuntime *rt = gba_rt(ctx);
    value &= 0xFF;
    switch (addr >> 24) {
    case 0x02: rt->ewram[addr & 0x3FFFF] = (uint8_t)value; return;
    case 0x03: rt->iwram[addr & 0x7FFF] = (uint8_t)value; return;
    case 0x05: put16(rt->palette + (addr & 0x3FE), value * 0x101); return;
    case 0x06: {
        int bitmap = (rt->io[GBA_REG_DISPCNT >> 1] & 7) >= 3;
        uint32_t offset = vram_offset(addr) & ~1u;
        if (offset < (bitmap ? 0x14000u : 0x10000u))  /* BG VRAM; OBJ VRAM ignores bytes */
            put16(rt->vram + offset, value * 0x101);
        return;
    }
    case 0x07: return;  /* OAM ignores byte writes */
    default: {
        int high = addr & 1;
        if (is_debug(addr) && addr < DEBUG_FLAGS) {
            rt->debug_text[addr - DEBUG_TEXT] = (char)value;  /* the string takes bytes */
            return;
        }
        write16(rt, addr & ~1u, value << (high * 8), high ? 0xFF00 : 0x00FF);
        return;
    }
    }
}
```

Create `src/gbaport/runtime/io.c`:
```c
/* io.c - the I/O registers at 0x04000000.
 *
 * Registers are kept by halfword and most read back what was written. The exceptions:
 * - DISPSTAT's status bits and VCOUNT belong to the scheduler; writes cannot change them.
 * - KEYINPUT comes from the host.
 * - IF clears the bits written as 1.
 * - DMA source, destination and count registers are write-only: they read as 0. */
#include <string.h>

#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

void gba_reset_io(GbaRuntime *rt)
{
    memset(rt->io, 0, sizeof rt->io);
    memset(rt->timer, 0, sizeof rt->timer);
    memset(rt->dma, 0, sizeof rt->dma);
    IO(rt, GBA_REG_DISPCNT) = 0x0080;  /* forced blank, as the BIOS leaves it */
    IO(rt, 0x020) = IO(rt, 0x026) = 0x0100;  /* BG2 affine matrix: identity */
    IO(rt, 0x030) = IO(rt, 0x036) = 0x0100;  /* BG3 */
    IO(rt, 0x088) = 0x0200;                  /* SOUNDBIAS */
    IO(rt, GBA_REG_RCNT) = 0x8000;
    IO(rt, GBA_REG_POSTFLG) = 0x0001;        /* booted */
}

static int dma_channel(uint32_t offset)  /* the channel whose CNT_H is at offset, or -1 */
{
    if (offset < GBA_REG_DMA0SAD || offset > GBA_REG_DMA3CNT_H)
        return -1;
    uint32_t rel = offset - GBA_REG_DMA0SAD;
    return rel % 12 == 10 ? (int)(rel / 12) : -1;
}

uint16_t gba_io_read(GbaRuntime *rt, uint32_t offset)
{
    if (offset >= GBA_REG_DMA0SAD && offset <= GBA_REG_DMA3CNT_H && dma_channel(offset) < 0)
        return 0;  /* source, destination and count are write-only */
    if (offset == GBA_REG_KEYINPUT)
        return (uint16_t)(0x3FF & ~rt->keys_pressed);
    return IO(rt, offset);
}

void gba_io_write(GbaRuntime *rt, uint32_t offset, uint16_t value, uint16_t mask)
{
    uint16_t old = IO(rt, offset);
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    switch (offset) {
    case GBA_REG_DISPSTAT: {
        uint16_t stat = (uint16_t)((old & 0x0007) | (merged & 0xFF38));
        uint16_t match = IO(rt, GBA_REG_VCOUNT) == (stat >> 8);
        IO(rt, offset) = (uint16_t)((stat & ~4) | (match ? 4 : 0));
        return;
    }
    case GBA_REG_VCOUNT:
    case GBA_REG_KEYINPUT:
        return;  /* read-only */
    case GBA_REG_IE:
        IO(rt, offset) = merged & 0x3FFF;
        return;
    case GBA_REG_IF:
        IO(rt, offset) = (uint16_t)(old & ~(value & mask));  /* writing 1 acknowledges */
        return;
    case GBA_REG_IME:
        IO(rt, offset) = merged & 1;
        return;
    case GBA_REG_WAITCNT:
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        return;
    case GBA_REG_POSTFLG:  /* POSTFLG in the low byte, HALTCNT (write-only) in the high one */
        IO(rt, offset) = merged & 0x0001;
        return;
    default:
        IO(rt, offset) = merged;
        return;
    }
}
```

Create `src/gbaport/runtime/scheduler.c`:
```c
/* scheduler.c - scanline timing and timed events.
 *
 * Recompiled code runs gba_events() once ctx->cycles reaches ctx->next_event. It runs
 * every event that is due, in time order: each scanline's HBlank and end, which keep
 * DISPSTAT and VCOUNT up to date, request interrupts in IF and count frames. Nothing
 * delivers the interrupts yet. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define NEVER UINT64_MAX

static uint64_t earliest(const GbaRuntime *rt, int *which)
{
    uint64_t when = NEVER;
    for (int i = 0; i < GBA_EVENT_COUNT; i++) {
        if (rt->event_at[i] < when) {
            when = rt->event_at[i];
            *which = i;
        }
    }
    return when;
}

void gba_reschedule(GbaRuntime *rt)
{
    int which;
    rt->cpu.next_event = earliest(rt, &which);
}

void gba_request_irq(GbaRuntime *rt, uint16_t bits)
{
    IO(rt, GBA_REG_IF) |= bits;
}

static void schedule_line(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = rt->line_start + GBA_CYCLES_HDRAW;
    rt->event_at[GBA_EVENT_LINE] = rt->line_start + GBA_CYCLES_LINE;
}

void gba_scheduler_start(GbaRuntime *rt)
{
    for (int i = 0; i < GBA_EVENT_COUNT; i++)
        rt->event_at[i] = NEVER;
    rt->line_start = rt->cpu.cycles;
    rt->frames = 0;
    IO(rt, GBA_REG_VCOUNT) = 0;
    schedule_line(rt);
    gba_reschedule(rt);
}

static void hblank(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    IO(rt, GBA_REG_DISPSTAT) |= 2;
    if (IO(rt, GBA_REG_DISPSTAT) & 0x10)
        gba_request_irq(rt, GBA_IRQ_HBLANK);
}

static void line_end(GbaRuntime *rt, uint64_t when)
{
    uint16_t line = (uint16_t)((IO(rt, GBA_REG_VCOUNT) + 1) % GBA_LINES);
    uint16_t stat = IO(rt, GBA_REG_DISPSTAT) & ~2;
    rt->line_start = when;
    schedule_line(rt);
    IO(rt, GBA_REG_VCOUNT) = line;
    if (line == GBA_VISIBLE_LINES)
        stat |= 1;
    else if (line == GBA_LINES - 1)
        stat &= ~1;  /* the VBlank flag is clear again in the last line */
    int match = line == (stat >> 8);
    stat = (uint16_t)(match ? stat | 4 : stat & ~4);
    IO(rt, GBA_REG_DISPSTAT) = stat;
    if (match && (stat & 0x20))
        gba_request_irq(rt, GBA_IRQ_VCOUNT);
    if (line == GBA_VISIBLE_LINES) {
        if (stat & 0x08)
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        rt->frames++;
        if (rt->host.frame)
            rt->host.frame(rt, rt->host.user);
    }
}

void gba_events(GbaCtx *ctx)
{
    GbaRuntime *rt = gba_rt(ctx);
    for (;;) {
        int which = 0;
        uint64_t when = earliest(rt, &which);
        if (when > ctx->cycles)
            break;
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else
            line_end(rt, when);
    }
    gba_reschedule(rt);
}
```

Create `src/gbaport/runtime/bios.c`:
```c
/* bios.c - the BIOS calls (SWI), reimplemented in C.
 *
 * This file has the resets and Stop so far. The other BIOS functions (0x02 and 0x04-0x2A:
 * Halt, the interrupt waits, arithmetic, copies, decompression, ...) are not implemented
 * yet and end the run with an error that names them. Numbers above 0x2A do not exist in
 * the BIOS; the first one is reported and they are ignored. */
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

/* RegisterRamReset: r0 selects what to clear. Bit 1 keeps the top 0x200 bytes of IWRAM;
 * bit 7 resets the I/O registers other than serial and sound. */
static void register_ram_reset(GbaRuntime *rt, uint32_t flags)
{
    if (flags & 0x01) memset(rt->ewram, 0, sizeof rt->ewram);
    if (flags & 0x02) memset(rt->iwram, 0, 0x7E00);
    if (flags & 0x04) memset(rt->palette, 0, sizeof rt->palette);
    if (flags & 0x08) memset(rt->vram, 0, sizeof rt->vram);
    if (flags & 0x10) memset(rt->oam, 0, sizeof rt->oam);
    if (flags & 0x20) {
        for (uint32_t r = GBA_REG_SIO_FIRST; r <= GBA_REG_SIO_LAST; r += 2)
            if (r != GBA_REG_KEYINPUT && r != GBA_REG_KEYCNT)
                IO(rt, r) = 0;
        IO(rt, GBA_REG_RCNT) = 0x8000;
    }
    if (flags & 0x40)
        for (uint32_t r = GBA_REG_SOUND_FIRST; r <= GBA_REG_SOUND_LAST; r += 2)
            IO(rt, r) = 0;
    if (flags & 0x80) {
        uint16_t keep[0x200];
        memcpy(keep, rt->io, sizeof keep);
        gba_reset_io(rt);
        IO(rt, GBA_REG_VCOUNT) = keep[GBA_REG_VCOUNT >> 1];
        IO(rt, GBA_REG_DISPSTAT) = keep[GBA_REG_DISPSTAT >> 1] & 7;
        for (uint32_t r = GBA_REG_SOUND_FIRST; r <= GBA_REG_SOUND_LAST; r += 2)
            IO(rt, r) = keep[r >> 1];
        for (uint32_t r = GBA_REG_SIO_FIRST; r <= GBA_REG_SIO_LAST; r += 2)
            if (r != GBA_REG_KEYCNT)
                IO(rt, r) = keep[r >> 1];
        for (int n = 0; n < 4; n++)
            rt->event_at[GBA_EVENT_TIMER0 + n] = UINT64_MAX;
        gba_reschedule(rt);
    }
}

void gba_swi(GbaCtx *ctx, uint32_t number)
{
    GbaRuntime *rt = gba_rt(ctx);
    ctx->cycles += 20;  /* entering and leaving the BIOS */
    switch (number) {
    case 0x00: gba_reset(rt); break;
    case 0x01: register_ram_reset(rt, ctx->r[0]); break;
    case 0x03: gba_end(rt, GBA_END_STOPPED); break;  /* nothing can wake a headless run */
    default:
        if (number <= 0x2A)
            gba_fail(rt, "BIOS function 0x%02x is not implemented yet", (unsigned)number);
        if (!rt->warned_swi && rt->host.diag) {
            char text[96];
            snprintf(text, sizeof text, "ignoring SWI 0x%02x: the BIOS has no such function",
                     (unsigned)number);
            rt->host.diag(rt, text, rt->host.user);
        }
        rt->warned_swi = 1;
        break;
    }
    rt->bios_bus = 0xE3A02004u;  /* the opcode the BIOS fetches last on its way out */
}
```

Create `src/gbaport/runtime/host_headless.c`:
```c
/* host_headless.c - run a recompiled game without a window.
 *
 *     game ROM [--frames N]
 *
 * The game's mGBA debug-log lines go to stdout, runtime warnings and errors to stderr.
 * Exit status: 0 the game executed Stop, 2 bad arguments or the wrong ROM, 3 a runtime
 * error (for example code the recompiler did not find), 4 the frame limit was reached. */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gba_runtime.h"

static unsigned long frame_limit;

static void on_frame(GbaRuntime *rt, void *user)
{
    (void)user;
    if (frame_limit && rt->frames >= frame_limit)
        gba_end(rt, GBA_END_HOST);
}

static void on_log(GbaRuntime *rt, int level, const char *text, void *user)
{
    (void)rt, (void)level, (void)user;
    printf("%s\n", text);
    fflush(stdout);
}

static void on_diag(GbaRuntime *rt, const char *text, void *user)
{
    (void)rt, (void)user;
    fprintf(stderr, "warning: %s\n", text);
}

static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = length > 0 ? malloc((size_t)length) : NULL;
    if (data && fread(data, 1, (size_t)length, f) != (size_t)length) {
        free(data);
        data = NULL;
    }
    fclose(f);
    *size = (uint32_t)length;
    return data;
}

int main(int argc, char **argv)
{
    const char *rom_path = NULL;
    int bad = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc)
            frame_limit = strtoul(argv[++i], NULL, 10);
        else if (!rom_path && argv[i][0] != '-')
            rom_path = argv[i];
        else
            bad = 1;
    }
    if (!rom_path || bad) {
        fprintf(stderr, "usage: %s ROM [--frames N]\n", argv[0]);
        return 2;
    }
    uint32_t size;
    uint8_t *rom = read_file(rom_path, &size);
    if (!rom) {
        fprintf(stderr, "error: cannot read %s\n", rom_path);
        return 2;
    }
    static GbaRuntime rt;
    GbaHost host = {on_frame, on_log, on_diag, NULL};
    if (gba_init(&rt, rom, size, &host) != 0) {
        fprintf(stderr, "error: %s\n", rt.error);
        return 2;
    }
    GbaEnd end = gba_run(&rt);
    if (end == GBA_END_ERROR)
        fprintf(stderr, "error: %s\n", rt.error);
    else if (end == GBA_END_HOST)
        fprintf(stderr, "stopped after %lu frames\n", frame_limit);
    return (int)end;
}
```

Create `src/gbaport/native/build.py`:
```python
"""A game's generated C sources, and compiling them with the runtime into a program.

``generated_sources`` adds two files to the lifter's output: ``gba_cpu.h`` and
``gba_rom.c``, which records where the game starts (the target of the cartridge's entry
branch, which the analysis starts from) and the size and CRC32 of the ROM the code came
from (the runtime refuses any other ROM). ``compile_native`` compiles those sources together with
the runtime in ``gbaport/runtime`` and one host (``host_headless.c`` so far).
"""

import os
import subprocess
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from gbaport.lift.program import HEADER, LiftedProgram, program_files
from gbaport.native.toolchain import ToolchainError, find_clang
from gbaport.rom.header import parse_header
from gbaport.rom.image import ROM_BASE, RomImage

PACKAGE = Path(__file__).parent.parent
RUNTIME = PACKAGE / "runtime"
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "bios.c")
HOSTS = {"headless": "host_headless.c"}
GENERATED_NAMES = ("gba_program.h", "gba_dispatch.c", "gba_rom.c", HEADER)  # plus gba_code_*.c
CFLAGS = ("-std=c11", "-O2", "-Wall", "-Werror", "-Wno-unused-label")


def rom_identity(data: bytes) -> str:
    entry = parse_header(RomImage(data)).entry_point or ROM_BASE  # the analysis seeds this
    return (
        "/* Generated by gbaport: the ROM this code was recompiled from. */\n"
        "#include <stdint.h>\n\n"
        f"const uint32_t gba_rom_entry = 0x{entry:08x}u;\n"
        f"const uint32_t gba_rom_size = {len(data)}u;\n"
        f"const uint32_t gba_rom_crc32 = 0x{zlib.crc32(data):08x}u;\n"
    )


def generated_sources(lifted: LiftedProgram, rom_data: bytes) -> dict[str, str]:
    """Every file `gbaport recompile` writes, by name."""
    files = program_files(lifted)
    files["gba_rom.c"] = rom_identity(rom_data)
    files[HEADER] = (PACKAGE / "lift" / HEADER).read_text(encoding="utf-8")
    return files


def write_sources(files: dict[str, str], out: Path) -> None:
    """Write ``files`` to ``out``, first removing the generated files of an earlier run."""
    out.mkdir(parents=True, exist_ok=True)
    for stale in [*out.glob("gba_code_*.c"), *(out / name for name in GENERATED_NAMES)]:
        stale.unlink(missing_ok=True)  # only files this command writes
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")


def compile_native(sources: Path, out: Path, name: str, host: str = "headless") -> Path:
    """Compile the generated ``sources`` with the runtime and ``host``; returns the program."""
    clang = find_clang()
    objects = out / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    units = [*sorted(sources.glob("*.c")), *(RUNTIME / s for s in RUNTIME_SOURCES), RUNTIME / HOSTS[host]]

    def compile_unit(unit: Path) -> Path:
        obj = objects / f"{unit.stem}.o"
        command = [clang, *CFLAGS, f"-I{sources}", f"-I{RUNTIME}", "-c", str(unit), "-o", str(obj)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ToolchainError(f"clang failed on {unit.name}:\n{result.stderr[-4000:]}")
        return obj

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        compiled = list(pool.map(compile_unit, units))
    program = out / (name + (".exe" if os.name == "nt" else ""))
    result = subprocess.run(
        [clang, *(str(obj) for obj in compiled), "-o", str(program)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ToolchainError(f"linking {program.name} failed:\n{result.stderr[-4000:]}")
    return program
```

In `src/gbaport/lift/function.py`, replace:
```python
whatever leaves the function (a return, a tail call, a jump through a register)
returns the address to continue at. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address. Blocks that loops
```
with:
```python
whatever leaves the function (a return, a tail call, a jump through a register)
returns the address to continue at, with bit 0 set when execution goes on in
Thumb state. The lookup ignores that bit; a miss reports it, so the user knows
which state the missing code is in. A call sets LR and runs the callee chain
with ``gba_call`` until it comes back to the return address. Blocks that loops
```

In `src/gbaport/lift/function.py`, replace:
```python
            if nxt != following:
                lines.append("    " + self._go(nxt))
        return lines
```
with:
```python
            if nxt != following:
                lines.append("    " + self._go(nxt, block.mode))
        return lines
```

In `src/gbaport/lift/function.py`, replace:
```python
                return [], False
            return [self._go(ins.target)], True
        if op is Op.BL:
```
with:
```python
                return [], False
            return [self._go(ins.target, ins.mode)], True
        if op is Op.BL:
```

In `src/gbaport/lift/function.py`, replace:
```python
                return [set_lr], False
            return [set_lr, self._call(ins.target, ret)], False
        if op is Op.BL_LO:
            ret = self._return_address(ins)
            return [
                f"t = ctx->r[14] + {hexu(ins.imm)};",
                f"ctx->r[14] = {hexu(ret)};",
```
with:
```python
                return [set_lr], False
            return [set_lr, self._call(ins.target, ret, ins.mode)], False
        if op is Op.BL_LO:
            ret = self._return_address(ins)
            return [
                f"t = (ctx->r[14] + {hexu(ins.imm)}) | 1u;",  # stays in Thumb state
                f"ctx->r[14] = {hexu(ret)};",
```

In `src/gbaport/lift/function.py`, replace:
```python

    def _call(self, target: int, ret: int) -> str:
        """A call to a constant target: direct when that function was recompiled."""
        if target in self.program.functions:
            return f"gba_call_direct(ctx, {function_name(target, self.prefix)}, {hexu(ret)});"
        return f"gba_call(ctx, {hexu(target)}, {hexu(ret)});"

    def _go(self, target: int) -> str:
        if target in self.blocks:
            return f"goto {label(target)};"
        return f"GBA_EXIT({hexu(target)});"
```
with:
```python

    def _call(self, target: int, ret: int, mode: Mode) -> str:
        """A call to a constant target: direct when that function was recompiled."""
        if target in self.program.functions:
            return f"gba_call_direct(ctx, {function_name(target, self.prefix)}, {hexu(ret)});"
        return f"gba_call(ctx, {hexu(_in_state(target, mode))}, {hexu(ret)});"

    def _go(self, target: int, mode: Mode) -> str:
        if target in self.blocks:
            return f"goto {label(target)};"
        return f"GBA_EXIT({hexu(_in_state(target, mode))});"
```

In `src/gbaport/lift/function.py`, replace:
```python
            return []  # bit 0 selects the state; the lookup ignores it
        if restores_cpsr(ins):  # the restored T bit decides the alignment
            return ["t &= (ctx->cpsr_ctrl & 0x20u) ? ~1u : ~3u;"]
        return ["t &= ~3u;" if ins.mode is Mode.ARM else "t &= ~1u;"]
```
with:
```python
            return []  # bit 0 selects the state; the lookup ignores it
        if restores_cpsr(ins):  # the restored T bit decides the state
            return ["t = (ctx->cpsr_ctrl & 0x20u) ? t | 1u : t & ~3u;"]
        return ["t &= ~3u;" if ins.mode is Mode.ARM else "t |= 1u;"]  # no state change
```

In `src/gbaport/lift/function.py`, replace:
```python
        lines += ["default: break;", "}"]
        return lines
```
with:
```python
        lines += ["default: break;", "}"]
        return lines


def _in_state(target: int, mode: Mode) -> int:
    """``target`` with bit 0 telling the state execution continues in."""
    return target | 1 if mode is Mode.THUMB else target
```

In `src/gbaport/lift/program.py`, replace:
```python
``gba_lookup`` (prefixed in tests, so several programs can share one binary)
finds the function for an address with a binary search and hands anything
else to the runtime's ``gba_missing``.
"""
```
with:
```python
``gba_lookup`` (prefixed in tests, so several programs can share one binary)
finds the function for an address with a binary search (bit 0, the CPU state,
does not matter) and hands anything else to the runtime's ``gba_missing``, bit 0
included.
"""
```

In `src/gbaport/lift/program.py`, replace:
```python
        "{",
        "    addr &= ~1u;",
    ]
```
with:
```python
        "{",
        "    uint32_t key = addr & ~1u;",
    ]
```

In `src/gbaport/lift/program.py`, replace:
```python
            f"        uint32_t found = {prefix}table[mid].addr;",
            "        if (found == addr)",
            f"            return {prefix}table[mid].fn;",
            "        if (found < addr)",
            "            lo = mid + 1;",
```
with:
```python
            f"        uint32_t found = {prefix}table[mid].addr;",
            "        if (found == key)",
            f"            return {prefix}table[mid].fn;",
            "        if (found < key)",
            "            lo = mid + 1;",
```

In `src/gbaport/cli.py`, replace:
```python
import json
import shutil
import sys
```
with:
```python
import json
import sys
```

In `src/gbaport/cli.py`, replace:
```python
from gbaport.isa.model import Mode
from gbaport.lift.program import HEADER, lift_program, program_files
from gbaport.rom.header import parse_header
```
with:
```python
from gbaport.isa.model import Mode
from gbaport.lift.program import HEADER, lift_program
from gbaport.native.build import compile_native, generated_sources, write_sources
from gbaport.rom.header import parse_header
```

In `src/gbaport/cli.py`, replace:
```python
    _add_recompile_command(commands)
    return parser
```
with:
```python
    _add_recompile_command(commands)
    _add_build_command(commands)
    return parser
```

In `src/gbaport/cli.py`, replace:
```python

GENERATED = ("gba_program.h", "gba_dispatch.c", HEADER)
```
with:
```python

def _recompile(args: argparse.Namespace, rom: RomImage, out: Path) -> None:
    """Analyse and lift ``rom``, write its C sources to ``out`` and report."""
    analysis = _analyse(args, rom)
    lifted = lift_program(analysis.program, analysis.exploration)
    files = generated_sources(lifted, rom.data)
    write_sources(files, out)
    lines = sum(text.count("\n") for name, text in files.items() if name != HEADER)
    print(f"{'functions':<13}{len(lifted.functions)}")
    print(f"{'C files':<13}{len(files)} ({lines} lines)")
    print(f"{'lift issues':<13}{len(lifted.problems)}")
    for problem in lifted.problems[:20]:
        print(f"  {problem}")
    print(f"wrote {out}")
```

In `src/gbaport/cli.py`, replace:
```python
    rom = RomImage.load(args.rom)
    analysis = _analyse(args, rom)
    lifted = lift_program(analysis.program, analysis.exploration)
    files = program_files(lifted)
    out = Path(args.out) if args.out else Path("games") / analysis.info.header.game_code / "generated"
    out.mkdir(parents=True, exist_ok=True)
    for stale in [*out.glob("gba_code_*.c"), *(out / name for name in GENERATED)]:
        stale.unlink(missing_ok=True)  # only files this command writes
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
    shutil.copyfile(Path(__file__).parent / "lift" / HEADER, out / HEADER)
    lines = sum(text.count("\n") for text in files.values())
    print(f"{'functions':<13}{len(lifted.functions)}")
    print(f"{'C files':<13}{len(files) + 1} ({lines} lines)")
    print(f"{'lift issues':<13}{len(lifted.problems)}")
    for problem in lifted.problems[:20]:
        print(f"  {problem}")
    print(f"wrote {out}")
    return 0
```
with:
```python
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
    build.set_defaults(handler=_run_build)


def _run_build(args: argparse.Namespace) -> int:
    rom = RomImage.load(args.rom)
    game_code = parse_header(rom).game_code or "game"
    root = Path(args.out) if args.out else Path("games") / game_code
    _recompile(args, rom, root / "generated")
    program = compile_native(root / "generated", root / "build", game_code)
    print(f"built {program}")
    print(f"run it with: {program} {args.rom} [--frames N]")
    return 0
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 545 passed (536 + 9); ruff clean. The first run compiles six test ROMs and their native builds in about 30 s; later runs reuse them from `%TEMP%/gbaport-romcache`.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py src/gbaport/lift src/gbaport/cli.py tests/gbaroms tests/romtest.py tests/runtime/test_core.py tests/test_build_cli.py tests/test_recompile_cli.py tests/lift/test_program.py
git commit -m "feat: native runtime core, gbaport build and the headless host"
```

---

### Task 3: Interrupts and waits

**Files:**
- Create: `tests/gbaroms/interrupts.c`, `tests/gbaroms/reset_in_irq.c`, `tests/gbaroms/err_no_handler.c`
- Replace: `src/gbaport/runtime/scheduler.c`, with interrupt delivery and Halt added.
- Modify: `src/gbaport/runtime/io.c` (IE/IF/IME and HALTCNT), `src/gbaport/runtime/bios.c` (Halt, IntrWait, VBlankIntrWait)
- Test: `tests/runtime/test_interrupts.py`

**Interfaces:**
- Consumes: Task 2's runtime and kit.
- Produces: `gba_irq_changed(rt)`, `gba_halt(rt)`, and the BIOS-style interrupt entry and exit.
- **IRQ entry and exit:**
  - The entry switches to IRQ mode and pushes r0-r3, r12 and lr (lr_irq = 0) on the IRQ stack.
  - It sets r0 = 0x04000000 and lr = 0x138, then runs `gba_call(handler, 0x138)`.
  - On return it pops those registers and restores CPSR = SPSR.
- **When interrupts arrive:**
  - Writes to IE, IF or IME that make an interrupt deliverable set `next_event` to now, so the interrupt is taken at the next loop head or function exit.
  - An interrupt waiting only on the CPSR's I bit arrives at the next scheduler event, within a scanline.
  - An interrupt with no handler set at 0x03007FFC is a runtime error.
- **BIOS waits:**
  - IntrWait and VBlankIntrWait turn IME on.
  - Calling them with the CPSR's I bit set is a runtime error, because on hardware they would never return.

- [ ] **Step 1: Write the failing tests**

Create `tests/gbaroms/interrupts.c`:
```c
/* Scanline timing and interrupts: VBlank, HBlank and VCount requests, IE/IME/CPSR gating,
 * the BIOS-style handler call, Halt and IntrWait. */
#include "testlib.h"

volatile uint32_t nested_seen;
void nesting_handler(void);

/* An IRQ handler that lets other interrupts in while it works, as sound engines do. It
 * saves SPSR and lr_irq first (a nested interrupt replaces both), acknowledges, and for a
 * VBlank switches to system mode with interrupts on until an HBlank has been counted. */
__asm__(
    ".section .iwram, \"ax\"\n"
    ".arm\n"
    ".align 2\n"
    ".global nesting_handler\n"
    ".type nesting_handler, %function\n"
    "nesting_handler:\n"
    "    mrs r3, spsr\n"
    "    stmfd sp!, {r3, lr}\n"
    "    mov r0, #0x04000000\n"
    "    add r0, r0, #0x200\n"
    "    ldr r1, [r0]\n"               /* IE | IF << 16 */
    "    and r1, r1, r1, lsr #16\n"
    "    strh r1, [r0, #2]\n"
    "    ldr r2, =irq_count\n"
    "    tst r1, #2\n"                 /* HBlank: count it */
    "    ldrne r3, [r2, #4]\n"
    "    addne r3, r3, #1\n"
    "    strne r3, [r2, #4]\n"
    "    tst r1, #1\n"                 /* VBlank: wait for an HBlank with interrupts on */
    "    beq 2f\n"
    "    ldr r1, [r2, #4]\n"
    "    msr cpsr_c, #0x1F\n"
    "1:  ldr r3, [r2, #4]\n"
    "    cmp r3, r1\n"
    "    beq 1b\n"
    "    msr cpsr_c, #0x92\n"
    "    ldr r2, =nested_seen\n"
    "    mov r3, #1\n"
    "    str r3, [r2]\n"
    "2:  ldmfd sp!, {r3, lr}\n"
    "    msr spsr_cf, r3\n"
    "    bx lr\n"
    ".ltorg\n"
    ".size nesting_handler, . - nesting_handler\n"
    ".text\n"
    ".thumb\n");

static void spin(int n)
{
    for (volatile int i = 0; i < n; i++) {}
}

/* A loop whose registers live across many interrupts: the handler must not disturb them. */
static uint32_t busy_sum(uint32_t n)
{
    uint32_t sum = 0;
    for (uint32_t i = 1; i <= n; i++)
        sum += i ^ (sum >> 3);
    return sum;
}

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;  /* request VBlank */
    REG_IE = IRQ_VBLANK;

    bios_vblank_wait();
    uint32_t line = REG_VCOUNT;
    expect("vblank wait returns in line 160", line, 160);
    expect("vblank flag set in line 160", REG_DISPSTAT & 1, 1);
    irq_count[0] = 0;
    for (int i = 0; i < 5; i++)
        bios_vblank_wait();
    expect("five vblank waits, five vblank interrupts", irq_count[0], 5);
    expect("handler ran in IRQ mode, ARM, IRQs off", irq_cpsr & 0xBF, 0x92);
    expect("back in system mode after the handler", get_cpsr() & 0x1F, 0x1F);

    wait_vcount(227);
    expect("vblank flag clear in line 227", REG_DISPSTAT & 1, 0);
    wait_vcount(100);
    expect("no vblank flag in visible lines", REG_DISPSTAT & 1, 0);

    /* HBlank: requested once per line, 228 a frame. */
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    bios_vblank_wait();
    irq_count[1] = 0;
    bios_vblank_wait();
    expect("228 hblank interrupts a frame", irq_count[1], 228);

    /* VCount match: once a frame, with the flag set while the line matches. */
    REG_DISPSTAT = 0x0008 | 0x0020 | (100 << 8);
    REG_IE = IRQ_VBLANK | IRQ_VCOUNT;
    bios_vblank_wait();
    irq_count[2] = 0;
    for (int i = 0; i < 3; i++)
        bios_vblank_wait();
    expect("one vcount interrupt a frame", irq_count[2], 3);
    wait_vcount(100);
    expect("vcounter flag while the line matches", REG_DISPSTAT & 4, 4);
    wait_vcount(101);
    expect("vcounter flag clear on the next line", REG_DISPSTAT & 4, 0);
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    /* IME off: the request stays pending in IF until IME is set again. */
    bios_vblank_wait();
    REG_IME = 0;
    uint32_t before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("ime off: no interrupt", irq_count[0], before);
    expect("ime off: request pending", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IME = 1;
    spin(10);
    expect("ime on: pending interrupt delivered", irq_count[0], before + 1);

    /* IE off: same. */
    REG_IE = 0;
    before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("ie off: no interrupt", irq_count[0], before);
    REG_IE = IRQ_VBLANK;
    spin(10);
    expect("ie on: pending interrupt delivered", irq_count[0], before + 1);

    /* The CPSR's I bit masks interrupts; clearing it with MSR lets them in again (taken at
     * the next scheduler event, so within a scanline). */
    set_cpsr_control(0x9F);
    before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("cpsr I set: no interrupt", irq_count[0], before);
    set_cpsr_control(0x1F);
    wait_vcount(163);
    expect("cpsr I clear: pending interrupt delivered", irq_count[0], before + 1);

    /* Halt sleeps until the next enabled request. */
    wait_vcount(20);
    before = irq_count[0];
    bios_halt();
    line = REG_VCOUNT;  /* read before print() takes its time */
    expect("halt wakes for vblank", irq_count[0], before + 1);
    expect("halt returns in line 160", line, 160);

    /* IntrWait: with discard 0, a flag already set in BIOS_IF returns at once. */
    wait_vcount(30);
    BIOS_IF |= IRQ_VBLANK;
    bios_intr_wait(0, IRQ_VBLANK);
    line = REG_VCOUNT;
    expect("intrwait returns at once for an old flag", line, 30);
    expect("intrwait clears the flag it waited for", BIOS_IF & IRQ_VBLANK, 0);
    BIOS_IF |= IRQ_VBLANK;
    bios_intr_wait(1, IRQ_VBLANK);
    line = REG_VCOUNT;
    expect("intrwait with discard waits for a new one", line, 160);

    /* One 32-bit store to 0x04000200 sets IE and acknowledges IF together. */
    REG_IME = 0;
    wait_vcount(10);
    wait_vcount(161);
    REG32(0x04000200) = IRQ_VBLANK | (IRQ_VBLANK << 16);
    expect("32-bit store sets IE", REG_IE, IRQ_VBLANK);
    expect("32-bit store acknowledges IF", REG_IF & IRQ_VBLANK, 0);

    /* The BIOS's interrupt waits turn IME on themselves. */
    before = irq_count[0];
    bios_vblank_wait();
    expect("vblank wait turns IME on", REG_IME, 1);
    expect("vblank wait with IME off still returns", irq_count[0], before + 1);

    /* A handler that re-enables interrupts gets a nested one. */
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    IRQ_VECTOR = (uint32_t)nesting_handler;
    nested_seen = 0;
    while (!nested_seen) {}
    irq_init();
    expect("an interrupt nested in a handler", nested_seen, 1);
    expect("system mode again after the nested handlers", get_cpsr() & 0xFF, 0x1F);

    /* Registers survive interrupts: the same sum with and without them. */
    REG_IME = 0;
    uint32_t quiet = busy_sum(300000);
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    REG_IME = 1;
    irq_count[1] = 0;
    uint32_t noisy = busy_sum(300000);
    check("the loop was interrupted", irq_count[1] > 100);
    expect("registers survive interrupts", noisy, quiet);

    test_end();
    return 0;
}
```

Create `tests/gbaroms/reset_in_irq.c`:
```c
/* SoftReset called from an interrupt handler, the way games check the reset key combo in
 * their VBlank handler: the game starts again in system mode. */
#include "testlib.h"

#define MARKER MEM32(0x0203FFF0)
#define MAGIC 0x49525152u

__attribute__((target("arm"), section(".iwram"), noinline)) static void resetting_handler(void)
{
    REG_IF = REG_IE & REG_IF;
    if (MARKER != MAGIC) {
        MARKER = MAGIC;
        __asm__ volatile("svc #0");
    }
}

int main(void)
{
    if (MARKER == MAGIC) {
        REG_IME = 0;  /* SoftReset cleared the IRQ vector; I/O registers kept their values */
        MARKER = 0;
        expect("soft reset from an interrupt handler: system mode", get_cpsr() & 0xFF, 0x1F);
        expect("the reset cleared the IRQ vector", IRQ_VECTOR, 0);
        test_end();
    }
    IRQ_VECTOR = (uint32_t)resetting_handler;
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    REG_IME = 1;
    for (;;) {}
    return 0;
}
```

Create `tests/gbaroms/err_no_handler.c`:
```c
/* Enables the VBlank interrupt without setting a handler at 0x03007FFC. */
#include "testlib.h"

int main(void)
{
    print("before");
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    REG_IME = 1;
    for (;;) {}
    return 0;
}
```

Create `tests/runtime/test_interrupts.py`:
```python
from romtest import run_test


def test_scanlines_interrupts_and_waits():
    run_test("interrupts").assert_passed()


def test_soft_reset_from_an_interrupt_handler():
    run_test("reset_in_irq").assert_passed()


def test_an_interrupt_without_a_handler_is_an_error():
    run = run_test("err_no_handler")
    assert run.status == 3
    assert "no handler is set at 0x03007FFC" in run.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/runtime/test_interrupts.py -v`
Expected: FAIL, 3 failed.
- `interrupts` exits with 3: `BIOS function 0x05 is not implemented yet`.
- `reset_in_irq` and `err_no_handler` run into the frame limit, exiting with 4 (`stopped after 600 frames`), because nothing delivers interrupts yet.

- [ ] **Step 3: Deliver interrupts, Halt and the BIOS waits**

Create `src/gbaport/runtime/scheduler.c` (replacing the Task 2 version):
```c
/* scheduler.c - scanline timing, timed events and interrupt delivery.
 *
 * Recompiled code runs gba_events() once ctx->cycles reaches ctx->next_event. It runs
 * every event that is due, in time order, then delivers an interrupt if one is requested,
 * enabled (IE, IME) and not masked by the CPSR's I bit. Writes that can make an interrupt
 * deliverable pull next_event forward to "now", so the interrupt is taken at the next loop
 * head or function exit. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define NEVER UINT64_MAX
#define BIOS_IRQ_RETURN 0x00000138u  /* where the BIOS's IRQ code expects the handler back */
#define IRQ_VECTOR 0x03007FFCu

static uint64_t earliest(const GbaRuntime *rt, int *which)
{
    uint64_t when = NEVER;
    for (int i = 0; i < GBA_EVENT_COUNT; i++) {
        if (rt->event_at[i] < when) {
            when = rt->event_at[i];
            *which = i;
        }
    }
    return when;
}

static int irq_ready(const GbaRuntime *rt)
{
    return (IO(rt, GBA_REG_IME) & 1) && (IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & 0x3FFF) &&
           !(rt->cpu.cpsr_ctrl & 0x80);
}

void gba_reschedule(GbaRuntime *rt)
{
    int which;
    rt->cpu.next_event = irq_ready(rt) ? rt->cpu.cycles : earliest(rt, &which);
}

void gba_irq_changed(GbaRuntime *rt)
{
    if (irq_ready(rt))
        rt->cpu.next_event = rt->cpu.cycles;
}

void gba_request_irq(GbaRuntime *rt, uint16_t bits)
{
    IO(rt, GBA_REG_IF) |= bits;
    gba_irq_changed(rt);
}

static void schedule_line(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = rt->line_start + GBA_CYCLES_HDRAW;
    rt->event_at[GBA_EVENT_LINE] = rt->line_start + GBA_CYCLES_LINE;
}

void gba_scheduler_start(GbaRuntime *rt)
{
    for (int i = 0; i < GBA_EVENT_COUNT; i++)
        rt->event_at[i] = NEVER;
    rt->line_start = rt->cpu.cycles;
    rt->frames = 0;
    IO(rt, GBA_REG_VCOUNT) = 0;
    schedule_line(rt);
    gba_reschedule(rt);
}

static void hblank(GbaRuntime *rt)
{
    rt->event_at[GBA_EVENT_HBLANK] = NEVER;
    IO(rt, GBA_REG_DISPSTAT) |= 2;
    if (IO(rt, GBA_REG_DISPSTAT) & 0x10)
        gba_request_irq(rt, GBA_IRQ_HBLANK);
}

static void line_end(GbaRuntime *rt, uint64_t when)
{
    uint16_t line = (uint16_t)((IO(rt, GBA_REG_VCOUNT) + 1) % GBA_LINES);
    uint16_t stat = IO(rt, GBA_REG_DISPSTAT) & ~2;
    rt->line_start = when;
    schedule_line(rt);
    IO(rt, GBA_REG_VCOUNT) = line;
    if (line == GBA_VISIBLE_LINES)
        stat |= 1;
    else if (line == GBA_LINES - 1)
        stat &= ~1;  /* the VBlank flag is clear again in the last line */
    int match = line == (stat >> 8);
    stat = (uint16_t)(match ? stat | 4 : stat & ~4);
    IO(rt, GBA_REG_DISPSTAT) = stat;
    if (match && (stat & 0x20))
        gba_request_irq(rt, GBA_IRQ_VCOUNT);
    if (line == GBA_VISIBLE_LINES) {
        if (stat & 0x08)
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        rt->frames++;
        if (rt->host.frame)
            rt->host.frame(rt, rt->host.user);
    }
}

/* Run every event that is due by ctx->cycles, in time order. */
static void advance(GbaRuntime *rt)
{
    for (;;) {
        int which = 0;
        uint64_t when = earliest(rt, &which);
        if (when > rt->cpu.cycles)
            break;
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else
            line_end(rt, when);
    }
    gba_reschedule(rt);
}

/* What the BIOS does on an IRQ: IRQ mode, push r0-r3, r12, lr; call [0x03007FFC] with
 * lr = 0x138; pop; return with CPSR = SPSR. The interrupted code resumes in C where it
 * called gba_events, so lr_irq (the resume address) is not known and is pushed as 0. */
static void deliver(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    uint32_t cpsr = gba_cpsr(ctx);
    uint32_t handler = gba_read32(ctx, IRQ_VECTOR);
    if (handler == 0)
        gba_fail(rt, "an interrupt was requested but no handler is set at 0x03007FFC");
    gba_switch_mode(ctx, GBA_MODE_IRQ);
    ctx->spsr = cpsr;
    ctx->cpsr_ctrl = (ctx->cpsr_ctrl & ~0xBFu) | 0x80u | GBA_MODE_IRQ;  /* ARM, I set, F kept */
    ctx->r[14] = 0;
    uint32_t sp = ctx->r[13] - 24;
    static const int saved[6] = {0, 1, 2, 3, 12, 14};
    for (int i = 0; i < 6; i++)
        gba_write32(ctx, sp + 4 * i, ctx->r[saved[i]]);
    ctx->r[13] = sp;
    ctx->r[0] = 0x04000000u;
    ctx->r[14] = BIOS_IRQ_RETURN;
    ctx->cycles += 40;  /* the BIOS's IRQ entry and exit */
    rt->bios_bus = 0xE55EC002u;
    gba_call(ctx, handler, BIOS_IRQ_RETURN);
    sp = ctx->r[13];
    for (int i = 0; i < 6; i++)
        ctx->r[saved[i]] = gba_read32(ctx, sp + 4 * i);
    ctx->r[13] = sp + 24;
    gba_restore_cpsr(ctx);
    rt->bios_bus = 0xE25EF004u;
    gba_reschedule(rt);
}

void gba_events(GbaCtx *ctx)
{
    GbaRuntime *rt = gba_rt(ctx);
    advance(rt);
    while (irq_ready(rt))
        deliver(rt);
}

/* Halt: skip ahead from event to event until an interrupt is requested and enabled in IE
 * (IME and the CPSR do not matter for waking up), then deliver it if they allow. */
void gba_halt(GbaRuntime *rt)
{
    GbaCtx *ctx = &rt->cpu;
    while (!(IO(rt, GBA_REG_IE) & IO(rt, GBA_REG_IF) & 0x3FFF)) {
        int which;
        uint64_t when = earliest(rt, &which);
        if (ctx->cycles < when)
            ctx->cycles = when;
        advance(rt);
    }
    while (irq_ready(rt))
        deliver(rt);
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
 * - DMA source, destination and count registers are write-only: they read as 0. */
```
with:
```c
 * - DMA source, destination and count registers are write-only: they read as 0.
 * - Writing IE, IF or IME can make an interrupt deliverable.
 * - Writing HALTCNT halts or stops the CPU. */
```

In `src/gbaport/runtime/io.c`, replace:
```c
    case GBA_REG_IE:
        IO(rt, offset) = merged & 0x3FFF;
        return;
    case GBA_REG_IF:
        IO(rt, offset) = (uint16_t)(old & ~(value & mask));  /* writing 1 acknowledges */
        return;
    case GBA_REG_IME:
        IO(rt, offset) = merged & 1;
        return;
    case GBA_REG_WAITCNT:
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        return;
    case GBA_REG_POSTFLG:  /* POSTFLG in the low byte, HALTCNT (write-only) in the high one */
        IO(rt, offset) = merged & 0x0001;
        return;
```
with:
```c
    case GBA_REG_IE:
        IO(rt, offset) = merged & 0x3FFF;
        gba_irq_changed(rt);
        return;
    case GBA_REG_IF:
        IO(rt, offset) = (uint16_t)(old & ~(value & mask));  /* writing 1 acknowledges */
        gba_irq_changed(rt);
        return;
    case GBA_REG_IME:
        IO(rt, offset) = merged & 1;
        gba_irq_changed(rt);
        return;
    case GBA_REG_WAITCNT:
        IO(rt, offset) = merged & 0x7FFF;  /* bit 15 reads 0: a GBA cartridge */
        return;
    case GBA_REG_POSTFLG:  /* POSTFLG in the low byte, HALTCNT (write-only) in the high one */
        IO(rt, offset) = merged & 0x0001;
        if (mask & 0xFF00) {
            if (value & 0x8000)
                gba_end(rt, GBA_END_STOPPED);  /* Stop: nothing wakes a headless run */
            gba_halt(rt);
        }
        return;
```

In `src/gbaport/runtime/bios.c`, replace:
```c
 * This file has the resets and Stop so far. The other BIOS functions (0x02 and 0x04-0x2A:
 * Halt, the interrupt waits, arithmetic, copies, decompression, ...) are not implemented
 * yet and end the run with an error that names them. Numbers above 0x2A do not exist in
 * the BIOS; the first one is reported and they are ignored. */
```
with:
```c
 * This file has the calls that control the CPU: resets, Halt, Stop and the interrupt
 * waits. The other BIOS functions (0x06-0x2A: arithmetic, copies, decompression, ...)
 * are not implemented yet and end the run with an error that names them. Numbers above
 * 0x2A do not exist in the BIOS; the first one is reported and they are ignored. */
```

In `src/gbaport/runtime/bios.c`, replace:
```c
#define IO(rt, offset) ((rt)->io[(offset) >> 1])
```
with:
```c
#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define BIOS_IF 0x03007FF8u  /* the flags a game's IRQ handler sets for IntrWait */
```

In `src/gbaport/runtime/bios.c`, replace:
```c
void gba_swi(GbaCtx *ctx, uint32_t number)
```
with:
```c
/* IntrWait: wait until the IRQ handler has set one of `flags` in BIOS_IF, then clear it.
 * With `discard`, flags that were already set do not count. The BIOS turns IME on. */
static void intr_wait(GbaRuntime *rt, uint32_t discard, uint32_t flags)
{
    GbaCtx *ctx = &rt->cpu;
    IO(rt, GBA_REG_IME) = 1;
    if (ctx->cpsr_ctrl & 0x80)
        gba_fail(rt, "IntrWait was called with interrupts disabled in the CPSR; it would never return");
    if (discard)
        gba_write16(ctx, BIOS_IF, gba_read16(ctx, BIOS_IF) & ~flags);
    for (;;) {
        uint32_t set = gba_read16(ctx, BIOS_IF);
        if (set & flags) {
            gba_write16(ctx, BIOS_IF, set & ~flags);
            return;
        }
        gba_halt(rt);
    }
}

void gba_swi(GbaCtx *ctx, uint32_t number)
```

In `src/gbaport/runtime/bios.c`, replace:
```c
    case 0x01: register_ram_reset(rt, ctx->r[0]); break;
    case 0x03: gba_end(rt, GBA_END_STOPPED); break;  /* nothing can wake a headless run */
```
with:
```c
    case 0x01: register_ram_reset(rt, ctx->r[0]); break;
    case 0x02: gba_halt(rt); break;
    case 0x03: gba_end(rt, GBA_END_STOPPED); break;  /* nothing can wake a headless run */
    case 0x04: intr_wait(rt, ctx->r[0], ctx->r[1]); break;
    case 0x05:
        ctx->r[0] = ctx->r[1] = 1;
        intr_wait(rt, 1, GBA_IRQ_VBLANK);
        break;
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 548 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime tests/gbaroms tests/runtime/test_interrupts.py
git commit -m "feat: interrupts the BIOS way, Halt and the interrupt waits"
```

---

### Task 4: Timers

**Files:**
- Create: `src/gbaport/runtime/timers.c`, `tests/gbaroms/timers.c`
- Modify: `src/gbaport/runtime/io.c` (timer registers), `src/gbaport/runtime/scheduler.c` (overflow events), `src/gbaport/native/build.py` (compile `timers.c`)
- Test: `tests/runtime/test_timers.py`

**Interfaces:**
- Consumes: Task 3's scheduler (`gba_reschedule`, `gba_request_irq`, the `GBA_EVENT_TIMER0 + n` slots).
- Produces: `gba_timer_write(rt, n, control)`, `gba_timer_counter(rt, n)`, `gba_timer_overflow(rt, n, when)`.
- **Counters:**
  - A ticking timer's counter is `counter + (cycles - start) >> shift`, with shifts 0, 6, 8 and 10.
  - It wraps into the reload period while an overflow is due but not yet run.
- **Overflows:**
  - Each overflow is a scheduler event.
  - It reloads the counter, requests an interrupt when control bit 6 is set, and steps the next timer if that one counts up.
  - Writes to TMxCNT_L set the reload value; enabling a timer loads it.

- [ ] **Step 1: Write the failing test**

Create `tests/gbaroms/timers.c`:
```c
/* Timers: counting, prescalers, reload, overflow interrupts, count-up cascades, and the
 * frame length measured in timer ticks (280896 cycles a frame). */
#include "testlib.h"

enum { ENABLE = 0x80, IRQ = 0x40, COUNT_UP = 0x04, PRESCALE_64 = 1, PRESCALE_1024 = 3 };

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    REG_TM_CNT_L(0) = 0x1234;
    REG_TM_CNT_H(0) = ENABLE | PRESCALE_1024;
    uint16_t started = REG_TM_CNT_L(0);
    expect("a timer starts at its reload value", started, 0x1234);
    expect("control reads back", REG_TM_CNT_H(0), ENABLE | PRESCALE_1024);
    uint16_t a = REG_TM_CNT_L(0);
    for (volatile int i = 0; i < 2000; i++) {}
    uint16_t b = REG_TM_CNT_L(0);
    check("a running timer counts up", b > a);
    REG_TM_CNT_H(0) = 0;
    a = REG_TM_CNT_L(0);
    for (volatile int i = 0; i < 2000; i++) {}
    expect("a stopped timer holds its count", REG_TM_CNT_L(0), a);

    /* A fast timer (a 16-cycle period) read when its overflow is already due but the
     * scheduler has not run yet still reads inside its period. */
    REG_TM_CNT_L(0) = 0xFFF0;
    REG_TM_CNT_H(0) = ENABLE;
    uint32_t lowest = 0xFFFF;
    for (int i = 0; i < 200; i++) {
        uint16_t value = REG_TM_CNT_L(0);
        if (value < lowest)
            lowest = value;
    }
    REG_TM_CNT_H(0) = 0;
    check("a fast timer never reads below its reload value", lowest >= 0xFFF0);

    /* A frame in 1024-cycle ticks: 280896 / 1024 = 274.3. */
    bios_vblank_wait();
    REG_TM_CNT_L(1) = 0;
    REG_TM_CNT_H(1) = ENABLE | PRESCALE_1024;
    bios_vblank_wait();
    uint16_t ticks = REG_TM_CNT_L(1);
    check("a frame is 274-275 ticks at 1024 cycles", ticks >= 274 && ticks <= 275);
    REG_TM_CNT_H(1) = 0;

    /* Overflow interrupts: a period of 23408 cycles is exactly 12 a frame. */
    REG_IE = IRQ_VBLANK | IRQ_TIMER0;
    bios_vblank_wait();
    REG_TM_CNT_L(0) = (uint16_t)(0x10000 - 23408);
    REG_TM_CNT_H(0) = ENABLE | IRQ;
    irq_count[3] = 0;
    for (int i = 0; i < 5; i++)
        bios_vblank_wait();
    uint32_t overflows = irq_count[3];
    check("12 overflow interrupts a frame", overflows >= 59 && overflows <= 61);
    REG_TM_CNT_H(0) = 0;

    /* Count-up: timer 3 counts timer 2's overflows (every 256 cycles: 1097.25 a frame). */
    REG_TM_CNT_L(2) = 0xFF00;
    REG_TM_CNT_L(3) = 0;
    REG_TM_CNT_H(3) = ENABLE | COUNT_UP;
    bios_vblank_wait();
    REG_TM_CNT_H(2) = ENABLE;
    uint16_t c0 = REG_TM_CNT_L(3);
    bios_vblank_wait();
    uint16_t c1 = REG_TM_CNT_L(3);
    REG_TM_CNT_H(2) = 0;
    uint16_t c2 = REG_TM_CNT_L(3);
    check("count-up timer counts overflows", (uint16_t)(c1 - c0) >= 1096 && (uint16_t)(c1 - c0) <= 1098);
    for (volatile int i = 0; i < 2000; i++) {}
    expect("a count-up timer stands still without overflows", REG_TM_CNT_L(3), c2);

    /* A count-up timer that overflows reloads and requests its own interrupt. */
    REG_IE = IRQ_VBLANK | (IRQ_TIMER0 << 3);
    REG_TM_CNT_L(3) = 0xFFF0;  /* 16 overflows of timer 2 */
    REG_TM_CNT_H(3) = 0;
    REG_TM_CNT_H(3) = ENABLE | COUNT_UP | IRQ;
    irq_count[6] = 0;
    REG_TM_CNT_H(2) = ENABLE;
    for (volatile int i = 0; i < 4000; i++) {}
    REG_TM_CNT_H(2) = 0;
    check("cascade overflow interrupt", irq_count[6] >= 1);
    check("cascade reloads", REG_TM_CNT_L(3) >= 0xFFF0);

    test_end();
    return 0;
}
```

Create `tests/runtime/test_timers.py`:
```python
from romtest import run_test


def test_timers():
    run_test("timers").assert_passed()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_timers.py -v`
Expected: FAIL. The ROM runs to its end, but the log has `FAIL a running timer counts up`, because the counter registers only hold what was written.

- [ ] **Step 3: Write the timers**

Create `src/gbaport/runtime/timers.c`:
```c
/* timers.c - the four 16-bit timers.
 *
 * A ticking timer is not stepped: its counter is worked out from the cycles since it last
 * held a known value, and its overflow is a scheduler event. Count-up timers (bit 2, not
 * timer 0) tick when the timer below them overflows. */
#include "gba_runtime.h"

#define NEVER UINT64_MAX

static const int prescale_shift[4] = {0, 6, 8, 10};  /* 1, 64, 256 or 1024 cycles a tick */

static int ticking(const GbaTimer *t, int n)
{
    return (t->control & 0x80) && !(n > 0 && (t->control & 0x04));
}

static int shift(const GbaTimer *t) { return prescale_shift[t->control & 3]; }

uint16_t gba_timer_counter(GbaRuntime *rt, int n)
{
    const GbaTimer *t = &rt->timer[n];
    if (!ticking(t, n))
        return t->counter;
    uint64_t ticks = (rt->cpu.cycles - t->start) >> shift(t);
    uint64_t first = 0x10000u - t->counter;  /* ticks until the next overflow */
    if (ticks < first)
        return (uint16_t)(t->counter + ticks);
    return (uint16_t)(t->reload + (ticks - first) % (0x10000u - t->reload));  /* overflow not yet run */
}

static void schedule(GbaRuntime *rt, int n)
{
    const GbaTimer *t = &rt->timer[n];
    rt->event_at[GBA_EVENT_TIMER0 + n] =
        ticking(t, n) ? t->start + ((uint64_t)(0x10000u - t->counter) << shift(t)) : NEVER;
}

void gba_timer_write(GbaRuntime *rt, int n, uint16_t control)
{
    GbaTimer *t = &rt->timer[n];
    int starting = !(t->control & 0x80) && (control & 0x80);
    t->counter = gba_timer_counter(rt, n);  /* keep the count under the old settings */
    t->start = rt->cpu.cycles;
    t->control = control & 0xC7;
    rt->io[(GBA_REG_TM0CNT_L + 4 * n + 2) >> 1] = t->control;
    if (starting)
        t->counter = t->reload;
    schedule(rt, n);
    gba_reschedule(rt);
}

static void overflowed(GbaRuntime *rt, int n);

static void count_up(GbaRuntime *rt, int n)
{
    GbaTimer *t = &rt->timer[n];
    if (!(t->control & 0x80) || !(t->control & 0x04))
        return;
    if (++t->counter == 0) {
        t->counter = t->reload;
        overflowed(rt, n);
    }
}

static void overflowed(GbaRuntime *rt, int n)
{
    if (rt->timer[n].control & 0x40)
        gba_request_irq(rt, (uint16_t)(GBA_IRQ_TIMER0 << n));
    if (n < 3)
        count_up(rt, n + 1);
}

void gba_timer_overflow(GbaRuntime *rt, int n, uint64_t when)
{
    GbaTimer *t = &rt->timer[n];
    t->counter = t->reload;
    t->start = when;
    schedule(rt, n);
    overflowed(rt, n);
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
 * - Writing HALTCNT halts or stops the CPU. */
```
with:
```c
 * - Writing HALTCNT halts or stops the CPU.
 * - Timer counters are worked out from the cycle count; writes set the reload value. */
```

In `src/gbaport/runtime/io.c`, replace:
```c
        return 0;  /* source, destination and count are write-only */
    if (offset == GBA_REG_KEYINPUT)
```
with:
```c
        return 0;  /* source, destination and count are write-only */
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H && !(offset & 2))
        return gba_timer_counter(rt, (int)(offset - GBA_REG_TM0CNT_L) / 4);
    if (offset == GBA_REG_KEYINPUT)
```

In `src/gbaport/runtime/io.c`, replace:
```c
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    switch (offset) {
```
with:
```c
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H) {
        int n = (int)(offset - GBA_REG_TM0CNT_L) / 4;
        if (offset & 2)
            gba_timer_write(rt, n, merged);
        else
            rt->timer[n].reload = merged;  /* used at the next start or overflow */
        return;
    }
    switch (offset) {
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else
            line_end(rt, when);
```
with:
```c
        if (which == GBA_EVENT_HBLANK)
            hblank(rt);
        else if (which == GBA_EVENT_LINE)
            line_end(rt, when);
        else
            gba_timer_overflow(rt, which - GBA_EVENT_TIMER0, when);
```

In `src/gbaport/native/build.py`, replace:
```python
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "bios.c")
```
with:
```python
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "bios.c")
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 549 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms/timers.c tests/runtime/test_timers.py
git commit -m "feat: timers with overflow interrupts and count-up cascades"
```

---

### Task 5: DMA

**Files:**
- Create: `src/gbaport/runtime/dma.c`, `tests/gbaroms/dma.c`
- Modify: `src/gbaport/runtime/io.c` (starting channels), `src/gbaport/runtime/scheduler.c` (VBlank and HBlank triggers), `src/gbaport/native/build.py` (compile `dma.c`)
- Test: `tests/runtime/test_dma.py`

**Interfaces:**
- Consumes: Task 3's `gba_request_irq` and the HBlank and line events.
- Produces: `gba_dma_write(rt, n, control)` (called for every DMAxCNT_H write) and `gba_dma_trigger(rt, timing)` (1 = VBlank, 2 = HBlank, visible lines only).
- **Starting a channel:**
  - The enable bit going from 0 to 1 latches the masked source, destination and count.
  - A count of 0 means 0x4000 (channels 0-2) or 0x10000 (channel 3).
- **Transfers:**
  - Timing 0 runs at once.
  - Transfers go through the memory accessors.
  - A cartridge source cannot count down.
- **After a transfer:**
  - Repeat keeps a VBlank or HBlank channel enabled and reloads the count, plus the destination when its control is 3. Otherwise the enable bit clears.
  - Control bit 14 requests the channel's interrupt.

- [ ] **Step 1: Write the failing test**

Create `tests/gbaroms/dma.c`:
```c
/* DMA: immediate copies and fills, address control, word counts, the end interrupt, and
 * VBlank and HBlank transfers with repeat. */
#include "testlib.h"

enum {
    ENABLE = 0x8000, IRQ = 0x4000, WORDS = 0x0400, REPEAT = 0x0200,
    AT_VBLANK = 0x1000, AT_HBLANK = 0x2000,
    DST_DEC = 0x0020, DST_FIXED = 0x0040, DST_RELOAD = 0x0060, SRC_FIXED = 0x0100,
};

#define EW16(i) MEM16(0x02010000 + 2 * (i))

static void start(int n, uint32_t src, uint32_t dst, uint32_t count, uint32_t control)
{
    REG_DMA_SAD(n) = src;
    REG_DMA_DAD(n) = dst;
    REG_DMA_CNT(n) = count | (control << 16);
}

static void clear(uint32_t halfwords)
{
    for (uint32_t i = 0; i < halfwords; i++)
        EW16(i) = 0;
}

static uint32_t count_value(uint16_t value, uint32_t limit)
{
    uint32_t n = 0;
    while (n < limit && EW16(n) == value)
        n++;
    return n;
}

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    for (int i = 0; i < 16; i++)
        MEM32(0x02000000 + 4 * i) = 0x01010101u * (uint32_t)i;
    start(3, 0x02000000, 0x03004000, 16, ENABLE | WORDS);
    int same = 1;
    for (int i = 0; i < 16; i++)
        same &= MEM32(0x03004000 + 4 * i) == 0x01010101u * (uint32_t)i;
    check("immediate 32-bit copy", same);
    expect("an immediate transfer clears its enable bit", REG_DMA_CNT_H(3) & ENABLE, 0);

    MEM16(0x02000100) = 0xBEEF;
    clear(8);
    start(3, 0x02000100, 0x02010000, 8, ENABLE | SRC_FIXED);
    expect("fixed source fills", count_value(0xBEEF, 9), 8);

    MEM16(0x02000200) = 1, MEM16(0x02000202) = 2, MEM16(0x02000204) = 3;
    clear(3);
    start(3, 0x02000200, 0x02010004, 3, ENABLE | DST_DEC);
    expect("decrementing destination reverses", EW16(0) << 8 | EW16(1) << 4 | EW16(2), 0x321);

    MEM16(0x02000300) = 0x7777;
    clear(0x4001);
    start(0, 0x02000300, 0x02010000, 0, ENABLE | SRC_FIXED);  /* count 0: 0x4000 units */
    expect("word count 0 means 0x4000 on DMA0", count_value(0x7777, 0x4001), 0x4000);

    REG_IE = IRQ_VBLANK | (IRQ_DMA0 << 3);
    irq_count[11] = 0;
    start(3, 0x02000300, 0x02010000, 4, ENABLE | IRQ);
    for (volatile int i = 0; i < 10; i++) {}
    expect("end-of-transfer interrupt", irq_count[11], 1);
    REG_IE = IRQ_VBLANK;

    /* VBlank DMA with repeat: one halfword each VBlank; the destination keeps counting. */
    MEM16(0x02000400) = 0xABCD;
    clear(8);
    bios_vblank_wait();
    start(1, 0x02000400, 0x02010000, 1, ENABLE | REPEAT | AT_VBLANK | SRC_FIXED);
    for (int i = 0; i < 4; i++)
        bios_vblank_wait();
    REG_DMA_CNT_H(1) = 0;
    expect("vblank dma runs once a vblank", count_value(0xABCD, 8), 4);

    /* Reloading the destination: every VBlank writes the same two halfwords. */
    clear(8);
    MEM16(0x02000400) = 0x1111;
    start(1, 0x02000400, 0x02010000, 2, ENABLE | REPEAT | AT_VBLANK | SRC_FIXED | DST_RELOAD);
    for (int i = 0; i < 3; i++)
        bios_vblank_wait();
    REG_DMA_CNT_H(1) = 0;
    expect("destination reload rewrites the same place", count_value(0x1111, 8), 2);

    /* HBlank DMA: once a visible line, 160 a frame. */
    MEM16(0x02000400) = 0x2222;
    clear(240);
    bios_vblank_wait();
    start(2, 0x02000400, 0x02010000, 1, ENABLE | REPEAT | AT_HBLANK | SRC_FIXED);
    bios_vblank_wait();
    REG_DMA_CNT_H(2) = 0;
    expect("hblank dma runs in the 160 visible lines", count_value(0x2222, 240), 160);

    test_end();
    return 0;
}
```

Create `tests/runtime/test_dma.py`:
```python
from romtest import run_test


def test_dma():
    run_test("dma").assert_passed()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/runtime/test_dma.py -v`
Expected: FAIL. The log has `FAIL immediate 32-bit copy`, because nothing transfers yet.

- [ ] **Step 3: Write the DMA channels**

Create `src/gbaport/runtime/dma.c`:
```c
/* dma.c - the four DMA channels.
 *
 * Starting a channel (enable bit 0 -> 1) latches its source, destination and count. An
 * immediate channel runs at once; VBlank and HBlank channels run when the scheduler
 * triggers them. Special timing (sound FIFOs, video capture) is not handled yet. The
 * transfer goes through the normal memory accessors, so it sees every region's rules. */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])

static const uint32_t src_mask[4] = {0x07FFFFFF, 0x0FFFFFFF, 0x0FFFFFFF, 0x0FFFFFFF};
static const uint32_t dst_mask[4] = {0x07FFFFFF, 0x07FFFFFF, 0x07FFFFFF, 0x0FFFFFFF};

static uint32_t base(int n) { return GBA_REG_DMA0SAD + 12u * (uint32_t)n; }

static uint32_t reg32(const GbaRuntime *rt, uint32_t offset)
{
    return IO(rt, offset) | (uint32_t)IO(rt, offset + 2) << 16;
}

static uint32_t word_count(const GbaRuntime *rt, int n)
{
    uint32_t mask = n == 3 ? 0xFFFF : 0x3FFF;
    uint32_t count = IO(rt, base(n) + 8) & mask;
    return count ? count : mask + 1;  /* 0 means the maximum */
}

static int32_t step(int control, uint32_t size)
{
    switch (control) {
    case 1: return -(int32_t)size;  /* decrement */
    case 2: return 0;               /* fixed */
    default: return (int32_t)size;  /* increment (3: increment, then reload the destination) */
    }
}

static void run(GbaRuntime *rt, int n)
{
    GbaCtx *ctx = &rt->cpu;
    GbaDma *d = &rt->dma[n];
    uint16_t control = IO(rt, base(n) + 10);
    uint32_t size = control & 0x0400 ? 4 : 2;
    int dst_control = (control >> 5) & 3, src_control = (control >> 7) & 3;
    if (d->src >= 0x08000000u && d->src < 0x0E000000u && src_control == 1)
        src_control = 0;  /* the cartridge bus cannot count down */
    int32_t dst_step = step(dst_control, size), src_step = step(src_control, size);
    for (uint32_t i = 0; i < d->count; i++) {
        if (size == 4)
            gba_write32(ctx, d->dst & ~3u, gba_read32(ctx, d->src & ~3u));
        else
            gba_write16(ctx, d->dst & ~1u, gba_read16(ctx, d->src & ~1u));
        d->src += (uint32_t)src_step;
        d->dst += (uint32_t)dst_step;
    }
    ctx->cycles += 4 + 2 * (uint64_t)d->count;
    int timing = (control >> 12) & 3;
    if ((control & 0x0200) && timing != 0) {  /* repeat: wait for the next trigger */
        d->count = word_count(rt, n);
        if (dst_control == 3)
            d->dst = reg32(rt, base(n) + 4) & dst_mask[n];
    } else {
        IO(rt, base(n) + 10) = control & ~0x8000;
    }
    if (control & 0x4000)
        gba_request_irq(rt, (uint16_t)(GBA_IRQ_DMA0 << n));
}

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control)
{
    uint16_t old = IO(rt, base(n) + 10);
    IO(rt, base(n) + 10) = control;
    if ((old & 0x8000) || !(control & 0x8000))
        return;
    GbaDma *d = &rt->dma[n];
    d->src = reg32(rt, base(n)) & src_mask[n];
    d->dst = reg32(rt, base(n) + 4) & dst_mask[n];
    d->count = word_count(rt, n);
    if (((control >> 12) & 3) == 0)
        run(rt, n);
}

void gba_dma_trigger(GbaRuntime *rt, int timing)
{
    for (int n = 0; n < 4; n++) {
        uint16_t control = IO(rt, base(n) + 10);
        if ((control & 0x8000) && ((control >> 12) & 3) == timing)
            run(rt, n);
    }
}
```

In `src/gbaport/runtime/io.c`, replace:
```c
 * - Timer counters are worked out from the cycle count; writes set the reload value. */
```
with:
```c
 * - Timer counters are worked out from the cycle count; writes set the reload value.
 * - Starting a DMA channel latches its registers and may run it at once. */
```

In `src/gbaport/runtime/io.c`, replace:
```c
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H) {
```
with:
```c
    uint16_t merged = (uint16_t)((old & ~mask) | (value & mask));
    int channel = dma_channel(offset);
    if (channel >= 0) {
        gba_dma_write(rt, channel, merged);
        return;
    }
    if (offset >= GBA_REG_TM0CNT_L && offset <= GBA_REG_TM3CNT_H) {
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
        gba_request_irq(rt, GBA_IRQ_HBLANK);
}
```
with:
```c
        gba_request_irq(rt, GBA_IRQ_HBLANK);
    if (IO(rt, GBA_REG_VCOUNT) < GBA_VISIBLE_LINES)  /* no HBlank DMA during VBlank */
        gba_dma_trigger(rt, 2);
}
```

In `src/gbaport/runtime/scheduler.c`, replace:
```c
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        rt->frames++;
```
with:
```c
            gba_request_irq(rt, GBA_IRQ_VBLANK);
        gba_dma_trigger(rt, 1);
        rt->frames++;
```

In `src/gbaport/native/build.py`, replace:
```python
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "bios.c")
```
with:
```python
RUNTIME_SOURCES = ("runtime.c", "memory.c", "io.c", "scheduler.c", "timers.c", "dma.c", "bios.c")
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 550 passed; ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/gbaport/runtime src/gbaport/native/build.py tests/gbaroms/dma.c tests/runtime/test_dma.py
git commit -m "feat: DMA channels: immediate, VBlank and HBlank transfers"
```

---

### Task 6: README, spec, and a smoke test on the real dump

**Files:**
- Modify: `README.md` (the `build` command, running a recompiled game, the runtime tests)
- Modify: `docs/superpowers/specs/2026-10-17-gba-native-port-design.md` (roadmap: P4 split into P4a/P4b/P4c; toolchain)

**Interfaces:**
- Consumes: everything above. Produces: documentation only.

- [ ] **Step 1: Update the README and the spec**

In `README.md`, replace:
````markdown
The lifter tests compile C with clang (`winget install LLVM.LLVM`) and compare against
Unicorn; their test binaries are cached in the system temp folder (`gbaport-liftcache`).
````
with:
````markdown
The lifter tests compile C with clang (`winget install LLVM.LLVM`) and compare against
Unicorn; their test binaries are cached in the system temp folder (`gbaport-liftcache`).
The runtime tests build small GBA test ROMs from C (`tests/gbaroms`) with clang and
ld.lld, recompile them and run them natively; ROMs and builds are cached in
`gbaport-romcache`.
````

In `README.md`, replace:
````markdown
    uv run gbaport recompile roms/mygame.gba [--out games/XXXX/generated]
````
with:
````markdown
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
````

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
````markdown
| P4 Runtime core + desktop host | C runtime (memory map, I/O, BIOS HLE, DMA, timers, scheduler/IRQ, saves) + SDL3 desktop window | Self-built test ROMs run natively with expected results; CPU test ROMs pass when recompiled | P3 |
| P5 Renderer | Scanline renderer, all modes/features, per-line latching | Reference-image tests on graphics test ROMs | P4 |
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4 |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P5, P6 |
````
with:
````markdown
| P4a Runtime core | C runtime (memory map, I/O registers, scanline scheduler and interrupts, timers, DMA, the BIOS calls that control the CPU), `gbaport build`, headless host | Self-built test ROMs run natively with the expected results | P3 |
| P4b BIOS and saves | The other BIOS functions (arithmetic, copies, decompression, affine), SRAM/Flash/EEPROM with save files | BIOS results match reference values; save test ROMs pass and their saves persist | P4a |
| P4c Desktop host | SDL3 window, input, frame pacing, keypad wake-up | CPU test ROMs pass when recompiled; a test ROM runs in a window | P4a |
| P5 Renderer | Scanline renderer, all modes/features, per-line latching | Reference-image tests on graphics test ROMs | P4a |
| P6 Audio | PSG + FIFO mixer, resampler, SDL3 audio output | Recorded-output comparisons on sound test ROMs | P4c |
| P7 First game on desktop + lockstep harness | User's first game boots to gameplay natively; `gbaport verify` | N-frame input replay matches mGBA within tolerance | P4b, P5, P6 |
````

In `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`, replace:
````markdown
- CMake ≥ 3.28 and Ninja (`winget install Kitware.CMake Ninja-build.Ninja`) — Plans 3–4.
- SDL3 (fetched by CMake `FetchContent`) — Plan 4.
````
with:
````markdown
- CMake ≥ 3.28 and Ninja (bundled with the MSVC Build Tools; elsewhere
  `winget install Kitware.CMake Ninja-build.Ninja`) — Plan 4c. Plan 4a builds with clang
  directly.
- SDL3 (fetched by CMake `FetchContent`) — Plan 4c.
````

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest && uv run ruff check src tests`
Expected: 550 passed (534 from Plans 1-3, 16 new); ruff clean.

- [ ] **Step 3: Smoke-test on the real dump**

Run, from the repo root:

```bash
uv run python -m gbaport.cli build roms/mygame.gba --out build/bt4e
build/bt4e/build/BT4E.exe roms/mygame.gba --frames 600; echo "exit $?"
```

Expected for BT4E (validated before this plan was approved):
- **Build:** `functions    474`, `C files      6 (127050 lines)` and `lift issues  0`, then a `built ...BT4E.exe` line, in about 5 s.
- **Run:** exit 3 with `error: no recompiled code at 0x080360b0 (Thumb state, lr = 0x080359e3)`. This is the first of 26 static constructors that start-up code reaches through a table of relative offsets (0x08036778-0x080367df), which discovery cannot follow.
- **Further:** with those 26 entries and 15 more found the same way, the game boots through its own interrupt dispatcher (0x03000c10, which lets nested interrupts in). It stops at its first BIOS Div call (`BIOS function 0x06 is not implemented yet`), which is Plan 4b's.

Record the numbers in the ledger.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-17-gba-native-port-design.md
git commit -m "docs: gbaport build, running a recompiled game, P4 split into P4a-P4c"
```

---

## Done criteria for Plan 4a

- `uv run pytest` passes 550 tests and `uv run ruff check src tests` is clean.
- **Test ROMs:** built from C at test time, recompiled and run natively, they pass every check. Together they cover:
  - the memory map: mirrors, byte writes, open bus and BIOS reads;
  - I/O register rules;
  - scanline timing and VBlank/HBlank/VCount interrupts, with gating by IE, IME and the CPSR, plus nested interrupts;
  - Halt, IntrWait and VBlankIntrWait;
  - SoftReset (also from an interrupt handler) and RegisterRamReset;
  - timers (prescalers, overflows, cascades, frame length);
  - DMA (immediate, VBlank, HBlank, repeat, reload, end-of-transfer interrupt).
- **Runtime errors** end the run with an exit status and a message that says what to do. These are missing code (address and CPU state), BIOS functions not implemented yet, interrupts without a handler, and a ROM that differs from the one the build came from.
- **On your game:** `gbaport build` turns BT4E into a native program that starts and runs until the first code discovery missed.
- **Spec:** the roadmap shows P4a, P4b and P4c.
