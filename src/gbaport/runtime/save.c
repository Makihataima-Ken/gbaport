/* save.c - the cartridge's save chip: SRAM, Flash or EEPROM (GBATEK, "GBA Cart Backup").
 *
 * - SRAM: 32 KiB on an 8-bit bus at 0x0E000000 (mirrored up to 0x0FFFFFFF).
 * - Flash: 64 or 128 KiB, also on the 8-bit bus, driven by command sequences written to
 *   0x0E005555 and 0x0E002AAA: chip ID, chip and 4 KiB sector erase, byte write, and (128
 *   KiB) bank switching. It identifies as a Panasonic (64 KiB) or Sanyo (128 KiB) chip.
 *   Writes can only clear bits, as on the real chip; erasing sets them again, and both
 *   take no time. (mGBA makes a byte take 650 cycles and a sector 30000, with the last
 *   sector erased reading 0x5F meanwhile; it then fails jsmolka's Flash tests, which the
 *   real chip and this model pass.)
 * - EEPROM: 512 bytes (6-bit block addresses) or 8 KiB (14-bit) behind 0x0D000000, one bit
 *   per halfword, normally by DMA. Requests: "11" + address + "0" reads a 64-bit block,
 *   which then comes out as 4 ignored bits and 64 data bits; "10" + address + 64 bits +
 *   "0" writes one, after which the chip is busy for 115000 cycles from the last data bit
 *   (about 6.9 ms, as in mGBA; GBATEK gives about 6.6). Reads report ready (1) when it is
 *   not, and no block is coming out. The chip's size is
 *   not in the ROM: it follows from the first DMA's length (9 or 73 halfwords: 512 bytes;
 *   17 or 81: 8 KiB) or from a save file's size.
 * Blank chips read 0xFF. The host stores and loads `data` through gba_save_*. */
#include <stdio.h>
#include <string.h>

#include "gba_runtime.h"

enum { FLASH_IDLE, FLASH_GOT_AA, FLASH_GOT_55 };

void gba_save_init(GbaRuntime *rt)
{
    GbaSave *s = &rt->save;
    memset(s, 0, sizeof *s);
    memset(s->data, 0xFF, sizeof s->data);
    s->type = (GbaSaveType)gba_save_type;
    switch (s->type) {
    case GBA_SAVE_SRAM: s->size = 0x8000; break;
    case GBA_SAVE_FLASH64K: s->size = 0x10000; break;
    case GBA_SAVE_FLASH128K: s->size = 0x20000; break;
    default: s->size = 0; break;  /* EEPROM: known after the first access */
    }
}

/* ---- SRAM and Flash (0x0E000000-0x0FFFFFFF, 8-bit bus) -------------------------------- */

uint32_t gba_save_read8(GbaRuntime *rt, uint32_t addr)
{
    GbaSave *s = &rt->save;
    uint32_t offset = addr & 0xFFFF;
    switch (s->type) {
    case GBA_SAVE_SRAM:
        return s->data[offset & 0x7FFF];
    case GBA_SAVE_FLASH64K:
    case GBA_SAVE_FLASH128K:
        if (s->flash_id_mode && offset < 2) {
            static const uint8_t id[2][2] = {{0x32, 0x1B}, {0x62, 0x13}};  /* Panasonic, Sanyo */
            return id[s->type == GBA_SAVE_FLASH128K][offset];
        }
        return s->data[s->flash_bank * 0x10000 + offset];
    default:
        return 0xFF;
    }
}

static void flash_command(GbaSave *s, uint32_t offset, uint32_t value)
{
    if (s->flash_erase) {  /* AA 55 80 AA 55, then 10 at 5555 (chip) or 30 at a sector */
        s->flash_erase = 0;
        if (offset == 0x5555 && value == 0x10)
            memset(s->data, 0xFF, s->size);
        else if (value == 0x30)
            memset(s->data + s->flash_bank * 0x10000 + (offset & 0xF000), 0xFF, 0x1000);
        s->dirty = 1;
        return;
    }
    if (offset != 0x5555)
        return;
    switch (value) {
    case 0x90: s->flash_id_mode = 1; break;
    case 0xF0: s->flash_id_mode = 0; break;
    case 0x80: s->flash_erase = 1; break;
    case 0xA0: s->flash_write = 1; break;
    case 0xB0: s->flash_bank_select = s->type == GBA_SAVE_FLASH128K; break;
    default: break;
    }
}

static void flash_write8(GbaSave *s, uint32_t offset, uint32_t value)
{
    if (s->flash_write) {  /* the byte after AA 55 A0 is programmed */
        s->flash_write = 0;
        s->data[s->flash_bank * 0x10000 + offset] &= (uint8_t)value;
        s->dirty = 1;
        return;
    }
    if (s->flash_bank_select && offset == 0) {
        s->flash_bank_select = 0;
        s->flash_bank = value & 1;
        return;
    }
    switch (s->flash_step) {
    case FLASH_IDLE:
        if (offset == 0x5555 && value == 0xAA)
            s->flash_step = FLASH_GOT_AA;
        else if (value == 0xF0)
            s->flash_id_mode = 0;  /* a lone F0 ends ID mode on some chips */
        break;
    case FLASH_GOT_AA:
        s->flash_step = offset == 0x2AAA && value == 0x55 ? FLASH_GOT_55 : FLASH_IDLE;
        break;
    default:
        s->flash_step = FLASH_IDLE;
        flash_command(s, offset, value);
        break;
    }
}

