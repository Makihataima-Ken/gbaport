"""Reference implementations of the GBA BIOS functions, and the compressors that feed them.

Written from GBATEK's descriptions (and mGBA's HLE BIOS where GBATEK leaves a corner
open, such as division by zero), independently of the C runtime, so the runtime tests
can compare against them. Values are plain Python ints; ``u32``/``s32`` wrap them to the
ARM's 32-bit registers.

The compressors produce valid BIOS streams (not the smallest ones): LZ77 never refers to
the byte just written (the VRAM decompressor cannot), RL emits runs of 3-130 bytes, and
Huffman keeps trees small enough for the 6-bit child offsets.
"""

import heapq
import math
import struct


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def s32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - (1 << 16) if value & 0x8000 else value


def _trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


# ---- arithmetic ---------------------------------------------------------------------


def div(num: int, den: int) -> tuple[int, int, int]:
    """SWI 0x06: (r0, r1, r3) = (num / den, num % den, |num / den|), C-style truncation.
    Division by zero returns (sign, num, 1) as mGBA does (the BIOS would hang)."""
    num, den = s32(num), s32(den)
    if den == 0:
        return u32(-1 if num < 0 else 1), u32(num), 1
    if den == -1 and num == -(1 << 31):
        return 0x80000000, 0, 0x80000000
    quot = _trunc_div(num, den)
    return u32(quot), u32(num - quot * den), u32(abs(quot))


def sqrt(value: int) -> int:
    """SWI 0x08: the integer square root of an unsigned 32-bit value."""
    return math.isqrt(u32(value))


def arctan(tan: int) -> tuple[int, int, int]:
    """SWI 0x09: (r0, r1, r3) of the BIOS's polynomial, for a 1.14 fixed-point tangent."""
    i = s32(tan)
    a = s32(-(s32(i * i) >> 14))
    b = s32((s32(0xA9 * a) >> 14) + 0x390)
    for constant in (0x91C, 0xFB6, 0x16AA, 0x2081, 0x3651, 0xA2F9):
        b = s32((s32(b * a) >> 14) + constant)
    return u32(s32(i * b) >> 16), u32(a), u32(b)


def arctan2(x: int, y: int) -> int:
    """SWI 0x0A: the angle of (x, y), 0x0000-0xFFFF for 0 <= theta < 2 pi."""
    x, y = s32(x), s32(y)
    if y == 0:
        return 0 if x >= 0 else 0x8000
    if x == 0:
        return 0x4000 if y >= 0 else 0xC000

    def tan(n: int, d: int) -> int:
        return s32(arctan(_trunc_div(n << 14, d))[0])

    if y >= 0:
        if x >= 0:
            if x >= y:
                return tan(y, x) & 0xFFFF
        elif -x >= y:
            return (tan(y, x) + 0x8000) & 0xFFFF
        return (0x4000 - tan(x, y)) & 0xFFFF
    if x <= 0:
        if -x > -y:
            return (tan(y, x) + 0x8000) & 0xFFFF
    elif x >= -y:
        return (tan(y, x) + 0x10000) & 0xFFFF
    return (0xC000 - tan(x, y)) & 0xFFFF


def midi_key_to_freq(freq: int, key: int, fine: int) -> int:
    """SWI 0x1F: freq / 2^((180 - key - fine/256) / 12), truncated."""
    return u32(int(freq / 2 ** ((180 - (key & 0xFF) - (fine & 0xFF) / 256) / 12)))


# ---- memory -------------------------------------------------------------------------


def bit_unpack(data: bytes, src_width: int, dst_width: int, offset: int, zero_too: bool) -> list[int]:
    """SWI 0x10: the 32-bit words BitUnPack writes. Units come from each byte's low bits
    first; non-zero units (all units, with ``zero_too``) get ``offset`` added; results are
    not masked to the destination width."""
    words, out, used = [], 0, 0
    for byte in data:
        for shift in range(0, 8, src_width):
            unit = (byte >> shift) & ((1 << src_width) - 1)
            if unit or zero_too:
                unit += offset
            out |= unit << used
            used += dst_width
            if used == 32:
                words.append(u32(out))
                out, used = 0, 0
    return words


SINE = [round(16384 * math.sin(2 * math.pi * i / 256)) for i in range(256)]  # 1.14 fixed point


