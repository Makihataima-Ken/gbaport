import pytest
from romkit import build_rom

from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveType, detect_save_type


def rom_with(*blobs: bytes) -> RomImage:
    patches = {0x200 + 0x40 * i: blob for i, blob in enumerate(blobs)}
    return RomImage(build_rom(size=0x400, patches=patches))


@pytest.mark.parametrize(
    "marker,expected",
    [
        (b"EEPROM_V124", SaveType.EEPROM),
        (b"SRAM_V113", SaveType.SRAM),
        (b"SRAM_F_V100", SaveType.SRAM),
        (b"FLASH_V126", SaveType.FLASH64K),
        (b"FLASH512_V131", SaveType.FLASH64K),
        (b"FLASH1M_V103", SaveType.FLASH128K),
    ],
)
def test_detects_library_marker(marker, expected):
    result = detect_save_type(rom_with(marker))
    assert result.save_type is expected
    assert result.markers == (marker.decode(),)


def test_no_marker_means_no_save():
    assert detect_save_type(rom_with()).save_type is SaveType.NONE


def test_marker_without_version_digits_is_ignored():
    assert detect_save_type(rom_with(b"FLASH_Vxyz")).save_type is SaveType.NONE


def test_first_marker_wins_and_all_are_reported():
    result = detect_save_type(rom_with(b"SRAM_V110", b"FLASH1M_V103"))
    assert result.save_type is SaveType.SRAM
    assert result.markers == ("SRAM_V110", "FLASH1M_V103")