void gba_save_write8(GbaRuntime *rt, uint32_t addr, uint32_t value)
{
    GbaSave *s = &rt->save;
    value &= 0xFF;
    switch (s->type) {
    case GBA_SAVE_SRAM:
        s->data[addr & 0x7FFF] = (uint8_t)value;
        s->dirty = 1;
        break;
    case GBA_SAVE_FLASH64K:
    case GBA_SAVE_FLASH128K:
        flash_write8(s, addr & 0xFFFF, value);
        break;
    default:
        break;
    }
}

/* ---- EEPROM ------------------------------------------------------------------------- */

int gba_save_is_eeprom(const GbaRuntime *rt, uint32_t addr)
{
    if (rt->save.type != GBA_SAVE_EEPROM || (addr >> 24) != 0x0D)
        return 0;
    return rt->rom_size <= 0x01000000u || addr >= 0x0DFFFF00u;  /* 32 MiB ROMs: the top only */
}

static void eeprom_set_bits(GbaSave *s, int bits)
{
    s->eeprom_address_bits = bits;
    s->size = bits == 6 ? 0x200 : 0x2000;
}

void gba_eeprom_dma(GbaRuntime *rt, uint32_t count)
{
    GbaSave *s = &rt->save;
    if (s->eeprom_address_bits)
        return;
    if (count == 9 || count == 73)
        eeprom_set_bits(s, 6);
    else if (count == 17 || count == 81)
        eeprom_set_bits(s, 14);
}

static uint32_t eeprom_bits(const GbaSave *s, uint32_t first, uint32_t count)
{
    uint32_t value = 0;
    for (uint32_t i = first; i < first + count; i++)
        value = value << 1 | s->eeprom_in[i];
    return value;
}

void gba_eeprom_write(GbaRuntime *rt, uint32_t value)
{
    GbaSave *s = &rt->save;
    if (!s->eeprom_address_bits)
        eeprom_set_bits(s, 6);  /* no DMA to tell: the small chip */
    uint32_t bits = (uint32_t)s->eeprom_address_bits;
    s->eeprom_in[s->eeprom_count++] = value & 1;
    if (s->eeprom_count < 2)
        return;
    uint32_t command = eeprom_bits(s, 0, 2);
    uint32_t block = 0;
    if (s->eeprom_count >= 2 + bits)
        block = eeprom_bits(s, 2, bits) & ((s->size / 8) - 1);
    if (command == 2 && s->eeprom_count == 2 + bits + 64)  /* the last data bit */
        s->eeprom_ready = rt->cpu.cycles + 115000;
    if (command == 3 && s->eeprom_count == 2 + bits + 1) {  /* read request */
        s->eeprom_out = 0;
        for (int i = 0; i < 8; i++)
            s->eeprom_out = s->eeprom_out << 8 | s->data[block * 8 + i];
        s->eeprom_out_left = 68;
        s->eeprom_count = 0;
    } else if (command == 2 && s->eeprom_count == 2 + bits + 64 + 1) {  /* write request */
        for (int i = 0; i < 8; i++)
            s->data[block * 8 + i] = (uint8_t)eeprom_bits(s, 2 + bits + 8 * i, 8);
        s->dirty = 1;
        s->eeprom_count = 0;
    } else if (command < 2 || s->eeprom_count >= sizeof s->eeprom_in) {
        s->eeprom_count = 0;  /* not a request: start over */
    }
}

uint32_t gba_eeprom_read(GbaRuntime *rt)
{
    GbaSave *s = &rt->save;
    if (!s->eeprom_out_left)
        return rt->cpu.cycles >= s->eeprom_ready;  /* 1: ready */
    s->eeprom_out_left--;
    if (s->eeprom_out_left >= 64)
        return 0;  /* the 4 bits before the data */
    return (uint32_t)(s->eeprom_out >> s->eeprom_out_left) & 1;
}

/* ---- for the host ------------------------------------------------------------------- */

uint8_t *gba_save_data(GbaRuntime *rt, uint32_t *size)
{
    *size = rt->save.size;
    return rt->save.data;
}

int gba_save_dirty(const GbaRuntime *rt) { return rt->save.dirty; }

void gba_save_stored(GbaRuntime *rt) { rt->save.dirty = 0; }

int gba_save_load(GbaRuntime *rt, const uint8_t *data, uint32_t size)
{
    GbaSave *s = &rt->save;
    if (s->type == GBA_SAVE_EEPROM && (size == 0x200 || size == 0x2000))
        eeprom_set_bits(s, size == 0x200 ? 6 : 14);
    if (s->type == GBA_SAVE_NONE)
        return 0;  /* nothing to load into, and nothing will be written back */
    if (size != s->size) {
        snprintf(rt->error, sizeof rt->error,
                 "the save file has %u bytes, but this game's save chip holds %s",
                 (unsigned)size, s->type == GBA_SAVE_EEPROM ? "512 or 8192" :
                 s->type == GBA_SAVE_SRAM ? "32768" :
                 s->type == GBA_SAVE_FLASH64K ? "65536" : "131072");
        return -1;
    }
    memcpy(s->data, data, size);
    return 0;
}
