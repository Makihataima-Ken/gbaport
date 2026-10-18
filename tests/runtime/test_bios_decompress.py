import random

import biosref
from romtest import run_test


def _samples(rng: random.Random, count: int) -> list[bytes]:
    """Even-length data (multiples of 4) mixing runs, repeats and noise from few values."""
    samples = []
    for _ in range(count):
        alphabet = rng.sample(range(256), rng.randint(2, 20))
        data = bytearray()
        while len(data) < rng.randint(8, 1500):
            kind = rng.random()
            if kind < 0.3:
                data += bytes([rng.choice(alphabet)]) * rng.randint(3, 40)
            elif kind < 0.5 and len(data) > 8:
                start = rng.randrange(len(data) - 4)
                data += data[start : start + rng.randint(3, 18)]
            else:
                data.append(rng.choice(alphabet))
        samples.append(bytes(data[: len(data) - len(data) % 4]) or b"\x01\x02\x03\x04")
    return samples


def _cases(name: str, pairs: list[tuple[bytes, bytes]]) -> str:
    parts = []
    for i, (packed, plain) in enumerate(pairs):
        parts.append(biosref.c_bytes(f"{name}_packed_{i}", packed))
        parts.append(biosref.c_bytes(f"{name}_plain_{i}", plain))
    rows = ",\n".join(f"    {{{name}_packed_{i}, {name}_plain_{i}, {len(plain)}u}}" for i, (_, plain) in enumerate(pairs))
    parts.append(f"#define {name.upper()}_COUNT {len(pairs)}u\nstatic const Packed {name}_cases[] = {{\n{rows}\n}};\n")
    return "".join(parts)


def decompress_data() -> str:
    rng = random.Random(47)
    data = _samples(rng, 8)
    return "".join([
        "typedef struct { const uint8_t *packed; const uint8_t *plain; uint32_t size; } Packed;\n",
        _cases("lz", [(biosref.lz77_compress(d), d) for d in data]),
        _cases("rl", [(biosref.rl_compress(d), d) for d in data]),
        _cases("huff8", [(biosref.huffman_compress(d, 8), d) for d in data]),
        _cases("huff4", [(biosref.huffman_compress(d, 4), d) for d in data]),
        _cases("diff8", [(biosref.diff_filter(d, 1), d) for d in data]),
        _cases("diff16", [(biosref.diff_filter(d, 2), d) for d in data]),
    ])


def test_bios_decompressors_give_back_the_original():
    run_test("bios_decompress", data=decompress_data()).assert_passed()
