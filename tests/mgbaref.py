"""mGBA as the reference picture and sound for the renderer and sound tests.

``gbaport.native.mgba`` builds mGBA's GBA core with gbaport's reference program (once, into
the cache folder) and runs it; these helpers hand it a test ROM and read back what it wrote.
"""

import struct
import tempfile
from pathlib import Path

from gbaport.native.mgba import run_mgba


def _reference(rom: bytes, frames: int, sound: bool, input: str | None) -> tuple[bytes, bytes]:
    """mGBA's picture and (with ``sound``) sound files after ``frames`` frames, holding the
    keys ``input`` (an input file's text) names."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch)
        rom_path, picture, sound_path = folder / "game.gba", folder / "picture.raw", folder / "sound.raw"
        rom_path.write_bytes(rom)
        input_path = None
        if input is not None:
            input_path = folder / "input.txt"
            input_path.write_text(input, encoding="utf-8")
        run_mgba(rom_path, frames, input=input_path, picture=picture,
                 sound=sound_path if sound else None, log=lambda line: None)
        return picture.read_bytes(), sound_path.read_bytes() if sound else b""


def mgba_picture(rom: bytes, frames: int, input: str | None = None) -> list[int]:
    """mGBA's picture after ``frames`` frames: 240x160 GBA colours (0BBBBBGGGGGRRRRR),
    top row first."""
    return list(struct.unpack("<38400H", _reference(rom, frames, False, input)[0]))


def mgba_sound(rom: bytes, frames: int) -> list[tuple[int, int]]:
    """The samples mGBA mixes in ``frames`` frames, 32768 a second: (left, right) pairs of
    signed 16-bit values, before mGBA resamples them for playback."""
    data = _reference(rom, frames, True, None)[1][8:]  # mGBA's first 2 come before any
    values = struct.unpack(f"<{len(data) // 2}h", data)      # sound: its mixer starts late
    return list(zip(values[0::2], values[1::2], strict=True))
