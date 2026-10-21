/* touchhost.c - runs runtime/touch.c for tests/runtime/test_touch.py. Reads commands,
 * one a line, and prints what they ask for:
 *
 *     layout W H SX SY SW SH   lay out a W x H screen whose safe area is SX SY SW SH;
 *                              prints the picture's box, the D-pad and each button's box
 *     down ID X Y | move ID X Y | up ID
 *     keys                     prints the keys held, "A+RIGHT" or "none"
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdio.h>
#include <string.h>

#include "touch.h"

static const char *const KEY_NAMES[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L",
};
static const char *const BUTTON_NAMES[TOUCH_BUTTONS] = {"A", "B", "SELECT", "START", "R", "L"};

int main(void)
{
    static TouchState touch;
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        char command[16];
        unsigned long long id;
        float a, b, c, d, e, f;
        if (sscanf(line, "%15s", command) != 1)
            continue;
        if (strcmp(command, "layout") == 0 &&
            sscanf(line, "%*s %f %f %f %f %f %f", &a, &b, &c, &d, &e, &f) == 6) {
            touch_layout(&touch.layout, a, b, (TouchBox){c, d, e, f});
            const TouchLayout *l = &touch.layout;
            printf("screen %.1f %.1f %.1f %.1f\n", l->screen.x, l->screen.y, l->screen.w, l->screen.h);
            printf("pad %.1f %.1f %.1f\n", l->pad_x, l->pad_y, l->pad_radius);
            for (int i = 0; i < TOUCH_BUTTONS; i++)
                printf("%s %.1f %.1f %.1f %.1f\n", BUTTON_NAMES[i], l->buttons[i].x,
                       l->buttons[i].y, l->buttons[i].w, l->buttons[i].h);
        } else if (strcmp(command, "down") == 0 && sscanf(line, "%*s %llu %f %f", &id, &a, &b) == 3) {
            touch_down(&touch, id, a, b);
        } else if (strcmp(command, "move") == 0 && sscanf(line, "%*s %llu %f %f", &id, &a, &b) == 3) {
            touch_move(&touch, id, a, b);
        } else if (strcmp(command, "up") == 0 && sscanf(line, "%*s %llu", &id) == 1) {
            touch_up(&touch, id);
        } else if (strcmp(command, "keys") == 0) {
            unsigned keys = touch_keys(&touch);
            int first = 1;
            for (int k = 0; k < 10; k++)
                if (keys >> k & 1) {
                    printf("%s%s", first ? "" : "+", KEY_NAMES[k]);
                    first = 0;
                }
            printf("%s\n", first ? "none" : "");
        } else {
            printf("bad command: %s", line);
            return 1;
        }
    }
    return 0;
}
