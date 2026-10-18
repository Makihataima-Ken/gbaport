/* Flash: the chip ID, sector and chip erase, byte writes (which only clear bits), bank
 * switching on 128 KiB chips, and a signature that must survive into the next run.
 * testdata.h defines FLASH_ID (the library ID string), FLASH_CHIP and FLASH_BANKS. */
#include "testlib.h"
#include "testdata.h"

__attribute__((used)) static const char save_id[] = FLASH_ID;
static const char signature[8] = "GBAPORT";

#define FLASH ((volatile uint8_t *)0x0E000000)

static void command(uint8_t value)
{
    FLASH[0x5555] = 0xAA;
    FLASH[0x2AAA] = 0x55;
    FLASH[0x5555] = value;
}

static void write_byte(uint32_t offset, uint8_t value)
{
    command(0xA0);
    FLASH[offset] = value;
}

static void erase_sector(uint32_t offset)
{
    command(0x80);
    FLASH[0x5555] = 0xAA;
    FLASH[0x2AAA] = 0x55;
    FLASH[offset] = 0x30;
}

static void erase_chip(void)
{
    command(0x80);
    command(0x10);
}

static void select_bank(uint8_t bank)
{
    command(0xB0);
    FLASH[0] = bank;
}

static void write_signature(void)
{
    for (int i = 0; i < 8; i++)
        write_byte(0x100 + i, (uint8_t)signature[i]);
}

static int range_is(uint32_t from, uint32_t to, uint8_t value)
{
    for (uint32_t i = from; i < to; i++)
        if (FLASH[i] != value)
            return 0;
    return 1;
}

int main(void)
{
    command(0x90);
    uint32_t id = FLASH[0] | FLASH[1] << 8;
    command(0xF0);
    expect("flash chip id", id, FLASH_CHIP);
    check("ID mode ends", FLASH[0] != (FLASH_CHIP & 0xFF) || FLASH[1] != (FLASH_CHIP >> 8));

    if (FLASH[0x100] == 0xFF) {
        write_signature();
        print("WROTE save");
    } else {
        int same = 1;
        for (int i = 0; i < 8; i++)
            same &= FLASH[0x100 + i] == (uint8_t)signature[i];
        check("the save survived", same);
    }

    erase_sector(0x3000);
    check("a sector erase leaves 0xFF", range_is(0x3000, 0x4000, 0xFF));
    write_byte(0x3010, 0x5A);
    expect("a byte write", FLASH[0x3010], 0x5A);
    write_byte(0x3010, 0xF0);
    expect("a byte write only clears bits", FLASH[0x3010], 0x50);
    erase_sector(0x3000);
    expect("erasing again", FLASH[0x3010], 0xFF);
    expect("another sector is untouched", FLASH[0x100], (uint8_t)signature[0]);

    if (FLASH_BANKS == 2) {
        select_bank(1);
        erase_sector(0x3000);
        write_byte(0x3010, 0x77);
        expect("bank 1 keeps its byte", FLASH[0x3010], 0x77);
        select_bank(0);
        expect("bank 0 is separate", FLASH[0x3010], 0xFF);
    }

    erase_chip();
    check("a chip erase leaves 0xFF", range_is(0, 0x200, 0xFF) && range_is(0xFE00, 0x10000, 0xFF));
    write_signature();
    test_end();
    return 0;
}
