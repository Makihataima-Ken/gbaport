/* Scanline timing and interrupts: VBlank, HBlank and VCount requests, IE/IME/CPSR gating,
 * the BIOS-style handler call, Halt and IntrWait. */
#include "testlib.h"

volatile uint32_t nested_seen;
void nesting_handler(void);

/* An IRQ handler that lets other interrupts in while it works, as sound engines do. It
 * saves SPSR and lr_irq first (a nested interrupt replaces both), acknowledges, and for a
 * VBlank switches to system mode with interrupts on until an HBlank has been counted. */
__asm__(
    ".section .iwram, \"ax\"\n"
    ".arm\n"
    ".align 2\n"
    ".global nesting_handler\n"
    ".type nesting_handler, %function\n"
    "nesting_handler:\n"
    "    mrs r3, spsr\n"
    "    stmfd sp!, {r3, lr}\n"
    "    mov r0, #0x04000000\n"
    "    add r0, r0, #0x200\n"
    "    ldr r1, [r0]\n"               /* IE | IF << 16 */
    "    and r1, r1, r1, lsr #16\n"
    "    strh r1, [r0, #2]\n"
    "    ldr r2, =irq_count\n"
    "    tst r1, #2\n"                 /* HBlank: count it */
    "    ldrne r3, [r2, #4]\n"
    "    addne r3, r3, #1\n"
    "    strne r3, [r2, #4]\n"
    "    tst r1, #1\n"                 /* VBlank: wait for an HBlank with interrupts on */
    "    beq 2f\n"
    "    ldr r1, [r2, #4]\n"
    "    msr cpsr_c, #0x1F\n"
    "1:  ldr r3, [r2, #4]\n"
    "    cmp r3, r1\n"
    "    beq 1b\n"
    "    msr cpsr_c, #0x92\n"
    "    ldr r2, =nested_seen\n"
    "    mov r3, #1\n"
    "    str r3, [r2]\n"
    "2:  ldmfd sp!, {r3, lr}\n"
    "    msr spsr_cf, r3\n"
    "    bx lr\n"
    ".ltorg\n"
    ".size nesting_handler, . - nesting_handler\n"
    ".text\n"
    ".thumb\n");

static void spin(int n)
{
    for (volatile int i = 0; i < n; i++) {}
}

/* A loop whose registers live across many interrupts: the handler must not disturb them. */
static uint32_t busy_sum(uint32_t n)
{
    uint32_t sum = 0;
    for (uint32_t i = 1; i <= n; i++)
        sum += i ^ (sum >> 3);
    return sum;
}

