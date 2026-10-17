"""One-call summary of a ROM: header, size, hash and save hardware."""

import hashlib
from dataclasses import dataclass

from gbaport.rom.header import RomHeader, parse_header
from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveDetection, detect_save_type


@dataclass(frozen=True)
class RomInfo:
    header: RomHeader
    size: int
    sha1: str
    save: SaveDetection

    def to_dict(self) -> dict:
        header = self.header
        return {
            "title": header.title,
            "game_code": header.game_code,
            "maker_code": header.maker_code,
            "version": header.version,
            "entry_point": None if header.entry_point is None else f"{header.entry_point:#010x}",
            "checksum_ok": header.checksum_ok,
            "size": self.size,
            "sha1": self.sha1,
            "save_type": self.save.save_type.value,
            "save_markers": list(self.save.markers),
        }


def inspect_rom(rom: RomImage) -> RomInfo:
    return RomInfo(
        header=parse_header(rom),
        size=len(rom.data),
        sha1=hashlib.sha1(rom.data).hexdigest(),
        save=detect_save_type(rom),
    )
