"""Read-only view of a cartridge ROM mapped at its GBA bus address."""

from dataclasses import dataclass, field
from pathlib import Path

ROM_BASE = 0x08000000
HEADER_SIZE = 0xC0
MAX_ROM_SIZE = 32 * 1024 * 1024


class RomError(ValueError):
    """The file is not a usable GBA ROM, or an access fell outside it."""


@dataclass(frozen=True)
class RomImage:
    data: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self.data) < HEADER_SIZE:
            raise RomError(f"ROM too small: {len(self.data)} bytes, header needs {HEADER_SIZE}")
        if len(self.data) > MAX_ROM_SIZE:
            raise RomError(f"ROM too large: {len(self.data)} bytes, GBA maximum is {MAX_ROM_SIZE}")

    @classmethod
    def load(cls, path: str | Path) -> "RomImage":
        return cls(Path(path).read_bytes())

    def contains(self, addr: int, size: int = 1) -> bool:
        offset = addr - ROM_BASE
        return offset >= 0 and offset + size <= len(self.data)

    def read(self, addr: int, size: int) -> bytes:
        if not self.contains(addr, size):
            raise RomError(f"read of {size} bytes at {addr:#010x} is outside ROM")
        offset = addr - ROM_BASE
        return self.data[offset:offset + size]

    def read8(self, addr: int) -> int:
        return self.read(addr, 1)[0]

    def read16(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 2), "little")

    def read32(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 4), "little")
