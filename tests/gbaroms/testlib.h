/* testlib.h - registers, logging and checks for the runtime test ROMs.
 *
 * Results go to mGBA's debug log (0x04FFF600), which the native runtime prints and mGBA
 * shows too, so a test ROM can run on both. A test ends with test_end(): it prints the
 * summary line and executes the BIOS Stop call, which ends a headless run. */
#ifndef TESTLIB_H
#define TESTLIB_H

#include <stdint.h>

#define REG16(addr) (*(volatile uint16_t *)(addr))
#define REG32(addr) (*(volatile uint32_t *)(addr))
#define MEM8(addr) (*(volatile uint8_t *)(addr))
#define MEM16(addr) (*(volatile uint16_t *)(addr))
#define MEM32(addr) (*(volatile uint32_t *)(addr))

#define REG_DISPCNT  REG16(0x04000000)
#define REG_DISPSTAT REG16(0x04000004)
#define REG_VCOUNT   REG16(0x04000006)
#define REG_DMA_SAD(n) REG32(0x040000B0 + 12 * (n))
#define REG_DMA_DAD(n) REG32(0x040000B4 + 12 * (n))
#define REG_DMA_CNT(n) REG32(0x040000B8 + 12 * (n))
#define REG_DMA_CNT_H(n) REG16(0x040000BA + 12 * (n))
#define REG_TM_CNT_L(n) REG16(0x04000100 + 4 * (n))
#define REG_TM_CNT_H(n) REG16(0x04000102 + 4 * (n))
#define REG_KEYINPUT REG16(0x04000130)
#define REG_KEYCNT   REG16(0x04000132)
#define REG_IE       REG16(0x04000200)
#define REG_IF       REG16(0x04000202)
#define REG_WAITCNT  REG16(0x04000204)
#define REG_IME      REG16(0x04000208)
#define BIOS_IF      MEM16(0x03007FF8)
#define IRQ_VECTOR   MEM32(0x03007FFC)

enum {
    IRQ_VBLANK = 1, IRQ_HBLANK = 2, IRQ_VCOUNT = 4, IRQ_TIMER0 = 8,
    IRQ_DMA0 = 0x100, IRQ_KEYPAD = 0x1000,
};

enum {  /* KEYINPUT and KEYCNT bits */
    KEY_A = 1, KEY_B = 2, KEY_SELECT = 4, KEY_START = 8, KEY_RIGHT = 0x10, KEY_LEFT = 0x20,
    KEY_UP = 0x40, KEY_DOWN = 0x80, KEY_R = 0x100, KEY_L = 0x200,
};

/* Counted by the IRQ handler that irq_init() installs; irq_cpsr is the CPSR it ran with. */
extern volatile uint32_t irq_count[14];
extern volatile uint32_t irq_cpsr;

void print(const char *fmt, ...);      /* %d %u %x %08x %s */
void check(const char *name, int ok);  /* PASS/FAIL line */
void expect(const char *name, uint32_t got, uint32_t want);
void test_end(void);                   /* summary line, then Stop */
void irq_init(void);                   /* install the counting handler, IME = 1 */
uint32_t get_cpsr(void);               /* ARM code: MRS and MSR do not exist in Thumb */
void set_cpsr_control(uint32_t value);  /* MSR cpsr_c */
void wait_vcount(uint32_t line);       /* busy-wait until VCOUNT == line */

/* Any BIOS call: r0-r3 in from in[0..3], out to out[0..3]. */
#define BIOS_CALL(number, in, out) do { \
        register uint32_t r0_ __asm__("r0") = (in)[0]; \
        register uint32_t r1_ __asm__("r1") = (in)[1]; \
        register uint32_t r2_ __asm__("r2") = (in)[2]; \
        register uint32_t r3_ __asm__("r3") = (in)[3]; \
        __asm__ volatile("svc #" #number : "+r"(r0_), "+r"(r1_), "+r"(r2_), "+r"(r3_) :: "memory"); \
        (out)[0] = r0_, (out)[1] = r1_, (out)[2] = r2_, (out)[3] = r3_; \
    } while (0)

/* Counts a mismatch and prints the first few (for tests that run many cases). */
void mismatch(const char *what, uint32_t a, uint32_t b, uint32_t got, uint32_t want);
uint32_t mismatches(void);  /* how many since the last call, then starts again */

static inline void bios_halt(void) { __asm__ volatile("svc #2" ::: "r0", "r1", "r2", "r3", "memory"); }
static inline void bios_vblank_wait(void)
{
    __asm__ volatile("svc #5" ::: "r0", "r1", "r2", "r3", "memory");
}
static inline void bios_intr_wait(uint32_t discard, uint32_t flags)
{
    register uint32_t r0 __asm__("r0") = discard;
    register uint32_t r1 __asm__("r1") = flags;
    __asm__ volatile("svc #4" : "+r"(r0), "+r"(r1) :: "r2", "r3", "memory");
}

#endif
