/* touch.h - the GBA's buttons drawn on a touch screen, and the keys the fingers on them
 * hold. Only geometry and bookkeeping: host_sdl.c draws the buttons and passes the
 * fingers on. Sizes are in pixels; the layout is made for a screen held sideways. */
#ifndef TOUCH_H
#define TOUCH_H

#include <stdint.h>

typedef struct {
    float x, y, w, h;
} TouchBox;

/* The buttons besides the D-pad. */
enum { TOUCH_A, TOUCH_B, TOUCH_SELECT, TOUCH_START, TOUCH_R, TOUCH_L, TOUCH_BUTTONS };

typedef struct {
    TouchBox screen;                  /* where the GBA picture goes */
    float pad_x, pad_y, pad_radius;   /* the D-pad, a circle */
    TouchBox buttons[TOUCH_BUTTONS];  /* A and B are drawn as the circles inside theirs */
} TouchLayout;

enum { TOUCH_FINGERS = 10 };

typedef struct {
    uint64_t id;
    float x, y;
    int on_pad;  /* it came down on the D-pad: it steers the D-pad wherever it moves */
} TouchFinger;

typedef struct {
    TouchLayout layout;
    TouchFinger fingers[TOUCH_FINGERS];
    int count;
} TouchState;

/* Lays the picture and the buttons out on a `width` x `height` screen whose `safe` part
 * is clear of notches and system bars. */
void touch_layout(TouchLayout *layout, float width, float height, TouchBox safe);
void touch_down(TouchState *touch, uint64_t id, float x, float y);
void touch_move(TouchState *touch, uint64_t id, float x, float y);
void touch_up(TouchState *touch, uint64_t id);
/* The GBA keys the fingers hold (GBA key bits, 1 = pressed). */
uint16_t touch_keys(const TouchState *touch);

#endif
