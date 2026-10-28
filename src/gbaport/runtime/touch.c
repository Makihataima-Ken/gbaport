/* touch.c - see touch.h. The picture is as large as the whole screen allows, in its
 * middle. The buttons keep to the safe area and their sizes follow its height `u`: the
 * D-pad on the left, A and B on the right, L and R in the top corners, Select and Start
 * at the bottom in the middle. On a screen wider than the picture they sit beside it;
 * on a narrower one they are drawn over it. A finger between A and B holds both. */
#include "touch.h"

#include <math.h>

static const uint16_t BUTTON_KEYS[TOUCH_BUTTONS] = {
    1u << 0, 1u << 1, 1u << 2, 1u << 3, 1u << 8, 1u << 9,  /* A B SELECT START R L */
};
enum { RIGHT = 1u << 4, LEFT = 1u << 5, UP = 1u << 6, DOWN = 1u << 7 };

#define A_B_REACH 1.4f  /* a round button's box reaches this many radii from its centre */

static TouchBox around(float x, float y, float radius)
{
    float reach = radius * A_B_REACH;
    return (TouchBox){x - reach, y - reach, 2 * reach, 2 * reach};
}

void touch_layout(TouchLayout *layout, float width, float height, TouchBox safe)
{
    float u = safe.h, right = safe.x + safe.w, bottom = safe.y + safe.h;
    float scale = fminf(width / 240, height / 160);
    layout->screen = (TouchBox){(width - 240 * scale) / 2, (height - 160 * scale) / 2,
                                240 * scale, 160 * scale};
    layout->pad_radius = 0.18f * u;
    layout->pad_x = safe.x + 0.05f * u + layout->pad_radius;
    layout->pad_y = safe.y + 0.60f * u;
    float round = 0.09f * u, ax = right - 0.05f * u - round, ay = safe.y + 0.52f * u;
    layout->buttons[TOUCH_A] = around(ax, ay, round);
    layout->buttons[TOUCH_B] = around(ax - 0.22f * u, ay + 0.12f * u, round);
    float middle = safe.x + safe.w / 2;
    layout->buttons[TOUCH_SELECT] = (TouchBox){middle - 0.19f * u, bottom - 0.10f * u, 0.17f * u, 0.08f * u};
    layout->buttons[TOUCH_START] = (TouchBox){middle + 0.02f * u, bottom - 0.10f * u, 0.17f * u, 0.08f * u};
    layout->buttons[TOUCH_R] = (TouchBox){right - 0.30f * u, safe.y, 0.30f * u, 0.13f * u};
    layout->buttons[TOUCH_L] = (TouchBox){safe.x, safe.y, 0.30f * u, 0.13f * u};
}

static int inside(TouchBox box, float x, float y)
{
    return x >= box.x && x < box.x + box.w && y >= box.y && y < box.y + box.h;
}

/* A finger on the D-pad points at up to two directions: each covers 135 degrees, so the
 * diagonals between them hold both; near the centre it points at none. */
static uint16_t pad_keys(const TouchLayout *layout, float x, float y)
{
    float dx = x - layout->pad_x, dy = y - layout->pad_y, distance = hypotf(dx, dy);
    if (distance < 0.2f * layout->pad_radius)
        return 0;
    float lean = 0.38f * distance;  /* cos(67.5 degrees) */
    return (uint16_t)((dx > lean ? RIGHT : 0) | (dx < -lean ? LEFT : 0) |
                      (dy < -lean ? UP : 0) | (dy > lean ? DOWN : 0));
}

static uint16_t finger_keys(const TouchLayout *layout, const TouchFinger *finger)
{
    if (finger->on_pad)
        return pad_keys(layout, finger->x, finger->y);
    uint16_t keys = 0;
    for (int b = 0; b < TOUCH_BUTTONS; b++)
        if (inside(layout->buttons[b], finger->x, finger->y))
            keys |= BUTTON_KEYS[b];
    return keys;
}

static TouchFinger *find(TouchState *touch, uint64_t id)
{
    for (int i = 0; i < touch->count; i++)
        if (touch->fingers[i].id == id)
            return &touch->fingers[i];
    return 0;
}

void touch_down(TouchState *touch, uint64_t id, float x, float y)
{
    touch->hidden = 0;  /* touching the screen brings the drawn buttons back */
    TouchFinger *finger = find(touch, id);
    if (!finger) {
        if (touch->count == TOUCH_FINGERS)
            return;  /* more fingers than anyone needs: the extra ones hold nothing */
        finger = &touch->fingers[touch->count++];
    }
    const TouchLayout *layout = &touch->layout;
    float distance = hypotf(x - layout->pad_x, y - layout->pad_y);
    *finger = (TouchFinger){id, x, y, distance < 1.4f * layout->pad_radius};
}

void touch_move(TouchState *touch, uint64_t id, float x, float y)
{
    TouchFinger *finger = find(touch, id);
    if (finger) {
        finger->x = x;
        finger->y = y;
    }
}

void touch_up(TouchState *touch, uint64_t id)
{
    TouchFinger *finger = find(touch, id);
    if (finger)
        *finger = touch->fingers[--touch->count];
}

uint16_t touch_keys(const TouchState *touch)
{
    uint16_t keys = 0;
    for (int i = 0; i < touch->count; i++)
        keys |= finger_keys(&touch->layout, &touch->fingers[i]);
    return keys;
}

void touch_gamepad_pressed(TouchState *touch)
{
    touch->hidden = 1;
}

void touch_gamepad_removed(TouchState *touch)
{
    touch->hidden = 0;
}
