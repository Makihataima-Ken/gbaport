/* render.c - the GBA's picture, drawn one scanline at a time.
 *
 * gba_render_line(rt, y) draws line y into rt->screen when the line's HDraw ends, before
 * the HBlank interrupt and HBlank DMA (as mGBA does), from the registers, VRAM and palette
 * as they are then: a game that changes them between lines gets its raster effects. Each
 * enabled layer is drawn into a line of its own; then every pixel takes the colour of the
 * topmost layer there, or the backdrop, palette entry 0. The lower priority number is on
 * top; at equal priority sprites come before backgrounds, and BG0 before BG3. Forced blank
 * draws white.
 *
 * Text backgrounds (BG0-BG3 in mode 0, BG0 and BG1 in mode 1) are 8x8 tiles named by a
 * map of 32x32 entries per 2 KiB screen block: 256 or 512 pixels each way, scrolled by
 * BGnHOFS/BGnVOFS with wrap-around. An entry holds the tile number, flips and (for 16-colour
 * tiles) a palette bank. Tile data past background VRAM (0x10000) is transparent.
 *
 * Rotation/scaling backgrounds (BG2 in mode 1, BG2 and BG3 in mode 2) are 128 to 1024
 * pixels square, of 256-colour tiles named by one-byte map entries. Outside the square
 * they are transparent, or wrap around when BGnCNT bit 13 says so.
 *
 * Sprites (OAM's 128 entries, in order) come in 12 sizes from 8x8 to 64x64, 16 or 256
 * colours, with tiles laid out in 1D (DISPCNT bit 6) or in a 2D sheet 32 tiles wide; in
 * the bitmap modes the tiles below 512 belong to the picture and are not drawn. A
 * rotation/scaling sprite samples its tiles through one of 32 matrices kept in OAM, around
 * its centre, in a box twice its size with "double size". Like mGBA, an earlier sprite
 * wins at equal priority, a later sprite's transparent pixel still passes its lower
 * priority number to the pixel below it, and a line takes sprites only while it has time:
 * 1210 cycles (954 with "HBlank interval free"), a sprite costing its width, or 10 plus
 * twice its box's width when it rotates.
 *
 * Windows choose which layers show where. With any of DISPCNT bits 13-15 set, every pixel
 * takes the layer bits of the first window it is in: WIN0, then WIN1 (rectangles, from
 * WINnH/WINnV), then the OBJ window (where OBJ window sprites have a colour), and
 * otherwise WINOUT. A rectangle whose end comes before its start wraps around; coordinates
 * past the screen are cut back to its edge, as in mGBA.
 *
 * Colour special effects (BLDCNT) work on the topmost layer when it is a 1st target and
 * the window allows effects: alpha blending with the layer right below it, when that is a
 * 2nd target (BLDALPHA's factors, at most 16/16), or brightening or darkening (BLDY, at
 * most 16/16), in 5 bits per channel like the GBA: c + (31 - c) * EVY / 16 and
 * c - c * EVY / 16, rounded down, as GBATEK gives them. (mGBA rounds the amount it darkens
 * by up in some channels, so its partial darkening can be one step darker.) A
 * semi-transparent sprite on top of a 2nd target blends with it whatever BLDCNT's effect
 * and the window say. Anywhere else it is brightened or darkened when sprites are a 1st
 * target, and also, as in mGBA, when an enabled background or the backdrop is a 2nd
 * target (GBATEK only says such sprites are always 1st targets).
 *
 * Mosaic (MOSAIC, for backgrounds with BGnCNT bit 6 and sprites with OAM bit 12) shows
 * blocks: every line repeats the first line of its group of lines, every pixel the first
 * pixel of its group of pixels, groups counted from the screen's top-left corner. As in
 * mGBA, a rotation/scaling or bitmap background whose group starts outside it tries again
 * at the next pixel; a sprite's line comes from its first line inside the group, and a
 * plain sprite widens to the end of its last group, repeating its edge.
 *
 * The rotation/scaling backgrounds (BG2 and BG3 outside mode 0) walk their picture from
 * an internal reference point: BGxX/BGxY at the start of every frame and whenever the game
 * writes them, moved by (PB, PD) after every line drawn while the background is on. Along
 * a line, each pixel moves it by (PA, PC). */
