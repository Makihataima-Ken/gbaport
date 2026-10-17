"""The address space the analyser may decode: ROM, its mirrors, and RAM copies of ROM blobs."""

from gbaport.analysis.config import ConfigError, RamCode
from gbaport.rom.image import ROM_BASE, RomError, RomImage

ROM_MIRROR_END = 0x0E000000  # 0x08, 0x0A and 0x0C regions all show the cartridge


class CodeSpace:
    def __init__(self, rom: RomImage, ram_code: tuple[RamCode, ...] = ()) -> None:
        self.rom = rom
        self.overlays = tuple(sorted(ram_code, key=lambda blob: blob.ram))
        for blob in self.overlays:
            if not rom.contains(blob.rom, blob.size):
                raise ConfigError(f"ram_code blob {blob.rom:#x}+{blob.size:#x} is outside the ROM")
            if ROM_BASE <= blob.ram < ROM_MIRROR_END:
                raise ConfigError(f"ram_code target {blob.ram:#x} is inside cartridge space")
        for first, second in zip(self.overlays, self.overlays[1:]):
            if first.ram + first.size > second.ram:
                raise ConfigError(
                    f"ram_code blobs at {first.ram:#x} and {second.ram:#x} overlap"
                )

    def canonical(self, addr: int) -> int:
        """Fold the ROM wait-state mirrors onto 0x08000000."""
        if ROM_BASE <= addr < ROM_MIRROR_END:
            return ROM_BASE + (addr & 0x01FFFFFF)
        return addr

    def rom_offset(self, addr: int, size: int = 1) -> int | None:
        """Offset into the ROM file of the ``size`` bytes at ``addr``, or None."""
        addr = self.canonical(addr)
        if self.rom.contains(addr, size):
            return addr - ROM_BASE
        for blob in self.overlays:
            if blob.ram <= addr and addr + size <= blob.ram + blob.size:
                return blob.rom - ROM_BASE + (addr - blob.ram)
        return None

    def contains(self, addr: int, size: int = 1) -> bool:
        return self.rom_offset(addr, size) is not None

    def read16(self, addr: int) -> int:
        offset = self._offset(addr, 2)
        return int.from_bytes(self.rom.data[offset:offset + 2], "little")

    def read32(self, addr: int) -> int:
        offset = self._offset(addr, 4)
        return int.from_bytes(self.rom.data[offset:offset + 4], "little")

    def _offset(self, addr: int, size: int) -> int:
        offset = self.rom_offset(addr, size)
        if offset is None:
            raise RomError(f"{addr:#010x} is outside analysable code")
        return offset
