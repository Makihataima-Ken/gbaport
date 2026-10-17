"""Bit-twiddling helpers shared by the decoders."""


def field(word: int, hi: int, lo: int) -> int:
    """Return bits ``hi..lo`` (inclusive) of ``word``."""
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


def bit(word: int, n: int) -> bool:
    return bool((word >> n) & 1)


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def ror32(value: int, amount: int) -> int:
    amount &= 31
    return ((value >> amount) | (value << (32 - amount))) & 0xFFFFFFFF
