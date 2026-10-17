"""Synthetic GBA ROM images for tests.

Deliberately independent of gbaport's own code so it can act as an oracle.
The Nintendo logo area (0x04-0x9F) is left zeroed: the repo never contains it.
"""

ROM_BASE = 0x08000000


def build_rom(
    code: bytes = b"",
    *,
    code_offset: int = 0xC0,
    title: bytes = b"TESTGAME",
    game_code: bytes = b"ATST",
    maker: bytes = b"01",
    version: int = 0,
    size: int = 0x400,
    patches: dict[int, bytes] | None = None,
    fix_checksum: bool = True,
) -> bytes:
    """Build a ROM whose entry branch jumps to ``code`` placed at ``code_offset``.

    ``patches`` (file offset -> bytes) are applied before the header checksum is
    computed, so header patches still get a valid checksum unless
    ``fix_checksum`` is False.
    """
    assert code_offset + len(code) <= size, "code does not fit in the ROM"
    rom = bytearray(size)
    branch = ((code_offset - 8) >> 2) & 0xFFFFFF
    rom[0:4] = (0xEA000000 | branch).to_bytes(4, "little")
    rom[0xA0:0xAC] = title.ljust(12, b"\0")
    rom[0xAC:0xB0] = game_code
    rom[0xB0:0xB2] = maker
    rom[0xB2] = 0x96
    rom[0xBC] = version
    rom[code_offset:code_offset + len(code)] = code
    for offset, blob in (patches or {}).items():
        rom[offset:offset + len(blob)] = blob
    if fix_checksum:
        total = 0
        for byte in rom[0xA0:0xBD]:
            total -= byte
        rom[0xBD] = (total - 0x19) & 0xFF
    return bytes(rom)
