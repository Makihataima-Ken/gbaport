/* A game that saves all the time: it prints the count its save holds ("SAVED n", 0 for a
 * blank save), then counts frames on from there, writing each new count to SRAM and
 * printing it ("COUNT n"). Never ends. The library ID string tells gbaport it has SRAM. */
#include "testlib.h"

__attribute__((used)) static const char save_id[] = "SRAM_V113";

#define SRAM ((volatile uint8_t *)0x0E000000)

static uint32_t load(void)
{
    uint32_t count = 0;
    for (int i = 0; i < 4; i++)
        count |= (uint32_t)SRAM[i] << (8 * i);
    return count == 0xFFFFFFFF ? 0 : count;
}

int main(void)
{
    uint32_t count = load();
    print("SAVED %u", count);
    for (;;) {
        wait_vcount(160);
        count++;
        for (int i = 0; i < 4; i++)
            SRAM[i] = (uint8_t)(count >> (8 * i));
        print("COUNT %u", count);
        wait_vcount(0);  /* printing can take longer than a line: wait for the next frame */
    }
}
