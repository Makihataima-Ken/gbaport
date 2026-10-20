/* How many cycles kinds of code take, measured with timer 0: Thumb and ARM code in the
 * cartridge and ARM code in IWRAM, loads and stores to each memory, load and store
 * multiple, multiplies and branches, each under four WAITCNT settings. Each count is drawn
 * as two pixels of a mode 3 picture (bits 0-14, then 15-29), so a test reads mGBA's counts
 * from its picture and the runtime's from its own. */
#include "testlib.h"

#define TM0 REG_TM_CNT_L(0)
#define VRAM16 ((volatile uint16_t *)0x06000000)
#define EWRAM_WORDS ((volatile uint32_t *)0x02000000)

static uint32_t iwram_words[64] __attribute__((section(".iwram.data")));
static const uint32_t rom_words[64] = {1, 2, 3, 4, 5, 6, 7, 8};
static int slot;

static void record(uint32_t count)
{
    VRAM16[2 * slot] = count & 0x7FFF;
    VRAM16[2 * slot + 1] = (count >> 15) & 0x7FFF;
    slot++;
}

/* Thumb, in the cartridge. */
static uint32_t thumb_alu(void)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: adds r1, #1\nadds r1, #1\nadds r1, #1\nadds r1, #1\n"
                     "adds r1, #1\nadds r1, #1\nadds r1, #1\nsubs r0, #1\nbne 1b"
                     ::: "r0", "r1", "cc");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_loads(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: ldr r1, [%0]\nldr r1, [%0, #4]\nldrh r1, [%0]\n"
                     "ldrb r1, [%0, #1]\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_stores(volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: str r0, [%0]\nstrh r0, [%0, #4]\nstrb r0, [%0, #6]\n"
                     "adds r1, #1\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_multiple(volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #32\n1: adds r2, %0, #0\nstmia r2!, {r3-r6}\nadds r2, %0, #0\n"
                     "ldmia r2!, {r3-r6}\npush {r4-r7}\npop {r4-r7}\nsubs r0, #1\nbne 1b"
                     :: "l"(where) : "r0", "r2", "r3", "r4", "r5", "r6", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_multiply(uint32_t value)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: adds r1, %0, #0\nmuls r1, r1\nadds r1, %0, #0\n"
                     "muls r1, r0\nsubs r0, #1\nbne 1b"
                     :: "l"(value) : "r0", "r1", "cc");
    return (uint16_t)(TM0 - t);
}

static uint32_t thumb_branches(void)
{
    uint16_t t = TM0;
    __asm__ volatile("movs r0, #64\n1: b 2f\nnop\n2: cmp r0, #100\nbeq 3f\n3: subs r0, #1\nbne 1b"
                     ::: "r0", "cc");
    return (uint16_t)(TM0 - t);
}

/* ARM, in the cartridge and in IWRAM. */
__attribute__((target("arm"), noinline)) static uint32_t arm_rom(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("mov r0, #64\n1: add r1, r1, #1\nadd r1, r1, r1, lsl #2\nldr r1, [%0]\n"
                     "str r1, [%0, #4]\nsubs r0, r0, #1\nbne 1b"
                     :: "r"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

__attribute__((target("arm"), noinline, section(".iwram")))
static uint32_t arm_iwram(const volatile void *where)
{
    uint16_t t = TM0;
    __asm__ volatile("mov r0, #64\n1: add r1, r1, #1\nadd r1, r1, r1, lsl r0\nldr r1, [%0]\n"
                     "str r1, [%0, #4]\nmul r1, r0, r1\nsubs r0, r0, #1\nbne 1b"
                     :: "r"(where) : "r0", "r1", "cc", "memory");
    return (uint16_t)(TM0 - t);
}

/* DMA 3, while the CPU waits. The timer is read a few instructions later: mGBA starts a
 * transfer 3 cycles after it is asked for, and the CPU runs on until then. */
static uint32_t dma(const volatile void *from, volatile void *to, uint32_t control)
{
    uint16_t t = TM0;
    REG_DMA_SAD(3) = (uint32_t)from;
    REG_DMA_DAD(3) = (uint32_t)to;
    REG_DMA_CNT(3) = control;
    __asm__ volatile("nop\nnop\nnop\nnop\nnop\nnop\nnop\nnop" ::: "memory");
    return (uint16_t)(TM0 - t);
}

static const uint16_t SETTINGS[4] = {0x0000, 0x4317, 0x0317, 0x4314};

int main(void)
{
    REG_IME = 0;
    REG_DISPCNT = 0x0403;  /* mode 3, BG2 */
    REG_TM_CNT_H(0) = 0x0080;  /* timer 0 counts cycles */
    for (int i = 0; i < 4; i++) {
        REG_WAITCNT = SETTINGS[i];
        record(thumb_alu());
        record(thumb_loads(iwram_words));
        record(thumb_loads(EWRAM_WORDS));
        record(thumb_loads(rom_words));
        record(thumb_loads(VRAM16 + 0x8000));
        record(thumb_stores(iwram_words));
        record(thumb_stores(EWRAM_WORDS));
        record(thumb_stores(VRAM16 + 0x8000));
        record(thumb_multiple(EWRAM_WORDS));
        record(thumb_multiple(iwram_words));
        record(thumb_multiply(5));
        record(thumb_multiply(0x12345678));
        record(thumb_branches());
        record(arm_rom(EWRAM_WORDS));
        record(arm_iwram(EWRAM_WORDS));
        record(dma(rom_words, EWRAM_WORDS, 0x84000040));  /* 64 words */
        record(dma(EWRAM_WORDS, VRAM16 + 0x8000, 0x80000040));  /* 64 halfwords */
    }
    REG_TM_CNT_H(0) = 0;
    for (int i = 0; i < 2; i++) {  /* two whole pictures with every count */
        wait_vcount(0);
        wait_vcount(160);
    }
    test_end();
    return 0;
}
