/* Sound: a script of register writes, made by the VBlank interrupt handler frame by frame.
 * testdata.h sets WRITES ({frame, offset from 0x04000000, value} each, in frame order; frame
 * 0 is the first VBlank; offset bit 15 makes a 32-bit write, bit 14 an 8-bit one, otherwise
 * it is 16-bit) and
 * two waveforms in ROM, WAVE_A and WAVE_B (16 KiB each),
 * whose addresses start-up puts in DMA1SAD and DMA2SAD for the FIFOs' DMA. Start-up does
 * nothing else, so the first VBlank is frame 0 on any machine. */
#include "testlib.h"
#include "testdata.h"

static const uint32_t writes[][3] = WRITES;
static const uint8_t wave_a[0x4000] __attribute__((aligned(4))) = WAVE_A;
static const uint8_t wave_b[0x4000] __attribute__((aligned(4))) = WAVE_B;
static volatile uint32_t frame, next;

__attribute__((target("arm"), section(".iwram"), noinline)) static void on_interrupt(void)
{
    uint16_t flags = REG_IF;
    if (flags & IRQ_VBLANK) {
        while (next < sizeof writes / sizeof writes[0] && writes[next][0] <= frame) {
            if (writes[next][1] & 0x8000)
                REG32(0x04000000 + (writes[next][1] & 0x7FFF)) = writes[next][2];
            else if (writes[next][1] & 0x4000)
                MEM8(0x04000000 + (writes[next][1] & 0x3FFF)) = (uint8_t)writes[next][2];
            else
                REG16(0x04000000 + writes[next][1]) = (uint16_t)writes[next][2];
            next++;
        }
        frame++;
    }
    REG_IF = flags;
}

int main(void)
{
    REG_DMA_SAD(1) = (uint32_t)wave_a;
    REG_DMA_SAD(2) = (uint32_t)wave_b;
    IRQ_VECTOR = (uint32_t)on_interrupt;
    REG_DISPSTAT = 0x08;
    REG_IE = IRQ_VBLANK;
    REG_IME = 1;
    for (;;)
        bios_halt();
}
