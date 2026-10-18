from liftkit import Case, differences, run_compiled, run_oracle

# A hand-written stand-in for a lifted program: r0 = 5, then the stop call.
STOP_AFTER_SETTING_R0 = """#include "lifthost.h"
static uint32_t entry(GbaCtx *ctx) { ctx->r[0] = 5; gba_swi(ctx, 0xFF); return 0; }
static GbaFn lookup(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }
const HarnessCase HARNESS_CASES[] = {{entry, lookup}};
const unsigned HARNESS_CASE_COUNT = 1;
"""

RETURN_AND_FAULT = """#include "lifthost.h"
static uint32_t back(GbaCtx *ctx) { return ctx->r[14]; }
static uint32_t wild(GbaCtx *ctx) { return gba_read32(ctx, 0x09000000u); }
static GbaFn lookup(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }
const HarnessCase HARNESS_CASES[] = {{back, lookup}, {wild, lookup}};
const unsigned HARNESS_CASE_COUNT = 2;
"""


EXCEPTION_RETURN = """#include "lifthost.h"
static uint32_t entry(GbaCtx *ctx)
{
    ctx->r[13] = 0x03000100u;               /* the system-mode stack */
    gba_set_cpsr(ctx, 0xD2u, 1u);           /* to IRQ mode, interrupts off */
    ctx->r[13] = 0x03000200u;               /* the IRQ stack */
    gba_set_spsr(ctx, 0x6000001Fu, 9u);     /* return to system mode with Z and C set */
    gba_restore_cpsr(ctx);                  /* what movs pc, lr does to the CPSR */
    ctx->r[0] = ctx->r[13];
    gba_swi(ctx, 0xFF);
    return 0;
}
static GbaFn lookup(GbaCtx *ctx, uint32_t addr) { return gba_missing(ctx, addr); }
const HarnessCase HARNESS_CASES[] = {{entry, lookup}};
const unsigned HARNESS_CASE_COUNT = 1;
"""


def test_exception_return_restores_mode_banks_and_flags():
    out = run_compiled(EXCEPTION_RETURN, [Case("nop")])[0]
    assert out.status == "stopped"
    assert out.regs[0] == out.regs[13] == 0x03000100
    assert out.cpsr & 0xF00000FF == 0x6000001F


def test_host_and_oracle_agree_on_a_hand_written_program():
    case = Case("mov r0, #5")
    host, oracle = run_compiled(STOP_AFTER_SETTING_R0, [case])[0], run_oracle([case])[0]
    assert host.status == oracle.status == "stopped"
    assert host.regs[0] == oracle.regs[0] == 5
    assert differences(host, oracle) == []


def test_host_reports_returns_and_faults():
    returned, faulted = run_compiled(RETURN_AND_FAULT, [Case("nop"), Case("nop")])
    assert (returned.status, faulted.status) == ("returned", "fault")


def test_oracle_stops_runaway_loops():
    assert run_oracle([Case("loop:\n    b loop")])[0].status == "runaway"


def test_differences_names_what_differs():
    case = Case("mov r0, #5")
    a = run_oracle([case])[0]
    b = run_oracle([Case("mov r0, #6")])[0]
    assert differences(a, b) == ["r0 0x00000005 != 0x00000006"]
