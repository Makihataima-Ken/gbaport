/* EEPROM through DMA 3, the way Nintendo's library drives it: read and write requests of
 * 64-bit blocks, the ready bit, and a signature that must survive into the next run.
 * testdata.h defines EEPROM_BITS: 6 for the 512-byte chip, 14 for the 8 KiB one. */
#include "testlib.h"
#include "testdata.h"

__attribute__((used)) static const char save_id[] = "EEPROM_V124";
static const uint8_t signature[8] = {'G', 'B', 'A', 'P', 'O', 'R', 'T', 0};

#define EEPROM 0x0D000000u

static uint16_t bits[96];

static void dma3(uint32_t src, uint32_t dst, uint32_t count)
{
    /* The compiler may move plain stores to `bits` past volatile register writes; the
     * barriers keep the buffer and the transfer in order. */
    __asm__ volatile("" ::: "memory");
    REG_DMA_SAD(3) = src;
    REG_DMA_DAD(3) = dst;
    REG_DMA_CNT(3) = count | 0x80000000u;  /* 16-bit units, immediately */
    __asm__ volatile("" ::: "memory");
}

static unsigned request(unsigned n, uint32_t kind, uint32_t block)
{
    bits[n++] = 1;
    bits[n++] = (uint16_t)kind;  /* 1: read, 0: write */
    for (int b = EEPROM_BITS - 1; b >= 0; b--)
        bits[n++] = (block >> b) & 1;
    return n;
}

static void read_block(uint32_t block, uint8_t out[8])
{
    unsigned n = request(0, 1, block);
    bits[n++] = 0;
    dma3((uint32_t)bits, EEPROM, n);
    dma3(EEPROM, (uint32_t)bits, 68);
    for (int i = 0; i < 8; i++) {
        uint8_t value = 0;
        for (int b = 0; b < 8; b++)
            value = (uint8_t)(value << 1 | (bits[4 + 8 * i + b] & 1));
        out[i] = value;
    }
}

static int write_block(uint32_t block, const uint8_t data[8])
{
    unsigned n = request(0, 0, block);
    for (int i = 0; i < 8; i++)
        for (int b = 7; b >= 0; b--)
            bits[n++] = (data[i] >> b) & 1;
    bits[n++] = 0;
    dma3((uint32_t)bits, EEPROM, n);
    for (int tries = 0; tries < 10000; tries++)
        if (MEM16(EEPROM) & 1)
            return 1;  /* ready */
    return 0;
}

static int same(const uint8_t *a, const uint8_t *b)
{
    for (int i = 0; i < 8; i++)
        if (a[i] != b[i])
            return 0;
    return 1;
}

int main(void)
{
    uint8_t block[8], blank[8] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
    read_block(5, block);
    if (same(block, blank)) {
        check("writing the signature", write_block(5, signature));
        print("WROTE save");
    } else {
        check("the save survived", same(block, signature));
    }

    static const uint8_t first[8] = {1, 2, 3, 4, 5, 6, 7, 8}, second[8] = {0x80, 0, 0, 0, 0, 0, 0, 0x01};
    check("a write ends with the ready bit", write_block(2, first));
    read_block(2, block);
    check("a block reads back", same(block, first));
    write_block(2, second);
    read_block(2, block);
    check("a block is overwritten", same(block, second));
    read_block(7, block);
    check("a blank block reads 0xFF", same(block, blank));
    read_block(5, block);
    check("other blocks are untouched", same(block, signature));
    test_end();
    return 0;
}
