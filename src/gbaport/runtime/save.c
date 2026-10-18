/* save.c - the cartridge's save chip: SRAM or Flash (GBATEK, "GBA Cart Backup").
 *
 * - SRAM: 32 KiB on an 8-bit bus at 0x0E000000 (mirrored up to 0x0FFFFFFF).
 * - Flash: 64 or 128 KiB, also on the 8-bit bus, driven by command sequences written to
 *   0x0E005555 and 0x0E002AAA: chip ID, chip and 4 KiB sector erase, byte write, and (128
 *   KiB) bank switching. It identifies as a Panasonic (64 KiB) or Sanyo (128 KiB) chip.
 *   Writes can only clear bits, as on the real chip; erasing sets them again.
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
    default: s->size = 0; break;  /* no save chip, or one not handled yet */
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
    if (s->type == GBA_SAVE_NONE)
        return 0;  /* nothing to load into, and nothing will be written back */
    if (size != s->size) {
        snprintf(rt->error, sizeof rt->error,
                 "the save file has %u bytes, but this game's save chip holds %s",
                 (unsigned)size, s->type == GBA_SAVE_SRAM ? "32768" :
                 s->type == GBA_SAVE_FLASH64K ? "65536" : "131072");
        return -1;
    }
    memcpy(s->data, data, size);
    return 0;
}
