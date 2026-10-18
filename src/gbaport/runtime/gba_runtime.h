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

typedef enum {  /* runtime warnings, each reported once a run */
    GBA_WARN_SWI = 1 << 0,           /* a SWI number the BIOS does not have */
    GBA_WARN_DIV_ZERO = 1 << 1,
    GBA_WARN_BAD_ARGUMENT = 1 << 2,  /* a BIOS call with arguments it rejects */
    GBA_WARN_SOUND = 1 << 3,         /* the BIOS sound driver, not implemented yet */
} GbaWarning;

typedef enum {  /* the cartridge's save chip; gba_rom.c gives the game's */
    GBA_SAVE_NONE, GBA_SAVE_SRAM, GBA_SAVE_FLASH64K, GBA_SAVE_FLASH128K, GBA_SAVE_EEPROM,
} GbaSaveType;

typedef struct {
    GbaSaveType type;
    uint8_t data[0x20000];  /* the chip's contents (0xFF when blank) */
    uint32_t size;          /* bytes in use; for EEPROM 0 until its size is known */
    int dirty;              /* written since the host last stored it */
    int flash_step, flash_id_mode, flash_erase, flash_write, flash_bank_select;
    uint32_t flash_bank;
    int eeprom_address_bits;  /* 6 (512 bytes) or 14 (8 KiB) */
    uint8_t eeprom_in[96];    /* request bits received so far */
    uint32_t eeprom_count;
    uint64_t eeprom_out;      /* the block being read out */
    uint32_t eeprom_out_left; /* bits still to come: 4 ignored, then 64 */
} GbaSave;

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
    GbaSave save;

    char debug_text[0x101];
    int debug_enabled;
    unsigned warned;  /* GbaWarning bits already reported */

    jmp_buf end_jump;
    int resetting;    /* 1 = SoftReset, 2 = HardReset */
    GbaEnd end;
    char error[256];
};

/* Provided by the generated code (`gbaport recompile`). */
extern const uint32_t gba_rom_entry;  /* where the cartridge's entry branch leads */
extern const uint32_t gba_rom_size;
extern const uint32_t gba_rom_crc32;
extern const uint32_t gba_save_type;  /* a GbaSaveType */
GbaFn gba_lookup(GbaCtx *ctx, uint32_t addr);

/* For the host. */
int gba_init(GbaRuntime *rt, const uint8_t *rom, uint32_t size, const GbaHost *host);
GbaEnd gba_run(GbaRuntime *rt);
void gba_end(GbaRuntime *rt, GbaEnd why);  /* from a callback: ends gba_run */
void gba_set_keys(GbaRuntime *rt, uint16_t pressed);
uint32_t gba_crc32(const uint8_t *data, uint32_t size);
uint8_t *gba_save_data(GbaRuntime *rt, uint32_t *size);  /* size 0: nothing to store */
int gba_save_dirty(const GbaRuntime *rt);
void gba_save_stored(GbaRuntime *rt);
int gba_save_load(GbaRuntime *rt, const uint8_t *data, uint32_t size);  /* before gba_run */

/* Inside the runtime. */
static inline GbaRuntime *gba_rt(GbaCtx *ctx) { return (GbaRuntime *)ctx->runtime; }
void gba_fail(GbaRuntime *rt, const char *fmt, ...);  /* runtime error: ends the run */
void gba_reset(GbaRuntime *rt);                       /* SoftReset: restarts gba_run */
void gba_hard_reset(GbaRuntime *rt);                  /* HardReset: power on again */
void gba_warn_once(GbaRuntime *rt, GbaWarning kind, const char *fmt, ...);
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

void gba_bios_div(GbaRuntime *rt, int32_t num, int32_t den);
void gba_bios_sqrt(GbaRuntime *rt);
void gba_bios_arctan(GbaRuntime *rt);
void gba_bios_arctan2(GbaRuntime *rt);
void gba_bios_midi_key_to_freq(GbaRuntime *rt);
void gba_bios_cpu_set(GbaRuntime *rt);
void gba_bios_cpu_fast_set(GbaRuntime *rt);
void gba_bios_bit_unpack(GbaRuntime *rt);
void gba_bios_bg_affine_set(GbaRuntime *rt);
void gba_bios_obj_affine_set(GbaRuntime *rt);
void gba_bios_lz77(GbaRuntime *rt, int halfwords);
void gba_bios_rl(GbaRuntime *rt, int halfwords);
void gba_bios_diff(GbaRuntime *rt, int unit, int halfwords);
void gba_bios_huffman(GbaRuntime *rt);

void gba_save_init(GbaRuntime *rt);
uint32_t gba_save_read8(GbaRuntime *rt, uint32_t addr);   /* 0x0E000000-0x0FFFFFFF */
void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value);
int gba_save_is_eeprom(const GbaRuntime *rt, uint32_t addr);
void gba_eeprom_dma(GbaRuntime *rt, uint32_t count);      /* a DMA of count halfwords starts */
uint32_t gba_eeprom_read(GbaRuntime *rt);
void gba_eeprom_write(GbaRuntime *rt, uint32_t value);

void gba_dma_write(GbaRuntime *rt, int n, uint16_t control);
void gba_dma_trigger(GbaRuntime *rt, int timing);  /* 1 = VBlank, 2 = HBlank */

#endif