int main(void)
{
    irq_init();
    REG_DISPSTAT = 0x0008;  /* request VBlank */
    REG_IE = IRQ_VBLANK;

    bios_vblank_wait();
    uint32_t line = REG_VCOUNT;
    expect("vblank wait returns in line 160", line, 160);
    expect("vblank flag set in line 160", REG_DISPSTAT & 1, 1);
    irq_count[0] = 0;
    for (int i = 0; i < 5; i++)
        bios_vblank_wait();
    expect("five vblank waits, five vblank interrupts", irq_count[0], 5);
    expect("handler ran in IRQ mode, ARM, IRQs off", irq_cpsr & 0xBF, 0x92);
    expect("back in system mode after the handler", get_cpsr() & 0x1F, 0x1F);

    wait_vcount(227);
    expect("vblank flag clear in line 227", REG_DISPSTAT & 1, 0);
    wait_vcount(100);
    expect("no vblank flag in visible lines", REG_DISPSTAT & 1, 0);

    /* HBlank: requested once per line, 228 a frame. */
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    bios_vblank_wait();
    irq_count[1] = 0;
    bios_vblank_wait();
    expect("228 hblank interrupts a frame", irq_count[1], 228);

    /* VCount match: once a frame, with the flag set while the line matches. */
    REG_DISPSTAT = 0x0008 | 0x0020 | (100 << 8);
    REG_IE = IRQ_VBLANK | IRQ_VCOUNT;
    bios_vblank_wait();
    irq_count[2] = 0;
    for (int i = 0; i < 3; i++)
        bios_vblank_wait();
    expect("one vcount interrupt a frame", irq_count[2], 3);
    wait_vcount(100);
    expect("vcounter flag while the line matches", REG_DISPSTAT & 4, 4);
    wait_vcount(101);
    expect("vcounter flag clear on the next line", REG_DISPSTAT & 4, 0);
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;

    /* IME off: the request stays pending in IF until IME is set again. */
    bios_vblank_wait();
    REG_IME = 0;
    uint32_t before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("ime off: no interrupt", irq_count[0], before);
    expect("ime off: request pending", REG_IF & IRQ_VBLANK, IRQ_VBLANK);
    REG_IME = 1;
    spin(10);
    expect("ime on: pending interrupt delivered", irq_count[0], before + 1);

    /* IE off: same. */
    REG_IE = 0;
    before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("ie off: no interrupt", irq_count[0], before);
    REG_IE = IRQ_VBLANK;
    spin(10);
    expect("ie on: pending interrupt delivered", irq_count[0], before + 1);

    /* The CPSR's I bit masks interrupts; clearing it with MSR lets them in again (taken at
     * the next scheduler event, so within a scanline). */
    set_cpsr_control(0x9F);
    before = irq_count[0];
    wait_vcount(10);
    wait_vcount(161);
    expect("cpsr I set: no interrupt", irq_count[0], before);
    set_cpsr_control(0x1F);
    wait_vcount(163);
    expect("cpsr I clear: pending interrupt delivered", irq_count[0], before + 1);

    /* Halt sleeps until the next enabled request. */
    wait_vcount(20);
    before = irq_count[0];
    bios_halt();
    line = REG_VCOUNT;  /* read before print() takes its time */
    expect("halt wakes for vblank", irq_count[0], before + 1);
    expect("halt returns in line 160", line, 160);

    /* IntrWait: with discard 0, a flag already set in BIOS_IF returns at once. */
    wait_vcount(30);
    BIOS_IF |= IRQ_VBLANK;
    bios_intr_wait(0, IRQ_VBLANK);
    line = REG_VCOUNT;
    expect("intrwait returns at once for an old flag", line, 30);
    expect("intrwait clears the flag it waited for", BIOS_IF & IRQ_VBLANK, 0);
    BIOS_IF |= IRQ_VBLANK;
    bios_intr_wait(1, IRQ_VBLANK);
    line = REG_VCOUNT;
    expect("intrwait with discard waits for a new one", line, 160);

    /* One 32-bit store to 0x04000200 sets IE and acknowledges IF together. */
    REG_IME = 0;
    wait_vcount(10);
    wait_vcount(161);
    REG32(0x04000200) = IRQ_VBLANK | (IRQ_VBLANK << 16);
    expect("32-bit store sets IE", REG_IE, IRQ_VBLANK);
    expect("32-bit store acknowledges IF", REG_IF & IRQ_VBLANK, 0);

    /* The BIOS's interrupt waits turn IME on themselves. */
    before = irq_count[0];
    bios_vblank_wait();
    expect("vblank wait turns IME on", REG_IME, 1);
    expect("vblank wait with IME off still returns", irq_count[0], before + 1);

    /* A handler that re-enables interrupts gets a nested one. */
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    IRQ_VECTOR = (uint32_t)nesting_handler;
    nested_seen = 0;
    while (!nested_seen) {}
    irq_init();
    expect("an interrupt nested in a handler", nested_seen, 1);
    expect("system mode again after the nested handlers", get_cpsr() & 0xFF, 0x1F);

    /* Registers survive interrupts: the same sum with and without them. */
    REG_IME = 0;
    uint32_t quiet = busy_sum(300000);
    REG_DISPSTAT = 0x0018;
    REG_IE = IRQ_VBLANK | IRQ_HBLANK;
    REG_IME = 1;
    irq_count[1] = 0;
    uint32_t noisy = busy_sum(300000);
    check("the loop was interrupted", irq_count[1] > 100);
    expect("registers survive interrupts", noisy, quiet);

    test_end();
    return 0;
}
