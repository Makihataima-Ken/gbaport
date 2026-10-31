"""runtime/decode.c decodes every instruction as the analysis does (isa/arm.py, isa/thumb.py)."""

import random
import subprocess

from hostkit import TESTS, host_program

import gbaport.native.build as native
from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Instruction
from gbaport.isa.thumb import decode_thumb


def _decoded(lines: list[str]) -> list[str]:
    program = host_program("decodehost", [TESTS / "decodehost.c", native.RUNTIME / "decode.c"],
                           [native.RUNTIME / "decode.h"])
    out = subprocess.run([str(program)], input="\n".join(lines) + "\n", capture_output=True,
                         text=True, timeout=120, check=True).stdout
    return out.splitlines()


def _fields(ins: Instruction) -> str:
    """The analysis's instruction as decodehost prints one."""
    def opt(v, fmt="{}"):
        return "-" if v is None else fmt.format(v)

    shift = "-" if ins.shift is None else \
        f"{ins.shift.kind.value}/{ins.shift.amount}/{opt(ins.shift.reg)}"
    regs = " ".join(opt(r) for r in (ins.rd, ins.rn, ins.rm, ins.rs, ins.rd_hi))
    mask = sum(1 << r for r in ins.reglist)
    return (f"{ins.op.value} {int(ins.cond)} {ins.size} {ins.raw:08x} {int(ins.s)} {regs} "
            f"{opt(None if ins.imm is None else ins.imm & 0xFFFFFFFF, '{:08x}')} "  # BL_HI: negative
            f"{opt(ins.target, '{:08x}')} {ins.imm_rot} {shift} "
            f"{int(ins.pre)} {int(ins.up)} {int(ins.writeback)} {int(ins.user)} {mask:04x} "
            f"{int(ins.spsr)} {ins.psr_mask}")


def _compare(lines: list[str], expected: list[str]) -> None:
    got = _decoded(lines)
    wrong = [f"{line}: {g} != {e}" for line, g, e in zip(lines, got, expected) if g != e]
    assert len(got) == len(expected)
    assert not wrong, f"{len(wrong)} differ:\n" + "\n".join(wrong[:10])


def _address(rng: random.Random, align: int) -> int:
    return rng.choice([0x08000000, 0x03000000, 0xFFFFFF00, rng.getrandbits(32)]) & ~(align - 1)


def test_every_thumb_halfword_decodes_as_the_analysis_decodes_it():
    rng = random.Random(1)
    lines, expected = [], []
    for hw in range(0x10000):
        addr = _address(rng, 2)
        nxt = rng.choice([None, rng.getrandbits(16), 0xF800 | rng.getrandbits(11)])
        lines.append(f"thumb {hw:x} {addr:x} {'-' if nxt is None else f'{nxt:x}'}")
        expected.append(_fields(decode_thumb(hw, addr, nxt)))
    _compare(lines, expected)


# Encodings random words rarely hit: (value, mask) of each special case's fixed bits.
ARM_PATTERNS = [
    (0x012FFF10, 0x0FFFFFF0), (0x00000090, 0x0FC000F0), (0x00800090, 0x0F8000F0),
    (0x01000090, 0x0FB00FF0), (0x00000090, 0x0E000090), (0x010F0000, 0x0FBF0FFF),
    (0x0120F000, 0x0FB0FFF0), (0x0320F000, 0x0FB0F000), (0x01000000, 0x0F900000),
    (0x0000F000, 0x0000F000), (0x000F0000, 0x000F0000),  # Rd or Rn = pc
]


def test_arm_words_decode_as_the_analysis_decodes_them():
    rng = random.Random(2)
    words = [rng.getrandbits(32) for _ in range(200_000)]
    for value, mask in ARM_PATTERNS:
        words += [(rng.getrandbits(32) & ~mask) | value for _ in range(10_000)]
    lines, expected = [], []
    for word in words:
        addr = _address(rng, 4)
        lines.append(f"arm {word:x} {addr:x}")
        expected.append(_fields(decode_arm(word, addr)))
    _compare(lines, expected)
