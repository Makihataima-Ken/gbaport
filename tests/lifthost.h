/* lifthost.h - the case table a batch of lifted test programs provides to lifthost.c. */
#ifndef LIFTHOST_H
#define LIFTHOST_H

#include "gba_cpu.h"

typedef struct HarnessCase {
    GbaFn entry;
    GbaFn (*lookup)(GbaCtx *ctx, uint32_t addr);
} HarnessCase;

extern const HarnessCase HARNESS_CASES[];
extern const unsigned HARNESS_CASE_COUNT;

#endif
