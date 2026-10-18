import random

import biosref
from romtest import run_test

HEADER = """
typedef struct { uint16_t length; uint8_t src_width, dst_width; uint32_t offset; } UnpackInfo;
typedef struct { const uint8_t *data; UnpackInfo info; uint32_t count; uint32_t words[64]; } UnpackCase;
typedef struct {
    struct { int32_t ox, oy; int16_t cx, cy, sx, sy; uint16_t angle, pad; } source;
    int16_t want_matrix[4];
    int32_t want_x, want_y;
} BgCase;
"""


def copy_data() -> str:
    rng = random.Random(43)
    parts, unpacks = [HEADER], []
    for i in range(40):
        src_width = rng.choice([1, 2, 4, 8])
        dst_width = rng.choice([w for w in (1, 2, 4, 8, 16, 32) if w >= src_width])
        length = min(rng.choice([4, 8, 16, 32]), 256 * src_width // dst_width)  # <= 64 words out
        data = bytes(rng.randrange(256) for _ in range(length))
        offset = rng.choice([0, 1, rng.randrange(1 << 20)])
        zero_too = rng.random() < 0.5
        words = biosref.bit_unpack(data, src_width, dst_width, offset, zero_too)
        parts.append(biosref.c_bytes(f"unpack_data_{i}", data))
        info = f"{{{length}, {src_width}, {dst_width}, 0x{offset | (zero_too << 31):08x}u}}"
        body = ", ".join(f"0x{w:08x}u" for w in words) or "0"
        unpacks.append(f"    {{unpack_data_{i}, {info}, {len(words)}u, {{{body}}}}},")
    parts.append(f"#define UNPACK_COUNT {len(unpacks)}u\nstatic const UnpackCase unpack_cases[] = {{\n")
    parts.append("\n".join(unpacks) + "\n};\n")

    objs = [(0x100, 0x100, 0), (0x100, 0x100, 0x4000), (0x80, 0x200, 0x2000)]
    objs += [(biosref.s16(rng.randrange(0x10000)), biosref.s16(rng.randrange(0x10000)), rng.randrange(0x10000))
             for _ in range(60)]
    rows = []
    for sx, sy, angle in objs:
        want = [biosref.s16(v) for v in biosref.obj_affine(sx, sy, angle)]
        rows.append("    {" + ", ".join(str(v) for v in (sx, sy, biosref.s16(angle), *want)) + "},")
    parts.append(f"#define OBJ_COUNT {len(rows)}u\nstatic const int16_t obj_cases[][7] = {{\n")
    parts.append("\n".join(rows) + "\n};\n")

    bgs = []
    for _ in range(60):
        ox, oy = rng.randrange(-(1 << 20), 1 << 20), rng.randrange(-(1 << 20), 1 << 20)
        cx, cy = rng.randrange(-240, 240), rng.randrange(-160, 160)
        sx, sy = rng.randrange(-0x400, 0x400), rng.randrange(-0x400, 0x400)
        angle = rng.randrange(0x10000)
        pa, pb, pc, pd, x, y = biosref.bg_affine(ox, oy, cx, cy, sx, sy, angle)
        matrix = ", ".join(str(biosref.s16(v)) for v in (pa, pb, pc, pd))
        bgs.append(f"    {{{{{ox}, {oy}, {cx}, {cy}, {sx}, {sy}, 0x{angle:04x}, 0}}, {{{matrix}}}, "
                   f"{biosref.s32(x)}, {biosref.s32(y)}}},")
    parts.append(f"#define BG_COUNT {len(bgs)}u\nstatic const BgCase bg_cases[] = {{\n")
    parts.append("\n".join(bgs) + "\n};\n")
    return "".join(parts)


def test_bios_memory_calls():
    run_test("bios_copy", data=copy_data()).assert_passed()