def _rotation(sx: int, sy: int, angle: int) -> tuple[int, int, int, int]:
    theta = (angle & 0xFFFF) >> 8
    sin, cos = SINE[theta], SINE[(theta + 64) & 0xFF]
    return (sx * cos) >> 14, (sx * -sin) >> 14, (sy * sin) >> 14, (sy * cos) >> 14


def obj_affine(sx: int, sy: int, angle: int) -> tuple[int, int, int, int]:
    """SWI 0x0F: (pa, pb, pc, pd) for 8.8 scales sx, sy and an angle (upper 8 bits used)."""
    return tuple(v & 0xFFFF for v in _rotation(s16(sx), s16(sy), angle))


def bg_affine(ox: int, oy: int, cx: int, cy: int, sx: int, sy: int, angle: int) -> tuple[int, ...]:
    """SWI 0x0E: (pa, pb, pc, pd, x, y): the matrix, and the start point that puts the
    texture point (ox, oy) (24.8 fixed point) at the screen point (cx, cy)."""
    pa, pb, pc, pd = _rotation(s16(sx), s16(sy), angle)
    x = s32(ox) - (pa * s16(cx) + pb * s16(cy))
    y = s32(oy) - (pc * s16(cx) + pd * s16(cy))
    return pa & 0xFFFF, pb & 0xFFFF, pc & 0xFFFF, pd & 0xFFFF, u32(x), u32(y)


# ---- compression --------------------------------------------------------------------


def _header(kind: int, size: int, low: int = 0) -> bytes:
    return struct.pack("<I", (size << 8) | (kind << 4) | low)


def _pad(data: bytes) -> bytes:
    return data + bytes(-len(data) % 4)


def lz77_compress(data: bytes) -> bytes:
    """A valid LZ77 stream (type 1) for both the WRAM and the VRAM decompressor."""
    out, i = bytearray(_header(1, len(data))), 0
    while i < len(data):
        flags_at, flags = len(out), 0
        out.append(0)
        for bit in range(8):
            if i >= len(data):
                break
            best_len, best_dist = 0, 0
            for dist in range(2, min(i, 0x1000) + 1):  # distance 1 would read an unwritten byte
                length = 0
                while length < 18 and i + length < len(data) and data[i + length - dist] == data[i + length]:
                    length += 1
                if length > best_len:
                    best_len, best_dist = length, dist
            if best_len >= 3:
                flags |= 0x80 >> bit
                out += bytes([((best_len - 3) << 4) | ((best_dist - 1) >> 8), (best_dist - 1) & 0xFF])
                i += best_len
            else:
                out.append(data[i])
                i += 1
        out[flags_at] = flags
    return _pad(bytes(out))


def lz77_decompress(stream: bytes) -> bytes:
    size = struct.unpack_from("<I", stream)[0] >> 8
    out, i = bytearray(), 4
    while len(out) < size:
        flags = stream[i]
        i += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                length = (stream[i] >> 4) + 3
                dist = (((stream[i] & 0xF) << 8) | stream[i + 1]) + 1
                i += 2
                for _ in range(length):
                    out.append(out[-dist])
            else:
                out.append(stream[i])
                i += 1
    return bytes(out[:size])


def rl_compress(data: bytes) -> bytes:
    """A run-length stream (type 3): runs of 3-130 equal bytes, literals of 1-128 bytes."""
    out, i, literal = bytearray(_header(3, len(data))), 0, bytearray()

    def flush() -> None:
        while literal:
            chunk = literal[:128]
            out.append(len(chunk) - 1)
            out.extend(chunk)
            del literal[:128]

    while i < len(data):
        run = 1
        while run < 130 and i + run < len(data) and data[i + run] == data[i]:
            run += 1
        if run >= 3:
            flush()
            out += bytes([0x80 | (run - 3), data[i]])
            i += run
        else:
            literal.append(data[i])
            i += 1
    flush()
    return _pad(bytes(out))


def rl_decompress(stream: bytes) -> bytes:
    size = struct.unpack_from("<I", stream)[0] >> 8
    out, i = bytearray(), 4
    while len(out) < size:
        flag = stream[i]
        i += 1
        if flag & 0x80:
            out += bytes([stream[i]]) * ((flag & 0x7F) + 3)
            i += 1
        else:
            out += stream[i : i + flag + 1]
            i += flag + 1
    return bytes(out[:size])


