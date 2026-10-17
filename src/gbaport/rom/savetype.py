"""Save-hardware detection from the library ID strings Nintendo's SDK embeds.

Every commercial game links one save library whose ID string (for example
``FLASH1M_V103``) sits in ROM. EEPROM size (512 B vs 8 KiB) cannot be told from
the string; the runtime infers it from the DMA transfer length.
"""

import re
from dataclasses import dataclass
from enum import Enum

from gbaport.rom.image import RomImage


class SaveType(Enum):
    NONE = "none"
    EEPROM = "eeprom"
    SRAM = "sram"
    FLASH64K = "flash64k"
    FLASH128K = "flash128k"


_MARKER = re.compile(rb"(EEPROM_V|SRAM_F_V|SRAM_V|FLASH1M_V|FLASH512_V|FLASH_V)\d{3}")
_TYPES = {
    b"EEPROM_V": SaveType.EEPROM,
    b"SRAM_V": SaveType.SRAM,
    b"SRAM_F_V": SaveType.SRAM,
    b"FLASH_V": SaveType.FLASH64K,
    b"FLASH512_V": SaveType.FLASH64K,
    b"FLASH1M_V": SaveType.FLASH128K,
}


@dataclass(frozen=True)
class SaveDetection:
    save_type: SaveType
    markers: tuple[str, ...]  # every library ID found, in ROM order


def detect_save_type(rom: RomImage) -> SaveDetection:
    matches = list(_MARKER.finditer(rom.data))
    if not matches:
        return SaveDetection(SaveType.NONE, ())
    markers = tuple(m.group(0).decode("ascii") for m in matches)
    return SaveDetection(_TYPES[matches[0].group(1)], markers)
