/* The keypad. Run with --press 5:A --press 10:A+B --press 15:none --press 20:A
 * --press 25:A+B (the test script holds those keys from those frames on). KEYINPUT reads
 * them (0 = pressed). KEYCNT requests the keypad interrupt as mGBA does: with "any of"
 * (OR), at every frame start while a chosen key is held; with "all of" (AND), once each
 * time the keys change to a match; never without its interrupt bit. */
#include "testlib.h"

#define KEYCNT_IRQ 0x4000
#define KEYCNT_AND 0x8000

static void until_frame(uint32_t *frame, uint32_t target)
{
    while (*frame < target) {
        bios_vblank_wait();
        ++*frame;
    }
}

int main(void)
{
    uint32_t frame = 0;
    irq_init();
    REG_DISPSTAT = 0x08;  /* VBlank interrupt */
    REG_IE = IRQ_VBLANK | IRQ_KEYPAD;
    REG_KEYCNT = KEYCNT_IRQ | KEY_B;  /* any of: B */

    until_frame(&frame, 7);
    expect("keyinput reads a held", REG_KEYINPUT, 0x3FF & ~KEY_A);
    expect("a key keycnt does not choose requests nothing", irq_count[12], 0);

    until_frame(&frame, 13);
    expect("keyinput reads a and b held", REG_KEYINPUT, 0x3FF & ~(KEY_A | KEY_B));
    check("holding b requests it at every frame", irq_count[12] >= 3);

    REG_KEYCNT = KEYCNT_IRQ | KEYCNT_AND | KEY_A | KEY_B;  /* all of: A, B (held now) */
    irq_count[12] = 0;
    until_frame(&frame, 14);
    expect("a keycnt matching the held keys requests it once", irq_count[12], 1);

    until_frame(&frame, 23);
    expect("keyinput reads a alone held", REG_KEYINPUT, 0x3FF & ~KEY_A);
    expect("half of an and condition requests nothing", irq_count[12], 1);

    until_frame(&frame, 28);
    expect("pressing both again requests it once more", irq_count[12], 2);

    REG_KEYCNT = KEY_A | KEY_B;  /* the interrupt bit off */
    until_frame(&frame, 30);
    expect("without the interrupt bit nothing is requested", irq_count[12], 2);
    test_end();
    return 0;
}
