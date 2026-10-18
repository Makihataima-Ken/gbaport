import random

import biosref
from romtest import run_test

EDGES = [0, 1, -1, 2, -2, 7, -7, 10, -1234, 0x7FFFFFFF, -0x80000000, 0x10000, -0x10000]


def _table(name: str, rows: list[tuple[int, ...]]) -> str:
    width = len(rows[0])
    body = ",\n".join("    {" + ", ".join(f"0x{biosref.u32(v):08x}u" for v in row) + "}" for row in rows)
    return (
        f"#define {name.upper()}_COUNT {len(rows)}u\n"
        f"static const uint32_t {name}_cases[][{width}] = {{\n{body}\n}};\n"
    )


def math_data() -> str:
    rng = random.Random(41)
    pairs = [(n, d) for n in EDGES for d in EDGES if d]
    pairs += [(rng.getrandbits(32), rng.choice([rng.getrandbits(32), rng.randint(1, 100)])) for _ in range(300)]
    pairs += [(5, 0), (-5, 0)]  # division by zero: mGBA's answer, and a warning
    divs = [(n, d, *biosref.div(n, d)) for n, d in pairs]
    roots = [(v, biosref.sqrt(v)) for v in [0, 1, 2, 3, 4, 0xFFFFFFFF, 0xFFFE0001, *(rng.getrandbits(32) for _ in range(200))]]
    tans = [t for t in range(-0x4000, 0x4001, 0x100)] + [rng.randint(-0x4000, 0x4000) for _ in range(100)]
    arctans = [(t, *biosref.arctan(t)) for t in tans]
    points = [(5, 0), (-5, 0), (0, 5), (0, -5), (0x1000, 0x1000), (-0x1000, 0x1000), (-0x1000, -0x1000)]
    points += [(rng.randint(-0x7FFF, 0x7FFF), rng.randint(-0x7FFF, 0x7FFF)) for _ in range(300)]
    arctan2s = [(x, y, biosref.arctan2(x, y)) for x, y in points]
    midis = [(f, k, p, biosref.midi_key_to_freq(f, k, p)) for f, k, p in
             [(rng.randint(0x1000, 0xFFFFFF), rng.randint(0, 127), rng.randint(0, 255)) for _ in range(100)]]
    return "".join(_table(name, rows) for name, rows in [
        ("div", divs), ("sqrt", roots), ("arctan", arctans), ("arctan2", arctan2s), ("midi", midis),
    ])


def test_bios_arithmetic_matches_the_reference():
    run = run_test("bios_math", data=math_data())
    run.assert_passed()
    assert "Div of 5 by zero" in run.stderr
