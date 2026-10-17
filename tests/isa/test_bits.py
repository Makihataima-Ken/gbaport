from gbaport.isa.bits import bit, field, ror32, sign_extend


def test_field_extracts_inclusive_range():
    assert field(0xE3A004FF, 31, 28) == 0xE
    assert field(0xE3A004FF, 11, 8) == 0x4


def test_bit():
    assert bit(0b1000, 3) is True
    assert bit(0b1000, 2) is False


def test_sign_extend():
    assert sign_extend(0xFFFFFC, 24) == -4
    assert sign_extend(0x7FFFFF, 24) == 0x7FFFFF
    assert sign_extend(0xEE, 8) == -18


def test_ror32():
    assert ror32(0xFF, 8) == 0xFF000000
    assert ror32(0x0F, 4) == 0xF0000000
    assert ror32(0x12345678, 0) == 0x12345678