#include "gba_runtime.h"

#define IO(rt, offset) ((rt)->io[(offset) >> 1])
#define CLEAR 0x8000u  /* no colour here: what is below shows through */

enum { W = GBA_SCREEN_WIDTH, H = GBA_SCREEN_HEIGHT };

typedef struct {
    uint16_t bg[4][W];         /* each background's colours on this line, or CLEAR */
    uint16_t obj[W];           /* the sprites' colours, or CLEAR */
    uint8_t obj_priority[W];   /* the sprites' priority; 4 where none drew */
    uint8_t obj_window[W];     /* where an OBJ window sprite has a colour */
    uint8_t obj_semi[W];       /* the sprite colour there is semi-transparent */
} Layers;

static const uint8_t SPRITE_SIZES[16][2] = {  /* by shape * 4 + size: width, height */
    {8, 8}, {16, 16}, {32, 32}, {64, 64}, {16, 8}, {32, 8}, {32, 16}, {64, 32},
    {8, 16}, {8, 32}, {16, 32}, {32, 64}, {0, 0}, {0, 0}, {0, 0}, {0, 0},
};

static uint16_t halfword(const uint8_t *memory, uint32_t offset)
{
    return (uint16_t)(memory[offset] | memory[offset + 1] << 8);
}

static uint16_t color_at(const uint8_t *memory, uint32_t offset)
{
    return halfword(memory, offset) & 0x7FFF;
}

/* BGxX or BGxY (offset of its low half): a signed 28-bit 20.8 fixed-point value. */
static int32_t reference(const GbaRuntime *rt, uint32_t offset)
{
    uint32_t value = IO(rt, offset) | (uint32_t)IO(rt, offset + 2) << 16;
    return (int32_t)(value << 4) >> 4;
}

void gba_render_frame_start(GbaRuntime *rt)
{
    for (int n = 0; n < 2; n++) {
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
    }
}

void gba_render_reference_write(GbaRuntime *rt, uint32_t offset)
{
    int n = offset >= 0x38;  /* BG3 */
    if ((offset & 0xF) < 0xC)
        rt->affine_x[n] = reference(rt, 0x28 + 0x10 * n);
    else
        rt->affine_y[n] = reference(rt, 0x2C + 0x10 * n);
}

/* Horizontal mosaic: every group of `size` pixels shows its first pixel. */
static void hold(uint16_t *line, unsigned size)
{
    for (int x = 0; size > 1 && x < W; x++)
        line[x] = line[x - x % size];
}

/* A text background's line. */
static void text_line(const GbaRuntime *rt, int n, int y, uint16_t *out)
{
    uint16_t control = IO(rt, 0x08 + 2 * n), mosaic = IO(rt, 0x4C);
    if (control & 0x40)
        y -= y % (int)(((mosaic >> 4) & 15) + 1);
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    unsigned size = control >> 14, colors256 = control & 0x80;
    unsigned in_y = (unsigned)(y + IO(rt, 0x12 + 4 * n)) & 0x1FF;
    unsigned hofs = IO(rt, 0x10 + 4 * n);
    uint32_t row = (in_y & 0xF8) * 4;  /* the map entry that starts this row of tiles */
    if (size == 2)
        row += (in_y & 0x100) * 4;  /* 256x512: the lower half is the next block */
    else if (size == 3)
        row += (in_y & 0x100) * 8;  /* 512x512: two blocks further */
    for (int x = 0; x < W; x++) {
        unsigned in_x = (x + hofs) & 0x1FF;
        uint32_t index = row + (in_x & 0xF8) / 8;
        if (size & 1)
            index += (in_x & 0x100) * 4;  /* the right half is the next block */
        uint32_t entry = halfword(rt->vram, screen_base + index * 2);
        unsigned tx = in_x & 7, ty = in_y & 7;
        if (entry & 0x400)
            tx = 7 - tx;
        if (entry & 0x800)
            ty = 7 - ty;
        uint32_t tile = entry & 0x3FF, address;
        out[x] = CLEAR;
        if (colors256)
            address = char_base + tile * 64 + ty * 8 + tx;
        else
            address = char_base + tile * 32 + ty * 4 + tx / 2;
        if (address >= 0x10000)
            continue;
        unsigned color = rt->vram[address];
        if (!colors256)
            color = tx & 1 ? color >> 4 : color & 15;
        if (color)
            out[x] = color_at(rt->palette, (colors256 ? color : (entry >> 12) * 16 + color) * 2);
    }
    if (control & 0x40)
        hold(out, (mosaic & 15) + 1u);
}

