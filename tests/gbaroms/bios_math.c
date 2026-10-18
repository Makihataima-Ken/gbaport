/* The BIOS's arithmetic against biosref: Div, DivArm, Sqrt, ArcTan, ArcTan2, MidiKey2Freq,
 * plus GetBiosChecksum, SoundBias and MultiBoot. testdata.h holds the cases. */
#include "testlib.h"
#include "testdata.h"

int main(void)
{
    uint32_t in[4] = {0}, out[4];

    for (unsigned i = 0; i < DIV_COUNT; i++) {
        const uint32_t *c = div_cases[i];
        in[0] = c[0], in[1] = c[1];
        BIOS_CALL(0x06, in, out);
        if (out[0] != c[2] || out[1] != c[3] || out[3] != c[4])
            mismatch("Div", c[0], c[1], out[0], c[2]);
        in[0] = c[1], in[1] = c[0];
        BIOS_CALL(0x07, in, out);
        if (out[0] != c[2] || out[1] != c[3] || out[3] != c[4])
            mismatch("DivArm", c[1], c[0], out[0], c[2]);
    }
    check("Div and DivArm", mismatches() == 0);

    for (unsigned i = 0; i < SQRT_COUNT; i++) {
        in[0] = sqrt_cases[i][0];
        BIOS_CALL(0x08, in, out);
        if (out[0] != sqrt_cases[i][1])
            mismatch("Sqrt", in[0], 0, out[0], sqrt_cases[i][1]);
    }
    check("Sqrt", mismatches() == 0);

    for (unsigned i = 0; i < ARCTAN_COUNT; i++) {
        const uint32_t *c = arctan_cases[i];
        in[0] = c[0];
        BIOS_CALL(0x09, in, out);
        if (out[0] != c[1] || out[1] != c[2] || out[3] != c[3])
            mismatch("ArcTan", c[0], 0, out[0], c[1]);
    }
    check("ArcTan", mismatches() == 0);

    for (unsigned i = 0; i < ARCTAN2_COUNT; i++) {
        const uint32_t *c = arctan2_cases[i];
        in[0] = c[0], in[1] = c[1];
        BIOS_CALL(0x0A, in, out);
        if (out[0] != c[2])
            mismatch("ArcTan2", c[0], c[1], out[0], c[2]);
    }
    check("ArcTan2", mismatches() == 0);

    static uint32_t wave[2];
    for (unsigned i = 0; i < MIDI_COUNT; i++) {
        const uint32_t *c = midi_cases[i];
        wave[1] = c[0];
        in[0] = (uint32_t)wave, in[1] = c[1], in[2] = c[2];
        BIOS_CALL(0x1F, in, out);
        if (out[0] + 1 < c[3] || out[0] > c[3] + 1)  /* pow() may round the last bit either way */
            mismatch("MidiKey2Freq", c[0], c[1], out[0], c[3]);
    }
    check("MidiKey2Freq", mismatches() == 0);

    BIOS_CALL(0x0D, in, out);
    expect("GetBiosChecksum", out[0], 0xBAAE187F);
    in[0] = 1;
    BIOS_CALL(0x19, in, out);
    expect("SoundBias up", REG16(0x04000088) & 0x3FF, 0x200);
    in[0] = 0;
    BIOS_CALL(0x19, in, out);
    expect("SoundBias down", REG16(0x04000088) & 0x3FF, 0);
    BIOS_CALL(0x25, in, out);
    expect("MultiBoot fails without a cable", out[0], 1);

    irq_init();
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    wait_vcount(10);
    uint32_t before = irq_count[0];
    in[2] = 0;  /* CustomHalt with 0: Halt */
    BIOS_CALL(0x27, in, out);
    uint32_t line = REG_VCOUNT;
    expect("CustomHalt halts until an interrupt", irq_count[0], before + 1);
    expect("CustomHalt returns in line 160", line, 160);

    test_end();
    return 0;
}
