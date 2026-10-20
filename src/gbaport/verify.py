"""``gbaport verify``: a game's native build against mGBA, picture by picture.

Both play the same input file from power-on with a blank save and write a hash of each
frame's picture (``--hashes``). The comparison takes runs of equal frames as pictures and
walks the two sequences of pictures side by side. The native build counts cycles as mGBA
does, but not everything happens at exactly the same moment (an interrupt comes at a loop
or a return), so a picture may come a frame early or late. ``slack`` frames are allowed:
each picture both show must come
within that many frames of mGBA's, and a picture only one of them shows may last at most
that long. The first picture that breaks this is where they part; the pictures there go
side by side into a PNG file. The first frame is left out: the game starts in line 126, so
its top lines show nothing yet.
"""

import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path

from gbaport.native.mgba import run_mgba


@dataclass(frozen=True)
class Comparison:
    frames: int  # frames both played
    pictures: int  # pictures mGBA showed in them
    apart: int  # the most frames a picture came early or late
    parted: tuple[int, int] | None  # (our frame, mGBA's frame) where the pictures part


def _pictures(hashes: list[str]) -> list[tuple[str, int, int]]:
    """Runs of equal frames as (hash, first frame, frames), frames counted from 1 (the
    picture complete at the first VBlank); the first frame is left out."""
    runs: list[tuple[str, int, int]] = []
    for frame, value in enumerate(hashes[1:], start=2):
        if runs and runs[-1][0] == value:
            runs[-1] = (value, runs[-1][1], runs[-1][2] + 1)
        else:
            runs.append((value, frame, 1))
    return runs


def _past_extras(a: list[tuple[str, int, int]], b: list[tuple[str, int, int]], i: int, j: int,
                 slack: int) -> tuple[int, int] | None:
    """Where the two show the same picture again (or end) after pictures only one of them
    shows, at most ``slack`` frames of them on each side, the fewest first; None when
    there is no such place."""
    def reach(runs: list[tuple[str, int, int]], start: int) -> list[int]:
        ends, frames = [start], 0
        while ends[-1] < len(runs) and frames + runs[ends[-1]][2] <= slack:
            frames += runs[ends[-1]][2]
            ends.append(ends[-1] + 1)
        return ends

    places = [(x, y) for x in reach(a, i) for y in reach(b, j) if (x, y) != (i, j)]
    for x, y in sorted(places, key=lambda place: place[0] - i + place[1] - j):
        if x == len(a) or y == len(b) or a[x][0] == b[y][0]:
            return x, y
    return None


def compare(ours: list[str], theirs: list[str], slack: int = 1) -> Comparison:
    """Our frames' hashes against mGBA's, over the frames both have. One pass, so a long
    replay that parts early takes no longer than one that does not."""
    frames = min(len(ours), len(theirs))
    a, b = _pictures(ours[:frames]), _pictures(theirs[:frames])
    i = j = apart = 0
    while i < len(a) and j < len(b):
        if a[i][0] == b[j][0]:
            if abs(a[i][1] - b[j][1]) > slack:
                return Comparison(frames, len(b), apart, (a[i][1], b[j][1]))
            apart = max(apart, abs(a[i][1] - b[j][1]))
            i, j = i + 1, j + 1
            continue
        place = _past_extras(a, b, i, j, slack)
        if place is None:
            return Comparison(frames, len(b), apart, (a[i][1], b[j][1]))
        i, j = place
    return Comparison(frames, len(b), apart, None)


def report(comparison: Comparison) -> str:
    c = comparison
    if c.parted is None:
        frame_word = "frame" if c.apart == 1 else "frames"
        return (f"verified {c.frames} frames: {c.pictures} pictures in the same order, "
                f"at most {c.apart} {frame_word} apart")
    return f"the pictures part at frame {c.parted[0]} (mGBA's frame {c.parted[1]})"


def read_hashes(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def play(program: Path, rom: Path, frames: int, input: Path | None, folder: Path,
         extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
    """Runs the native build with a blank save; its hashes go to folder/ours.hashes."""
    save = folder / "verify.sav"
    save.unlink(missing_ok=True)
    command = [str(program), str(rom), "--frames", str(frames), "--save", str(save),
               "--hashes", str(folder / "ours.hashes"), *extra]
    if input is not None:
        command += ["--input", str(input)]
    return subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)


def _bmp_colours(data: bytes) -> list[int]:
    """The hosts' 24-bit, bottom-up 240x160 BMP as GBA colours."""
    offset = struct.unpack_from("<I", data, 10)[0]
    colours = []
    for y in range(160):
        row = offset + (159 - y) * 720
        for x in range(240):
            b, g, r = data[row + 3 * x: row + 3 * x + 3]
            colours.append(r >> 3 | (g >> 3) << 5 | (b >> 3) << 10)
    return colours


def write_png(path: Path, pictures: list[list[int]]) -> None:
    """240x160 GBA-colour pictures side by side, a grey gap between them."""
    rows = []
    for y in range(160):
        row = bytearray([0])
        for i, picture in enumerate(pictures):
            if i:
                row += b"\x80\x80\x80" * 4
            for c in picture[y * 240:(y + 1) * 240]:
                row += bytes(((c & 31) << 3, (c >> 5 & 31) << 3, (c >> 10 & 31) << 3))
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    width = 240 * len(pictures) + 4 * (len(pictures) - 1)
    header = struct.pack(">IIBBBBB", width, 160, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


def where_they_part(program: Path, rom: Path, parted: tuple[int, int], input: Path | None,
                    folder: Path) -> Path:
    """Our picture at our frame and mGBA's at its own, side by side: folder/frame-N.png."""
    ours, theirs = parted
    shot = folder / "ours.bmp"
    play(program, rom, ours, input, folder, ("--screenshot", str(shot)))
    run_mgba(rom, theirs, input=input, picture=folder / "mgba.raw", log=lambda line: None)
    mgba = list(struct.unpack("<38400H", (folder / "mgba.raw").read_bytes()))
    png = folder / f"frame-{ours}.png"
    write_png(png, [_bmp_colours(shot.read_bytes()), mgba])
    return png


def verify(program: Path, rom: Path, frames: int, input: Path | None, folder: Path,
           slack: int = 1) -> int:
    """Plays ``rom`` natively and in mGBA, prints how their pictures compare, and returns 0
    when they agree within ``slack`` frames for all of them, 1 when they part or the native
    build stopped first."""
    folder.mkdir(parents=True, exist_ok=True)
    run = play(program, rom, frames, input, folder)
    if run.returncode not in (0, 4):
        last = (run.stderr.strip().splitlines() or ["(no message)"])[-1]
        print(f"the native build stopped (exit status {run.returncode}): {last}")
    ours = read_hashes(folder / "ours.hashes")
    if run.returncode == 0 and len(ours) < frames:
        print(f"the native build stopped at frame {len(ours)}: the game executed Stop and "
              "nothing woke it")
    run_mgba(rom, frames, input=input, hashes=folder / "mgba.hashes")
    comparison = compare(ours, read_hashes(folder / "mgba.hashes"), slack)
    print(report(comparison))
    if comparison.parted is not None:
        print(f"wrote {where_they_part(program, rom, comparison.parted, input, folder)} "
              "(ours, then mGBA's)")
        return 1
    return 0 if run.returncode == 4 else 1  # all the frames, compared