/* The colour of BG2/BG3's texel (tx, ty), or CLEAR; *outside says it is off a background
 * that does not wrap around. mode is DISPCNT's: 1-2 tiles, 3-5 a bitmap (BG2). */
static uint16_t texel(const GbaRuntime *rt, int n, uint32_t mode, int32_t tx, int32_t ty, int *outside)
{
    uint16_t control = IO(rt, 0x08 + 2 * n);
    *outside = 0;
    if (mode >= 3) {
        uint32_t page = IO(rt, GBA_REG_DISPCNT) & 0x10 ? 0xA000 : 0;
        int width = mode == 5 ? 160 : 240, height = mode == 5 ? 128 : 160;
        if (tx < 0 || ty < 0 || tx >= width || ty >= height) {
            *outside = 1;
            return CLEAR;
        }
        if (mode == 3)
            return color_at(rt->vram, (uint32_t)(ty * 240 + tx) * 2);
        if (mode == 5)
            return color_at(rt->vram, page + (uint32_t)(ty * 160 + tx) * 2);
        uint8_t index = rt->vram[page + (uint32_t)(ty * 240 + tx)];
        return index ? color_at(rt->palette, index * 2u) : CLEAR;
    }
    int32_t size = 128 << (control >> 14);  /* pixels each way */
    if (control & 0x2000) {  /* wrap around */
        tx &= size - 1;
        ty &= size - 1;
    } else if (tx < 0 || ty < 0 || tx >= size || ty >= size) {
        *outside = 1;
        return CLEAR;
    }
    uint32_t char_base = ((control >> 2) & 3) * 0x4000u;
    uint32_t screen_base = ((control >> 8) & 31) * 0x800u;
    uint32_t tile = rt->vram[screen_base + (uint32_t)((ty >> 3) * (size >> 3) + (tx >> 3))];
    uint8_t color = rt->vram[char_base + tile * 64 + (uint32_t)((ty & 7) * 8 + (tx & 7))];
    return color ? color_at(rt->palette, color * 2u) : CLEAR;
}

/* A line of BG2 or BG3 outside mode 0, walked from its reference point. */
static void affine_line(const GbaRuntime *rt, int n, int y, uint32_t mode, uint16_t *out)
{
    int k = n - 2;
    int32_t x = rt->affine_x[k], v = rt->affine_y[k];
    int32_t dx = (int16_t)IO(rt, 0x20 + 0x10 * k), dy = (int16_t)IO(rt, 0x24 + 0x10 * k);
    unsigned size = 1, wait = 0;
    uint16_t held = CLEAR;
    if (IO(rt, 0x08 + 2 * n) & 0x40) {  /* mosaic: from the group's first line */
        uint16_t mosaic = IO(rt, 0x4C);
        int back = y % (int)(((mosaic >> 4) & 15) + 1);
        x -= back * (int16_t)IO(rt, 0x22 + 0x10 * k);  /* PB */
        v -= back * (int16_t)IO(rt, 0x26 + 0x10 * k);  /* PD */
        size = (mosaic & 15) + 1u;
    }
    for (int i = 0; i < W; i++, x += dx, v += dy) {
        if (wait) {
            wait--;
            out[i] = held;
            continue;
        }
        int outside;
        out[i] = texel(rt, n, mode, x >> 8, v >> 8, &outside);
        if (!outside) {  /* a group that starts outside starts again at the next pixel */
            held = out[i];
            wait = size - 1;
        }
    }
}

