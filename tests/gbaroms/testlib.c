#include <stdarg.h>

#include "testlib.h"

#define DEBUG_STRING ((volatile char *)0x04FFF600)
#define DEBUG_FLAGS  REG16(0x04FFF700)
#define DEBUG_ENABLE REG16(0x04FFF780)

volatile uint32_t irq_count[14];
volatile uint32_t irq_cpsr;
/* The counts sit just above the system stack (it grows down from 0x03007F00) and far
 * below the IRQ stack's top (0x03007FA0): RegisterRamReset never clears this area, and
 * SoftReset clears it before a test has counted anything. */
#define passed MEM32(0x03007F00)
#define failed MEM32(0x03007F04)

/* ---- what clang may call on its own in freestanding ARMv4T code ------------------ */

void *memcpy(void *dst, const void *src, unsigned n)
{
    uint8_t *d = dst;
    const uint8_t *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *memset(void *dst, int value, unsigned n)
{
    uint8_t *d = dst;
    while (n--) *d++ = (uint8_t)value;
    return dst;
}

typedef struct { unsigned quot, rem; } udiv_t;

static udiv_t udivmod(unsigned n, unsigned d)
{
    udiv_t r = {0, 0};
    for (int bit = 31; bit >= 0; bit--) {
        r.rem = (r.rem << 1) | ((n >> bit) & 1);
        if (r.rem >= d) { r.rem -= d; r.quot |= 1u << bit; }
    }
    return r;
}

unsigned __aeabi_uidiv(unsigned n, unsigned d) { return udivmod(n, d).quot; }

int __aeabi_idiv(int n, int d)
{
    unsigned q = udivmod(n < 0 ? -(unsigned)n : (unsigned)n, d < 0 ? -(unsigned)d : (unsigned)d).quot;
    return (n < 0) != (d < 0) ? -(int)q : (int)q;
}

/* ---- the mGBA debug log ----------------------------------------------------------- */

static void emit(const char *text)
{
    DEBUG_ENABLE = 0xC0DE;
    int i = 0;
    for (; text[i] && i < 255; i++) DEBUG_STRING[i] = text[i];
    DEBUG_STRING[i] = 0;
    DEBUG_FLAGS = 0x100 | 3;  /* print at "info" level */
}

static char *put_number(char *out, uint32_t value, unsigned base, int width)
{
    char digits[11];
    int n = 0;
    do { digits[n++] = "0123456789abcdef"[value % base]; value /= base; } while (value);
    while (n < width) digits[n++] = '0';
    while (n) *out++ = digits[--n];
    return out;
}

void print(const char *fmt, ...)
{
    char line[256], *out = line, *end = line + sizeof line - 12;
    va_list args;
    va_start(args, fmt);
    for (const char *p = fmt; *p && out < end; p++) {
        if (*p != '%') { *out++ = *p; continue; }
        int width = 0;
        while (p[1] >= '0' && p[1] <= '9') width = width * 10 + (*++p - '0');
        switch (*++p) {
        case 'd': {
            int v = va_arg(args, int);
            if (v < 0) { *out++ = '-'; v = -v; }
            out = put_number(out, (uint32_t)v, 10, width);
            break;
        }
        case 'u': out = put_number(out, va_arg(args, uint32_t), 10, width); break;
        case 'x': out = put_number(out, va_arg(args, uint32_t), 16, width); break;
        case 's':
            for (const char *s = va_arg(args, const char *); *s && out < end; s++) *out++ = *s;
            break;
        default: *out++ = *p; break;
        }
    }
    va_end(args);
    *out = 0;
    emit(line);
}

void check(const char *name, int ok)
{
    if (ok) passed++; else failed++;
    print("%s %s", ok ? "PASS" : "FAIL", name);
}

void expect(const char *name, uint32_t got, uint32_t want)
{
    if (got == want) {
        passed++;
        print("PASS %s", name);
    } else {
        failed++;
        print("FAIL %s: got 0x%08x, want 0x%08x", name, got, want);
    }
}

static uint32_t mismatch_count;

void mismatch(const char *what, uint32_t a, uint32_t b, uint32_t got, uint32_t want)
{
    if (mismatch_count++ < 3)
        print("  %s(0x%08x, 0x%08x): got 0x%08x, want 0x%08x", what, a, b, got, want);
}

uint32_t mismatches(void)
{
    uint32_t n = mismatch_count;
    mismatch_count = 0;
    return n;
}

void test_end(void)
{
    print("DONE %u passed, %u failed", passed, failed);
    __asm__ volatile("svc #3");  /* Stop: the end of a headless run */
}

/* ---- interrupts ------------------------------------------------------------------- */

/* Called by the BIOS in ARM state, in IRQ mode; it must acknowledge what it handled. */
__attribute__((target("arm"), section(".iwram"), noinline)) static void irq_handler(void)
{
    uint32_t cpsr;
    __asm__ volatile("mrs %0, cpsr" : "=r"(cpsr));
    irq_cpsr = cpsr;
    uint16_t flags = REG_IE & REG_IF;
    for (int i = 0; i < 14; i++)
        if (flags & (1u << i)) irq_count[i]++;
    REG_IF = flags;
    BIOS_IF |= flags;
}

void irq_init(void)
{
    for (int i = 0; i < 14; i++) irq_count[i] = 0;
    IRQ_VECTOR = (uint32_t)irq_handler;
    REG_IME = 1;
}

__attribute__((target("arm"), noinline)) uint32_t get_cpsr(void)
{
    uint32_t value;
    __asm__ volatile("mrs %0, cpsr" : "=r"(value));
    return value;
}

__attribute__((target("arm"), noinline)) void set_cpsr_control(uint32_t value)
{
    __asm__ volatile("msr cpsr_c, %0" ::"r"(value) : "memory");
}

void wait_vcount(uint32_t line)
{
    while (REG_VCOUNT != line) {}
}
