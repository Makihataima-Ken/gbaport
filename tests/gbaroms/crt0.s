@ Start-up code for the runtime test ROMs: header, stacks, IWRAM copy, BSS, then main.
@ The header fields after the entry branch are filled in by tests/romtest.py.

    .section .crt0, "ax"
    .arm
    .global _start
_start:
    b       start
    .space  0xBC                @ header: logo (left zero), title, codes, checksum

start:
    mov     r0, #0xD2           @ IRQ mode, interrupts off
    msr     cpsr_c, r0
    ldr     sp, =0x03007FA0
    mov     r0, #0x1F           @ system mode, interrupts on
    msr     cpsr_c, r0
    ldr     sp, =0x03007F00

    ldr     r0, =__iwram_lma    @ copy the IWRAM sections (code and data) from ROM
    ldr     r1, =__iwram_start
    ldr     r2, =__iwram_end
1:  cmp     r1, r2
    ldrlo   r3, [r0], #4
    strlo   r3, [r1], #4
    blo     1b

    ldr     r1, =__bss_start    @ clear BSS
    ldr     r2, =__bss_end
    mov     r3, #0
2:  cmp     r1, r2
    strlo   r3, [r1], #4
    blo     2b

    ldr     r0, =main
    mov     lr, pc
    bx      r0
    swi     #0x030000           @ main returned: Stop
3:  b       3b