/* One sprite's part of line y (in_y: the line within its box; group: its mosaic's width). */
static void sprite_line(const GbaRuntime *rt, const uint8_t *entry, int in_y, int group,
                        Layers *layers)
{
    uint16_t a0 = halfword(entry, 0), a1 = halfword(entry, 2), a2 = halfword(entry, 4);
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    int width = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][0];
    int height = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][1];
    int affine = a0 & 0x100, twice = affine && (a0 & 0x200);
    int box_w = width << twice, box_h = height << twice;
    int left = (int)(a1 & 0x1FF) - ((a1 & 0x100) ? 512 : 0);
    unsigned colors256 = a0 & 0x2000, one_d = control & 0x40, tile = a2 & 0x3FF;
    if ((control & 7) >= 3 && tile < 512)
        return;
    if (colors256 && !one_d)
        tile &= ~1u;
    uint32_t start = tile * 32;
    uint32_t stride = one_d ? (uint32_t)width * (colors256 ? 8 : 4) / 8 : 0x80;  /* per line of tiles */
    uint32_t across = one_d ? 0x7FFF : 0x3FF, row_base = one_d ? 0 : start & 0x7C00;
    uint32_t palette = 0x200 + (colors256 ? 0 : (a2 >> 12) * 32u);
    uint8_t priority = (a2 >> 10) & 3;
    int window = ((a0 >> 10) & 3) == 2;  /* draws the OBJ window, not colours */
    uint8_t semi = ((a0 >> 10) & 3) == 1;
    int16_t pa = 0, pb = 0, pc = 0, pd = 0;
    if (affine) {
        const uint8_t *matrix = rt->oam + ((a1 >> 9) & 31) * 32;
        pa = (int16_t)halfword(matrix, 6);
        pb = (int16_t)halfword(matrix, 14);
        pc = (int16_t)halfword(matrix, 22);
        pd = (int16_t)halfword(matrix, 30);
    }
    int right = left + box_w;
    if (group > 1 && right < W && right % group)
        right += group - right % group;  /* mosaic: on to the end of the last group */
    int first = left < 0 ? 0 : left;
    int32_t cy = in_y - box_h / 2, cx = first - 1 - left - box_w / 2;
    int held_x = (pa * cx + pb * cy + (width << 7)) >> 8;  /* a rotating sprite's sample */
    int held_y = (pc * cx + pd * cy + (height << 7)) >> 8;
    for (int x = first; x < right && x < W; x++) {
        int tx, ty = in_y;
        if (affine) {
            if (x % group == 0) {  /* every group samples where it starts */
                cx = x - left - box_w / 2;
                held_x = (pa * cx + pb * cy + (width << 7)) >> 8;
                held_y = (pc * cx + pd * cy + (height << 7)) >> 8;
            }
            tx = held_x;
            ty = held_y;
            if (tx < 0 || ty < 0 || tx >= width || ty >= height)
                continue;
        } else {
            tx = x - x % group - left;
            if (a1 & 0x1000)
                tx = width - 1 - tx;
            if (a1 & 0x2000)
                ty = height - 1 - ty;
            tx = tx < 0 ? 0 : tx >= width ? width - 1 : tx;  /* mosaic past the edges */
        }
        uint32_t x_part, y_part;
        if (colors256) {
            x_part = (uint32_t)(tx & ~7) * 8 + (uint32_t)(tx & 7);
            y_part = (uint32_t)(ty & ~7) * stride + (uint32_t)(ty & 7) * 8;
        } else {
            x_part = (uint32_t)(tx & ~7) * 4 + (uint32_t)(tx & 7) / 2;
            y_part = (uint32_t)(ty & ~7) * stride + (uint32_t)(ty & 7) * 4;
        }
        unsigned color = rt->vram[0x10000 + ((y_part + row_base + ((x_part + start) & across)) & 0x7FFF)];
        if (!colors256)
            color = tx & 1 ? color >> 4 : color & 15;
        if (window) {
            if (color)
                layers->obj_window[x] = 1;
            continue;
        }
        if (layers->obj_priority[x] <= priority)
            continue;  /* an earlier sprite, or one with a lower priority number, is on top */
        if (color) {
            layers->obj[x] = color_at(rt->palette, palette + color * 2);
            layers->obj_priority[x] = priority;
            layers->obj_semi[x] = semi;
        } else if (layers->obj[x] != CLEAR) {
            layers->obj_priority[x] = priority;  /* the transparent pixel still passes its priority, */
            layers->obj_semi[x] = semi;          /* and whether it is semi-transparent */
        }
    }
}

