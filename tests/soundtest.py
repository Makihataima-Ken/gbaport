"""Sound tests: a test ROM's sound, recompiled and run natively, against mGBA's.

Both sides give the samples the GBA mixes, 32768 a second, as (left, right) pairs of
signed 16-bit values: ours from the headless host's ``--audio`` WAV file, mGBA's from
``mgba_sound``. The recompiled code's cycle counts are estimates, so a register write can
land a little earlier or later than in mGBA; the comparison allows each change in the
sound to move by a few samples, and nothing else.

A scene must therefore not mix two sounds that change on their own clocks on one side: a
channel whose timing starts at a register write (the wave and noise channels, a FIFO's
timer) can then move against one whose timing counts from the game's start (the squares),
making sums that mGBA never makes. Channels that change together (FIFOs on one timer, the
two squares) or hold a steady level can share a side.
"""

import struct
import tempfile
import wave
from pathlib import Path

from mgbaref import mgba_sound
from romtest import CACHE, TestRom, _digest, build_test_rom, run_rom

RATE = 32768
WAVE_A = bytes((i * 5 + (i >> 8) * 16) & 0xFF for i in range(0x4000))  # a stepped sawtooth


def _noise() -> bytes:
    value, out = 1, bytearray()
    for _ in range(0x4000):
        value = (value * 1103515245 + 12345) & 0x7FFFFFFF
        out.append(value >> 16 & 0xFF)
    return bytes(out)


WAVE_B = _noise()


WORD, BYTE = 0x8000, 0x4000  # in a script's offset: a 32-bit or an 8-bit write


def word(frame: int, offset: int, value: int) -> tuple[int, int, int]:
    """A 32-bit write for a script."""
    return frame, offset | WORD, value


def byte(frame: int, offset: int, value: int) -> tuple[int, int, int]:
    """An 8-bit write for a script."""
    return frame, offset | BYTE, value


def script(writes: list[tuple[int, int, int]]) -> str:
    """testdata.h for sound.c: (frame, offset from 0x04000000, value) writes, 16-bit unless
    `word` or `byte` made them."""
    rows = ", ".join(f"{{{frame}, 0x{offset:03x}, 0x{value:04x}}}" for frame, offset, value in writes)
    waves = [", ".join(str(b) for b in data) for data in (WAVE_A, WAVE_B)]
    return (f"#define WRITES {{{rows}}}\n#define WAVE_A {{{waves[0]}}}\n"
            f"#define WAVE_B {{{waves[1]}}}\n")


def read_wav(path: Path) -> list[tuple[int, int]]:
    """A 16-bit stereo WAV file's samples, checked to be 32768 a second."""
    with wave.open(str(path), "rb") as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (2, 2, RATE)
        data = audio.readframes(audio.getnframes())
    values = memoryview(data).cast("h")
    return list(zip(values[0::2], values[1::2], strict=True))


def write_wav(path: Path, samples: list[tuple[int, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(struct.pack(f"<{2 * len(samples)}h", *(v for s in samples for v in s)))


def our_sound(rom: TestRom, frames: int) -> list[tuple[int, int]]:
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "sound.wav"
        run = run_rom(rom, frames=frames, args=("--audio", str(path)))
        assert run.status in (0, 4), f"exit status {run.status}: {run.stderr}"
        return read_wav(path)


SEARCH = 16  # how far the whole sound may be shifted, in samples
SLACK = 2    # how far each change in it may move besides, in samples


def sound_difference(ours: list[tuple[int, int]], reference: list[tuple[int, int]]) -> str | None:
    """None when ``ours`` is ``reference`` shifted by at most SEARCH samples, give or take
    SLACK samples at every change on either side; otherwise what differs."""
    n = min(len(ours), len(reference))
    if abs(len(ours) - len(reference)) > 600:
        return f"{len(ours)} samples instead of {len(reference)}"
    lo, hi = SEARCH + SLACK, n - SEARCH - SLACK
    shift = max(range(-SEARCH, SEARCH + 1),  # the best match; the smallest shift of equals
                key=lambda d: (sum(ours[i] == reference[i + d] for i in range(lo, hi)), -abs(d)))

    def near(value: int, side: list[int], at: int) -> bool:
        return value in side[at - SLACK:at + SLACK + 1]

    sides = [([s[k] for s in ours], [s[k] for s in reference]) for k in (0, 1)]
    wrong = [i for i in range(lo, hi)
             if any(not near(o[i], r, i + shift) or not near(r[i + shift], o, i) for o, r in sides)]
    if not wrong:
        return None
    first = wrong[0]
    return (f"{len(wrong)} of {hi - lo} samples differ from mGBA's (shifted by {shift}), the "
            f"first at {first} ({first / RATE:.4f} s): {ours[first]} instead of "
            f"{reference[first + shift]}")


def assert_same_sound(rom: TestRom, frames: int = 60) -> None:
    """The native build of ``rom`` sounds like mGBA for ``frames`` frames. When it does not,
    both sounds are written to the test-ROM cache as WAV files, and the message names them."""
    ours, reference = our_sound(rom, frames), mgba_sound(rom.data, frames)
    difference = sound_difference(ours, reference)
    if difference:
        folder = CACHE / "sounds"
        write_wav(folder / f"{_digest(rom.data)}-ours.wav", ours)
        write_wav(folder / f"{_digest(rom.data)}-mgba.wav", reference)
        raise AssertionError(f"{difference} (see {folder / _digest(rom.data)}-*.wav)")


def assert_script_matches(writes: list[tuple[int, int, int]], frames: int = 60) -> None:
    assert_same_sound(build_test_rom("sound", script(writes)), frames)
