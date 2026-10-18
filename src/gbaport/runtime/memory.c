/* memory.c - the GBA memory map behind gba_read8/16/32 and gba_write8/16/32.
 *
 * Addresses arrive aligned to the access size (gba_cpu.h applies the ARM7TDMI rules for
 * misaligned loads and stores first). Every region mirrors across its 16 MiB page.
 * Byte writes follow the hardware: palette and BG VRAM write the byte to both halves of
 * the halfword, OBJ VRAM and OAM ignore them. Reads past the end of the ROM return the
 * cartridge bus's open-bus pattern (each halfword reads as its address / 2); other
 * unmapped reads return 0. The save chip (save.c) answers at 0x0E000000-0x0FFFFFFF on
 * an 8-bit bus (wider reads repeat the byte), and an EEPROM at 0x0D000000. */
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
static int is_save(uint32_t addr) { return addr >= 0x0E000000u && addr < 0x10000000u; }

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
    if (gba_save_is_eeprom(rt, addr))
        return gba_eeprom_read(rt);
    if (is_save(addr))
        return gba_save_read8(rt, addr) * 0x0101u;
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
    if (is_save(addr))
        return gba_save_read8(rt, addr);
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
    if (is_save(addr))
        return gba_save_read8(rt, addr) * 0x01010101u;
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
    case 0x0D:
        if (gba_save_is_eeprom(rt, addr))
            gba_eeprom_write(rt, value);
        break;
    case 0x0E:
    case 0x0F:
        gba_save_write8(rt, addr, value);  /* the 8-bit bus takes the low byte */
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
    case 0x0E:
    case 0x0F:
        gba_save_write8(rt, addr, value);
        return;
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
