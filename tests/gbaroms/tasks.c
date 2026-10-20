/* Two tasks taking turns on their own stacks, as games' task systems do. switch_task keeps
 * the running task's registers and stack pointer and returns into the other task, where it
 * last called switch_task: at its start the first time. So a switch back to the first task
 * returns past the calls the second task made, and the second task goes on at places only
 * such returns reach (task_b_resumes and yield_b_resumes are labels, not ELF functions). */
#include "testlib.h"
#include "testdata.h"

#ifndef TURNS
#define TURNS 5
#endif

uint32_t a_sp, b_sp, b_count;
static uint32_t b_stack[64];

__asm__(
    "    .text\n"
    "    .thumb\n"
    "    .align 1\n"
    "    .global switch_task\n"
    "    .thumb_func\n"
    "    .type switch_task, %function\n"
    "switch_task:\n"             /* r0: where to keep this task's sp; r1: the other's sp */
    "    push {r4-r7, lr}\n"
    "    mov r2, sp\n"
    "    str r2, [r0]\n"
    "    mov sp, r1\n"
    "    pop {r4-r7, pc}\n"
    "    .global run_a_once\n"
    "    .thumb_func\n"
    "    .type run_a_once, %function\n"
    "run_a_once:\n"              /* the first task: lets the second run once */
    "    push {lr}\n"
    "    ldr r0, =a_sp\n"
    "    ldr r1, =b_sp\n"
    "    ldr r1, [r1]\n"
    "    bl switch_task\n"
    "    .global a_resumes\n"
    "a_resumes:\n"
    "    pop {r0}\n"
    "    bx r0\n"
    "    .global task_b\n"
    "    .thumb_func\n"
    "    .type task_b, %function\n"
    "task_b:\n"                  /* the second task: counts by 2, then yields, forever */
    "    ldr r0, =b_count\n"
    "    ldr r1, [r0]\n"
    "    adds r1, r1, #2\n"
    "    str r1, [r0]\n"
    "    bl yield_b\n"
    "    .global task_b_resumes\n"
    "task_b_resumes:\n"
    "    b task_b\n"
    "    .global yield_b\n"
    "    .thumb_func\n"
    "    .type yield_b, %function\n"
    "yield_b:\n"
    "    push {lr}\n"
    "    ldr r0, =b_sp\n"
    "    ldr r1, =a_sp\n"
    "    ldr r1, [r1]\n"
    "    bl switch_task\n"
    "    .global yield_b_resumes\n"
    "yield_b_resumes:\n"
    "    pop {pc}\n"
    "    .pool\n");

void run_a_once(void);
void task_b(void);

int main(void)
{
    irq_init();  /* VBlank interrupts come in while the tasks take turns */
    REG_DISPSTAT = 0x0008;
    REG_IE = IRQ_VBLANK;
    uint32_t *top = b_stack + 64 - 5;  /* as switch_task leaves a stack: r4-r7, then pc */
    top[4] = (uint32_t)task_b;
    b_sp = (uint32_t)top;
    for (uint32_t turn = 1; turn <= TURNS; turn++) {
        run_a_once();
        expect("the second task ran once more", b_count, 2 * turn);
    }
    if (TURNS >= 1000)  /* (the lines these print take many frames) */
        check("interrupts came in while the tasks took turns", irq_count[0] > 0);
    test_end();
    return 0;
}
