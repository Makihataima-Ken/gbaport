"""The buttons drawn on a phone's screen (runtime/touch.c), through tests/touchhost.c."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

import gbaport.native.build as native
from gbaport.native.toolchain import find_clang

HOST = Path(__file__).parent.parent / "touchhost.c"
SOURCES = (HOST, native.RUNTIME / "touch.c", native.RUNTIME / "touch.h")
PHONE = "layout 2400 1080 0 0 2400 1080"  # a 20:9 phone held sideways, no notch


def _program() -> Path:
    """touchhost, built once per version of its sources (rebuilt with a salt when Windows'
    Smart App Control refuses to start it, as gbaport build does)."""
    digest = hashlib.sha1(b"".join(path.read_bytes() for path in SOURCES)).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / "gbaport-touchhost" / digest
    program = folder / ("touchhost.exe" if os.name == "nt" else "touchhost")
    if program.exists():
        return program
    folder.mkdir(parents=True, exist_ok=True)
    salt = folder / "salt.c"
    for _ in range(native.SALTED_REBUILDS):
        salt.write_text(f'const char touchhost_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        subprocess.run(
            [find_clang(), "-std=c11", "-O2", "-Wall", "-Werror", f"-I{native.RUNTIME}", str(HOST),
             str(native.RUNTIME / "touch.c"), str(salt), "-o", str(program)],
            check=True, capture_output=True,
        )
        if native._starts(program):
            return program
    raise AssertionError("Windows refused to start touchhost")


def touch(*commands: str) -> list[str]:
    result = subprocess.run([str(_program())], input="\n".join(commands) + "\n",
                            capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.splitlines()


def layout(command: str = PHONE) -> dict[str, list[float]]:
    return {line.split()[0]: [float(v) for v in line.split()[1:]] for line in touch(command)}


def centre(box: list[float]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2, y + h / 2


def test_the_picture_fills_the_screens_height_in_the_middle():
    assert layout()["screen"] == [390.0, 0.0, 1620.0, 1080.0]


def test_the_buttons_are_inside_the_safe_area():
    boxes = layout("layout 2400 1080 100 40 2200 1000")  # a notch on each side, bars above and below
    for name in ("A", "B", "SELECT", "START", "R", "L"):
        x, y, w, h = boxes[name]
        assert 100 <= x and x + w <= 2300 and 40 <= y and y + h <= 1040, name
    pad_x, pad_y, radius = boxes["pad"]
    assert 100 <= pad_x - radius and pad_y + radius <= 1040
    assert boxes["screen"] == [390.0, 0.0, 1620.0, 1080.0]  # the picture still fills the height


def test_a_finger_on_a_button_holds_its_key_until_it_comes_up():
    ax, ay = centre(layout()["A"])
    assert touch(PHONE, f"down 1 {ax} {ay}", "keys", "up 1", "keys")[-2:] == ["A", "none"]


@pytest.mark.parametrize("dx, dy, keys", [
    (1, 0, "RIGHT"), (-1, 0, "LEFT"), (0, -1, "UP"), (0, 1, "DOWN"),
    (0.7, -0.7, "RIGHT+UP"), (-0.7, 0.7, "LEFT+DOWN"), (0.05, 0.05, "none"),
])
def test_the_d_pad_points_where_the_finger_is(dx, dy, keys):
    x, y, radius = layout()["pad"]
    finger = f"down 7 {x + dx * 0.8 * radius} {y + dy * 0.8 * radius}"
    assert touch(PHONE, finger, "keys")[-1] == keys


def test_a_finger_that_came_down_on_the_d_pad_keeps_steering_it_beyond_its_edge():
    x, y, radius = layout()["pad"]
    out = touch(PHONE, f"down 1 {x} {y - 0.5 * radius}", f"move 1 {x + 3 * radius} {y}", "keys")
    assert out[-1] == "RIGHT"


def test_a_finger_that_came_down_elsewhere_does_not_steer_the_d_pad():
    boxes = layout()
    x, y, radius = boxes["pad"]
    sx, sy = centre(boxes["START"])
    assert touch(PHONE, f"down 1 {sx} {sy}", f"move 1 {x + 0.8 * radius} {y}", "keys")[-1] == "none"


def test_a_finger_between_a_and_b_holds_both():
    (ax, ay), (bx, by) = centre(layout()["A"]), centre(layout()["B"])
    assert touch(PHONE, f"down 1 {(ax + bx) / 2} {(ay + by) / 2}", "keys")[-1] == "A+B"


def test_a_finger_sliding_from_b_to_a_moves_the_press():
    (ax, ay), (bx, by) = centre(layout()["A"]), centre(layout()["B"])
    assert touch(PHONE, f"down 1 {bx} {by}", f"move 1 {ax} {ay}", "keys")[-1] == "A"


def test_fingers_add_up():
    boxes = layout()
    x, y, radius = boxes["pad"]
    lx, ly = centre(boxes["L"])
    ax, ay = centre(boxes["A"])
    out = touch(PHONE, f"down 1 {x + 0.8 * radius} {y}", f"down 2 {lx} {ly}", f"down 3 {ax} {ay}",
                "keys", "up 2", "keys")
    assert out[-2:] == ["A+RIGHT+L", "A+RIGHT"]


def test_an_eleventh_finger_holds_nothing_and_its_coming_up_changes_nothing():
    boxes = layout()
    ax, ay = centre(boxes["A"])
    sx, sy = centre(boxes["START"])
    resting = [f"down {i} 1200 540" for i in range(10)]  # ten fingers on the picture
    out = touch(PHONE, *resting, f"down 10 {sx} {sy}", "keys", "up 10", "up 3",
                f"down 11 {ax} {ay}", "keys")
    assert out[-2:] == ["none", "A"]