/* Line y of the sprite layer. */
static void sprites_line(const GbaRuntime *rt, int y, Layers *layers)
{
    for (int x = 0; x < W; x++) {
        layers->obj[x] = CLEAR;
        layers->obj_priority[x] = 4;
        layers->obj_window[x] = 0;
        layers->obj_semi[x] = 0;
    }
    int time = IO(rt, GBA_REG_DISPCNT) & 0x20 ? 954 : 1210;
    uint16_t mosaic = IO(rt, 0x4C);
    int group_w = ((mosaic >> 8) & 15) + 1, group_h = ((mosaic >> 12) & 15) + 1;
    for (int i = 0; i < 128; i++) {
        const uint8_t *entry = rt->oam + i * 8;
        uint16_t a0 = halfword(entry, 0), a1 = halfword(entry, 2);
        int affine = a0 & 0x100;
        if (!affine && (a0 & 0x200))
            continue;  /* hidden */
        int width = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][0];
        int height = SPRITE_SIZES[(a0 >> 14) * 4 + (a1 >> 14)][1];
        int twice = affine && (a0 & 0x200);
        int top = a0 & 0xFF, left = a1 & 0x1FF, box_w = width << twice, box_h = height << twice;
        if ((top >= H && top + box_h < 228) || (left >= W && left + box_w < 512))
            continue;  /* nowhere on the screen */
        int bottom = top + box_h;
        if ((y < top && (bottom < 256 || y >= bottom - 256)) || y >= bottom)
            continue;  /* not on this line */
        int line = y, mosaic_on = a0 & 0x1000;
        if (mosaic_on && group_h > 1) {  /* the group's first line that is inside the sprite */
            line = y - y % group_h;
            if (line < top && top < H)
                line = top;
            if (line >= (bottom & 0xFF))
                line = bottom - 1;
        }
        int in_y = line - top;
        if (affine ? in_y < 0 : top + height >= 256)
            in_y += 256;  /* the sprite wraps past line 255 */
        sprite_line(rt, entry, in_y, mosaic_on ? group_w : 1, layers);
        time -= affine ? 10 + box_w * 2 : width;
        if (time <= 0)
            break;
    }
}

/* WINnH or WINnV: start (high byte) and end (low byte), cut back to the screen as mGBA
 * does; returns whether position `at` is inside. */
static int inside(uint16_t value, int limit, int at)
{
    int start = value >> 8, end = value & 0xFF;
    if (start > limit && start > end)
        start = 0;
    if (end > limit) {
        end = limit;
        if (start > limit)
            start = limit;
    }
    if (end >= start)
        return at >= start && at < end;
    return at >= start || at < end;  /* wraps around */
}

/* Each pixel's layer bits (BG0-BG3, sprites, effects) on line y. */
static void window_line(const GbaRuntime *rt, int y, const Layers *layers, uint8_t *region)
{
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    if (!(control & 0xE000)) {
        for (int x = 0; x < W; x++)
            region[x] = 0x3F;
        return;
    }
    uint16_t win_in = IO(rt, 0x48), win_out = IO(rt, 0x4A);
    int in0 = (control & 0x2000) && inside(IO(rt, 0x44), H, y);
    int in1 = (control & 0x4000) && inside(IO(rt, 0x46), H, y);
    for (int x = 0; x < W; x++) {
        if (in0 && inside(IO(rt, 0x40), W, x))
            region[x] = win_in & 0x3F;
        else if (in1 && inside(IO(rt, 0x42), W, x))
            region[x] = (win_in >> 8) & 0x3F;
        else if ((control & 0x8000) && layers->obj_window[x])
            region[x] = (win_out >> 8) & 0x3F;
        else
            region[x] = win_out & 0x3F;
    }
}

static unsigned weight(unsigned value)  /* an effect factor: 0-16 sixteenths */
{
    value &= 0x1F;
    return value > 16 ? 16 : value;
}

static uint16_t mix(uint16_t a, uint16_t b, unsigned wa, unsigned wb)
{
    uint16_t out = 0;
    for (int shift = 0; shift < 15; shift += 5) {
        unsigned c = (((a >> shift) & 31) * wa + ((b >> shift) & 31) * wb) / 16;
        out |= (uint16_t)((c > 31 ? 31 : c) << shift);
    }
    return out;
}

