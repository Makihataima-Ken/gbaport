/* interp.h - running guest code that was not recompiled.
 *
 * gba_interpret is a GbaFn: gba_missing hands it the address the dispatcher found no
 * recompiled function for (ctx->interp_pc, bit 0 set for Thumb state), and it runs the
 * code there by the rules recompiled code follows (lift/function.py, lift/semantics.py):
 * the same instruction semantics, the same cycles charged at the same moments, events
 * checked at backward branches and jumps through registers, calls run as nested
 * gba_call chains. It returns the address execution continues at when control reaches
 * the current call's return address, recompiled code (ctx->find), an outer call's return
 * address, or leaves through a register jump.
 *
 * The runtime (or a test host) provides instruction fetches. */
#ifndef GBA_INTERP_H
#define GBA_INTERP_H

#include "gba_cpu.h"

uint32_t gba_interpret(GbaCtx *ctx);

uint32_t gba_fetch16(GbaCtx *ctx, uint32_t addr);
uint32_t gba_fetch32(GbaCtx *ctx, uint32_t addr);

#endif
