import random

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.thumb import decode_thumb

BASE = 0x08000000


def test_arm_text():
    assert format_instruction(decode_arm(0xE0810182, BASE)) == "add r0, r1, r2, lsl #3"
    assert format_instruction(decode_arm(0x00910002, BASE)) == "addseq r0, r1, r2"
    assert format_instruction(decode_arm(0xE8BD80F0, BASE)) == "ldmia sp!, {r4, r5, r6, r7, pc}"
    assert format_instruction(decode_arm(0xEB00003E, BASE)) == "bl #0x8000100"
    assert format_instruction(decode_arm(0xE5310004, BASE)) == "ldr r0, [r1, #-4]!"
    # W bit still shown when the loaded base makes the writeback ineffective
    assert format_instruction(decode_arm(0xE8B00003, BASE)) == "ldmia r0!, {r0, r1}"


def test_thumb_text():
    assert format_instruction(decode_thumb(0x0088, BASE)) == "lsls r0, r1, #2"
    assert format_instruction(decode_thumb(0x4248, BASE)) == "rsbs r0, r1, #0"
    assert format_instruction(decode_thumb(0xB510, BASE)) == "push {r4, lr}"
    assert format_instruction(decode_thumb(0xF000, BASE, 0xF87E)) == "bl #0x8000100"


def test_undefined_prints_as_data():
    assert format_instruction(decode_arm(0xF0000000, BASE)) == ".word 0xf0000000"
    assert format_instruction(decode_thumb(0xDE00, BASE)) == ".hword 0xde00"


def test_lone_bl_half_prints_as_annotated_data():
    assert format_instruction(decode_thumb(0xF000, BASE)).startswith(".hword 0xf000  @ bl_hi")


def test_every_thumb_halfword_formats():
    for hw in range(0x10000):
        assert format_instruction(decode_thumb(hw, BASE))


def test_random_arm_words_format():
    rng = random.Random(0x6BA)
    for _ in range(100_000):
        assert format_instruction(decode_arm(rng.getrandbits(32), BASE))
