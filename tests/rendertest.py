"""Renderer tests: a test ROM's picture, recompiled and run natively, against mGBA's.

Pictures are compared as GBA colours (15-bit), so the two ways of widening them to 24 bits
do not matter. When they differ, a PNG with mGBA's picture, ours and the differences (in
red) side by side is written to the test-ROM cache, and the message names it.
"""

import struct
import tempfile
import zlib
from pathlib import Path

from mgbaref import mgba_picture
from romtest import CACHE, TestRom, _digest, build_test_rom, read_bmp, run_rom


def gba_colour(pixel: int) -> int:
    """0x00RRGGBB, as the hosts widen a GBA colour, back to 0BBBBBGGGGGRRRRR."""
    return (pixel >> 19 & 31) | (pixel >> 11 & 31) << 5 | (pixel >> 3 & 31) << 10


def our_picture(rom: TestRom, frames: int) -> list[int]:
    with tempfile.TemporaryDirectory() as scratch:
        shot = Path(scratch) / "screen.bmp"
        run = run_rom(rom, frames=frames, args=("--screenshot", str(shot)))
        assert run.status in (0, 4), f"exit status {run.status}: {run.stderr}"
        return [gba_colour(p) for p in read_bmp(shot)]


def _png(path: Path, pictures: list[list[int]]) -> None:
    def rgb(c: int) -> bytes:
        return bytes([(c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3])

    rows = []
    for y in range(160):
        row = bytearray([0])
        for i, picture in enumerate(pictures):
            if i:
                row += b"\x80\x80\x80" * 4  # a grey gap between them
            for x in range(240):
                row += rgb(picture[y * 240 + x])
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    width = 240 * len(pictures) + 4 * (len(pictures) - 1)
    header = struct.pack(">IIBBBBB", width, 160, 8, 2, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def assert_same_picture(rom: TestRom, frames: int = 30) -> None:
    """The native build of ``rom`` shows what mGBA shows after ``frames`` frames."""
    ours, reference = our_picture(rom, frames), mgba_picture(rom.data, frames)
    if ours == reference:
        return
    wrong = [i for i in range(len(ours)) if ours[i] != reference[i]]
    differences = [0x001F if i in set(wrong) else 0 for i in range(len(ours))]
    picture = CACHE / "pictures" / f"{_digest(rom.data)}.png"
    _png(picture, [reference, ours, differences])
    x, y = wrong[0] % 240, wrong[0] // 240
    raise AssertionError(
        f"{len(wrong)} pixels differ from mGBA's picture, the first at ({x}, {y}): "
        f"{ours[wrong[0]]:#06x} instead of {reference[wrong[0]]:#06x} (see {picture})"
    )


def assert_test_rom_matches(name: str, data: str = "", frames: int = 30) -> None:
    assert_same_picture(build_test_rom(name, data), frames)


IDENTITY = (0x100, 0, 0, 0x100)


def obj(x: int, y: int, shape: int = 0, size: int = 0, tile: int = 0, palette: int = 0,
        priority: int = 0, colors256: bool = False, hflip: bool = False, vflip: bool = False,
        affine: int | None = None, double: bool = False, mode: int = 0) -> tuple[int, int, int]:
    """OAM attributes 0-2 of a sprite (affine: its matrix number)."""
    a0 = (y & 0xFF) | mode << 10 | (0x2000 if colors256 else 0) | shape << 14
    a1 = (x & 0x1FF) | size << 14
    if affine is None:
        a1 |= hflip << 12 | vflip << 13
    else:
        a0 |= 0x100 | (0x200 if double else 0)
        a1 |= affine << 9
    return a0, a1, tile | priority << 10 | palette << 12


def scene(io: list[tuple[int, int]], objs=(), matrices=(IDENTITY,)) -> str:
    """testdata.h for scene.c: register writes ({offset, value}, in order), sprites and
    matrices."""
    writes = ", ".join(f"{{0x{offset:03x}, 0x{value:04x}}}" for offset, value in io)
    rows = ", ".join(f"{{{a}, {b}, {c}}}" for a, b, c in objs) or "{0x0200, 0, 0}"
    mats = ", ".join(f"{{{a}, {b}, {c}, {d}}}" for a, b, c, d in matrices)
    return f"#define IO_WRITES {{{writes}}}\n#define OBJS {{{rows}}}\n#define MATRICES {{{mats}}}\n"
