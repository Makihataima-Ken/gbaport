"""Cartridge header (0x08000000-0x080000BF) parsing.

The Nintendo logo bytes (0x04-0x9F) are deliberately not checked, so the
repository never needs a copy of them.
"""

from dataclasses import dataclass

from gbaport.rom.image import ROM_BASE, RomError, RomImage

FIXED_BYTE_OFFSET = 0xB2
FIXED_BYTE_VALUE = 0x96


@dataclass(frozen=True)
class RomHeader:
    title: str
    game_code: str
    maker_code: str
    version: int
    entry_point: int | None  # target of the ARM branch at 0x08000000
    checksum: int
    checksum_ok: bool


def header_checksum(data: bytes) -> int:
    """Complement check over 0xA0-0xBC, computed the way the BIOS does."""
    total = 0
    for byte in data[0xA0:0xBD]:
        total -= byte
    return (total - 0x19) & 0xFF


def parse_header(rom: RomImage) -> RomHeader:
    data = rom.data
    if data[FIXED_BYTE_OFFSET] != FIXED_BYTE_VALUE:
        raise RomError(
            f"not a GBA ROM: header byte {FIXED_BYTE_OFFSET:#x} is "
            f"{data[FIXED_BYTE_OFFSET]:#04x}, expected {FIXED_BYTE_VALUE:#04x}"
        )
    return RomHeader(
        title=_ascii(data[0xA0:0xAC]),
        game_code=_ascii(data[0xAC:0xB0]),
        maker_code=_ascii(data[0xB0:0xB2]),
        version=data[0xBC],
        entry_point=_entry_point(rom.read32(ROM_BASE)),
        checksum=data[0xBD],
        checksum_ok=data[0xBD] == header_checksum(data),
    )


def _ascii(raw: bytes) -> str:
    # backslashreplace keeps stray bytes visible and printable on any console encoding
    return raw.rstrip(b"\0").decode("ascii", errors="backslashreplace")


def _entry_point(word: int) -> int | None:
    """Target of the unconditional ARM branch every cartridge starts with."""
    if word >> 24 != 0xEA:
        return None
    offset = word & 0xFFFFFF
    if offset & 0x800000:
        offset -= 0x1000000
    return (ROM_BASE + 8 + offset * 4) & 0xFFFFFFFF
