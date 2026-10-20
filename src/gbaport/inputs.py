"""Input files: the keys a game is played with, frame by frame.

An input file is text with one change of the keys held per line, so the same play can be
replayed by mGBA and by the native build::

    # comments and blank lines are ignored
    900 A
    906 none
    3900 RIGHT+A

``FRAME KEYS`` holds KEYS from the FRAME-th VBlank on, until the next line: names joined
with ``+`` (A, B, SELECT, START, RIGHT, LEFT, UP, DOWN, R, L) or ``none``. Frames never
go down. The hosts' ``--press FRAME:KEYS`` options mean the same.
"""

from dataclasses import dataclass
from pathlib import Path

KEY_NAMES = ("A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L")


class InputError(ValueError):
    """An input file that is not one."""


@dataclass(frozen=True)
class Press:
    frame: int
    keys: int  # KEYINPUT bits that are held (1 = pressed)

    def names(self) -> str:
        held = [name for bit, name in enumerate(KEY_NAMES) if self.keys >> bit & 1]
        return "+".join(held) or "none"


def keys_from_names(text: str) -> int:
    """``A+START`` -> the KEYINPUT bits; ``none`` -> 0. Raises ``ValueError``."""
    if text == "none":
        return 0
    keys = 0
    for name in text.split("+"):
        if name not in KEY_NAMES:
            raise ValueError(f"unknown key {name!r} (keys: {', '.join(KEY_NAMES)}, or none)")
        keys |= 1 << KEY_NAMES.index(name)
    return keys


def parse_input(text: str, source: str = "input") -> list[Press]:
    presses: list[Press] = []
    for number, line in enumerate(text.removeprefix("\ufeff").splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) != 2 or not (fields[0].isascii() and fields[0].isdigit()):
            raise InputError(f"{source}, line {number}: expected 'FRAME KEYS', got {line!r}")
        try:
            keys = keys_from_names(fields[1])
        except ValueError as error:
            raise InputError(f"{source}, line {number}: {error}") from None
        frame = int(fields[0])
        if presses and frame < presses[-1].frame:
            raise InputError(f"{source}, line {number}: frame {frame} comes before frame "
                             f"{presses[-1].frame}")
        presses.append(Press(frame, keys))
    return presses


def format_input(presses: list[Press]) -> str:
    return "".join(f"{press.frame} {press.names()}\n" for press in presses)


def load_input(path: str | Path) -> list[Press]:
    return parse_input(Path(path).read_text(encoding="utf-8"), str(path))
