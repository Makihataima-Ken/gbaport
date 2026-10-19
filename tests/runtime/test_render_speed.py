"""A busy picture: four backgrounds, 128 rotating sprites, both windows and the sprite
window, blending and mosaic, all at once. It looks like mGBA's, and the native build draws
it faster than the GBA shows it.

Two things mGBA does differently from the GBA are left out: it draws the sprites that make
the OBJ window without mosaic, and it restarts a 256-colour background's mosaic where a
window starts. So those sprites and BG2 (256 colours) have no mosaic here."""

import math
import time

from rendertest import assert_same_picture, obj, our_picture, scene
from romtest import build_test_rom

DISPCNT, BGCNT, MOSAIC = 0x000, 0x008, 0x04C
WIN0H, WIN1H, WIN0V, WIN1V, WININ, WINOUT = 0x040, 0x042, 0x044, 0x046, 0x048, 0x04A
BLDCNT, BLDALPHA = 0x050, 0x052
MATRICES = [
    (round(256 * math.cos(a) / s), round(-256 * math.sin(a) / s),
     round(256 * math.sin(a) / s), round(256 * math.cos(a) / s))
    for a, s in ((2 * math.pi * i / 32, 0.75 + i / 40) for i in range(32))
]
SPRITES = [
    obj(37 * i % 240, 23 * i % 160, i % 3, 2 + i % 2, tile=16 * i % 1024, palette=i % 16,
        priority=i % 4, affine=i % 32, double=True, mode=i % 3)
    for i in range(128)
]
BUSY = scene([
    (BGCNT, 0x1040 | 3), (BGCNT + 2, 0x1244 | 2), (BGCNT + 4, 0x1480 | 1), (BGCNT + 6, 0x1644),
    (0x010, 13), (0x016, 7), (0x018, 300), (0x01E, 99),
    (MOSAIC, 2 | 1 << 4 | 1 << 8 | 2 << 12),
    (WIN0H, 20 << 8 | 200), (WIN0V, 10 << 8 | 150), (WIN1H, 60 << 8 | 230), (WIN1V, 40 << 8 | 120),
    (WININ, 0x2F3F), (WINOUT, 0x371B), (BLDCNT, 0x3E41), (BLDALPHA, 9 << 8 | 7),
    (DISPCNT, 0xFF40),
], [(a0 if i % 3 == 2 else a0 | 0x1000, a1, a2) for i, (a0, a1, a2) in enumerate(SPRITES)],
    MATRICES)
FRAMES = 600  # ten seconds on a GBA


def test_a_busy_picture_looks_like_mgba():
    assert_same_picture(build_test_rom("scene", BUSY))


def test_a_busy_picture_is_drawn_faster_than_the_gba_shows_it():
    rom = build_test_rom("scene", BUSY)
    our_picture(rom, frames=1)  # builds the program
    start = time.perf_counter()
    our_picture(rom, frames=FRAMES)
    seconds = time.perf_counter() - start
    assert seconds < FRAMES / 59.73, f"{FRAMES} frames took {seconds:.1f} s"