def diff_filter(data: bytes, unit: int) -> bytes:
    """A differencing stream (type 8) of 1- or 2-byte units."""
    values = list(data) if unit == 1 else list(struct.unpack(f"<{len(data) // 2}H", data))
    mask = 0xFF if unit == 1 else 0xFFFF
    deltas = [values[0]] + [(values[k] - values[k - 1]) & mask for k in range(1, len(values))]
    body = bytes(deltas) if unit == 1 else struct.pack(f"<{len(deltas)}H", *deltas)
    return _pad(_header(8, len(data), unit) + body)


def _units(data: bytes, bits: int) -> list[int]:
    if bits == 8:
        return list(data)
    return [nibble for byte in data for nibble in (byte & 0xF, byte >> 4)]  # low nibble first


def huffman_compress(data: bytes, bits: int) -> bytes:
    """A Huffman stream (type 2) for 4- or 8-bit units. ``data`` should use few distinct
    units (at most about 40), so every child offset fits in 6 bits."""
    units = _units(data, bits)
    counts: dict[int, int] = {}
    for unit in units:
        counts[unit] = counts.get(unit, 0) + 1
    if len(counts) == 1:  # a tree needs two leaves
        counts[(units[0] + 1) % (1 << bits)] = 0
    heap = [(count, n, ("leaf", unit)) for n, (unit, count) in enumerate(sorted(counts.items()))]
    heapq.heapify(heap)
    n = len(heap)
    while len(heap) > 1:
        a, b = heapq.heappop(heap), heapq.heappop(heap)
        heapq.heappush(heap, (a[0] + b[0], n, ("node", a[2], b[2])))
        n += 1
    root = heap[0][2]

    table = [0, 0]  # [tree size byte, root node]
    codes: dict[int, str] = {}
    queue = [(root, 1, "")]  # (node, index in table, code so far): breadth first
    while queue:
        node, index, code = queue.pop(0)
        if node[0] == "leaf":
            table[index] = node[1]
            codes[node[1]] = code
            continue
        pair = len(table)
        table += [0, 0]
        offset = (pair - (index & ~1) - 2) // 2
        assert 0 <= offset <= 63, "tree too large for the 6-bit child offsets"
        table[index] = offset | (0x80 if node[1][0] == "leaf" else 0) | (0x40 if node[2][0] == "leaf" else 0)
        queue += [(node[1], pair, code + "0"), (node[2], pair + 1, code + "1")]
    table += [0] * (-len(table) % 4)
    table[0] = len(table) // 2 - 1
    bitstring = "".join(codes[unit] for unit in units)
    bitstring += "0" * (-len(bitstring) % 32)
    words = [int(bitstring[k : k + 32], 2) for k in range(0, len(bitstring), 32)]
    return _header(2, len(data), bits) + bytes(table) + struct.pack(f"<{len(words)}I", *words)


def huffman_decompress(stream: bytes) -> bytes:
    header = struct.unpack_from("<I", stream)[0]
    bits, size = header & 0xF, header >> 8
    tree = 4 + 1  # the root node
    stream_at = 4 + (stream[4] + 1) * 2
    units: list[int] = []
    node, word_at = tree, stream_at
    while len(units) * bits < size * 8:
        word = struct.unpack_from("<I", stream, word_at)[0]
        word_at += 4
        for k in range(31, -1, -1):
            bit = (word >> k) & 1
            value = stream[node]
            child = (node & ~1) + (value & 0x3F) * 2 + 2 + bit
            if value & (0x80 >> bit):
                units.append(stream[child])
                node = tree
                if len(units) * bits >= size * 8:
                    break
            else:
                node = child
    if bits == 8:
        return bytes(units[:size])
    return bytes(units[k] | (units[k + 1] << 4) for k in range(0, size * 2, 2))


def c_bytes(name: str, data: bytes) -> str:
    """A C array definition for test data headers, 4-byte aligned."""
    body = ", ".join(f"0x{b:02x}" for b in data)
    return f"static const uint8_t {name}[{max(len(data), 1)}] __attribute__((aligned(4))) = {{{body}}};\n"
