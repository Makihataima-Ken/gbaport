/* A general scene for the renderer tests. VRAM holds varied background tiles with gaps
 * (0x0000-0x7FFF), maps of varied entries (0x8000-0xFFFF: low tile numbers, flips, palette
 * banks) and varied sprite tiles (0x10000-0x17FFF); both palettes hold varied colours.
 * testdata.h gives the sprites (OBJS: {attr0, attr1, attr2} each, the rest disabled), their
 * matrices (MATRICES: {PA, PB, PC, PD} each) and the register writes to make, in order
 * (IO_WRITES: {offset from 0x04000000, halfword} each). */
#include "testlib.h"
#include "testdata.h"

#define PALETTE ((volatile uint16_t *)0x05000000)
#define VRAM ((volatile uint16_t *)0x06000000)
#define OAM ((volatile uint16_t *)0x07000000)

static uint32_t mix(uint32_t value)
{
    value ^= value >> 15;
    value *= 0x2C1B3C6Du;
    value ^= value >> 12;
    return value;
}

static const uint16_t objs[][3] = OBJS;
static const int16_t matrices[][4] = MATRICES;
static const uint16_t io_writes[][2] = IO_WRITES;

int main(void)
{
    for (uint32_t i = 0; i < 512; i++)
        PALETTE[i] = (uint16_t)(mix(i + 11) & 0x7FFF);
    for (uint32_t i = 0; i < 0xC000; i++) {
        uint32_t bits = mix(i + 1);
        if (i >= 0x4000 && i < 0x8000) {
            bits &= 0xFC7F;  /* map entries: tiles below 128 */
        } else if ((i & 0xF) < 4) {
            bits &= 0x0F0F;  /* the first rows of every tile are partly clear */
        }
        VRAM[i] = (uint16_t)bits;
    }
    for (int i = 0; i < 128; i++) {
        OAM[i * 4] = 0x0200;  /* disabled */
        OAM[i * 4 + 1] = 0;
        OAM[i * 4 + 2] = 0;
    }
    for (unsigned i = 0; i < sizeof objs / sizeof objs[0]; i++) {
        OAM[i * 4] = objs[i][0];
        OAM[i * 4 + 1] = objs[i][1];
        OAM[i * 4 + 2] = objs[i][2];
    }
    for (unsigned i = 0; i < sizeof matrices / sizeof matrices[0]; i++) {
        for (int k = 0; k < 4; k++)
            OAM[(i * 4 + k) * 4 + 3] = (uint16_t)matrices[i][k];
    }
    for (unsigned i = 0; i < sizeof io_writes / sizeof io_writes[0]; i++)
        REG16(0x04000000 + io_writes[i][0]) = io_writes[i][1];
    irq_init();
    REG_DISPSTAT = (uint16_t)(REG_DISPSTAT | 0x08);
    REG_IE = IRQ_VBLANK;
    for (;;)
        bios_vblank_wait();
}