static uint16_t brightness(uint16_t color, unsigned evy, int up)
{
    uint16_t out = 0;
    for (int shift = 0; shift < 15; shift += 5) {
        unsigned c = (color >> shift) & 31;
        c = up ? c + (31 - c) * evy / 16 : c - c * evy / 16;
        out |= (uint16_t)(c << shift);
    }
    return out;
}

/* Every pixel: the topmost layer with a colour there (layer 0-3: a background, 4: the
 * sprites, 5: the backdrop), with the colour effects. */
static void compose(const GbaRuntime *rt, const Layers *layers, unsigned all, int y, uint16_t *row)
{
    uint16_t backdrop = color_at(rt->palette, 0);
    uint16_t targets = IO(rt, 0x50), factors = IO(rt, 0x52);
    unsigned effect = (targets >> 6) & 3, eva = weight(factors), evb = weight(factors >> 8);
    unsigned evy = weight(IO(rt, 0x54));
    /* a semi-transparent sprite is a 1st target for brightness when an enabled background
     * or the backdrop is a 2nd target (as mGBA does) */
    unsigned any_second = (targets >> 8) & (0x20u | ((IO(rt, GBA_REG_DISPCNT) >> 8) & 0xFu));
    uint8_t region[W];
    window_line(rt, y, layers, region);
    for (int x = 0; x < W; x++) {
        unsigned enabled = all & region[x];
        int layer[2] = {5, 5}, found = 0;
        uint16_t color[2] = {backdrop, backdrop};
        for (unsigned priority = 0; priority < 4 && found < 2; priority++) {
            if ((enabled & 0x10) && layers->obj_priority[x] == priority && layers->obj[x] != CLEAR) {
                layer[found] = 4;
                color[found++] = layers->obj[x];
            }
            for (int n = 0; n < 4 && found < 2; n++) {
                if ((enabled & (1u << n)) && (IO(rt, 0x08 + 2 * n) & 3) == priority &&
                    layers->bg[n][x] != CLEAR) {
                    layer[found] = n;
                    color[found++] = layers->bg[n][x];
                }
            }
        }
        int second = (targets >> 8) & (1u << layer[1]);
        if (layer[0] == 4 && layers->obj_semi[x] && second) {
            color[0] = mix(color[0], color[1], eva, evb);
        } else if ((region[x] & 0x20) && ((targets & (1u << layer[0])) ||
                                          (layer[0] == 4 && layers->obj_semi[x] && any_second))) {
            if (effect == 1 && second)
                color[0] = mix(color[0], color[1], eva, evb);
            else if (effect >= 2)
                color[0] = brightness(color[0], evy, effect == 2);
        }
        row[x] = color[0];
    }
}

void gba_render_line(GbaRuntime *rt, int y)
{
    uint16_t *row = rt->screen[y];
    uint16_t control = IO(rt, GBA_REG_DISPCNT);
    uint32_t mode = control & 7;
    if (control & 0x80) {  /* forced blank */
        for (int x = 0; x < W; x++)
            row[x] = 0x7FFF;
        return;
    }
    static Layers layers;
    unsigned enabled = 0;
    for (int n = 0; n < 4; n++) {
        int text = mode == 0 || (mode == 1 && n < 2);
        if (text && (control & (0x100u << n))) {
            text_line(rt, n, y, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
    for (int n = 2; n < 4; n++) {
        int affine = (mode == 1 && n == 2) || mode == 2 || (mode >= 3 && mode <= 5 && n == 2);
        if (affine && (control & (0x100u << n))) {
            affine_line(rt, n, y, mode, layers.bg[n]);
            enabled |= 1u << n;
        }
    }
    if (control & 0x1000) {
        sprites_line(rt, y, &layers);
        enabled |= 0x10;
    } else {
        for (int x = 0; x < W; x++)
            layers.obj_window[x] = 0;  /* no sprites, no OBJ window */
    }
    compose(rt, &layers, enabled, y, row);
    for (int n = 0; n < 2; n++) {
        if (mode != 0 && (control & (0x400u << n))) {
            rt->affine_x[n] += (int16_t)IO(rt, 0x22 + 0x10 * n);  /* PB */
            rt->affine_y[n] += (int16_t)IO(rt, 0x26 + 0x10 * n);  /* PD */
        }
    }
}
