import pytest
from romkit import ROM_BASE, build_rom

from gbaport.rom.header import parse_header
from gbaport.rom.image import MAX_ROM_SIZE, RomError, RomImage


def test_parses_header_fields():
    rom = RomImage(build_rom(title=b"POCKETDEMO", game_code=b"APDE", maker=b"7Z", version=2))
    header = parse_header(rom)
    assert header.title == "POCKETDEMO"
    assert header.game_code == "APDE"
    assert header.maker_code == "7Z"
    assert header.version == 2
    assert header.checksum_ok is True


def test_entry_point_follows_branch_at_rom_start():
    rom = RomImage(build_rom(code_offset=0x100, size=0x200))
    assert parse_header(rom).entry_point == ROM_BASE + 0x100


def test_entry_point_none_when_first_word_is_not_a_branch():
    rom = RomImage(build_rom(patches={0: b"\0\0\0\0"}))
    assert parse_header(rom).entry_point is None


def test_bad_checksum_is_reported_not_rejected():
    data = bytearray(build_rom())
    data[0xBD] ^= 0xFF
    assert parse_header(RomImage(bytes(data))).checksum_ok is False


def test_rejects_rom_smaller_than_header():
    with pytest.raises(RomError, match="too small"):
        RomImage(bytes(0xBF))


def test_rejects_rom_larger_than_32_mib():
    with pytest.raises(RomError, match="too large"):
        RomImage(bytes(MAX_ROM_SIZE + 1))


def test_rejects_missing_fixed_byte():
    with pytest.raises(RomError, match="0x96"):
        parse_header(RomImage(build_rom(patches={0xB2: b"\x00"})))


def test_reads_little_endian_values_at_bus_addresses():
    rom = RomImage(build_rom(code=bytes([0x78, 0x56, 0x34, 0x12])))
    assert rom.read8(ROM_BASE + 0xC0) == 0x78
    assert rom.read16(ROM_BASE + 0xC0) == 0x5678
    assert rom.read32(ROM_BASE + 0xC0) == 0x12345678


def test_reads_outside_rom_raise():
    rom = RomImage(build_rom(size=0x201))
    assert rom.contains(ROM_BASE + 0x200)
    assert not rom.contains(ROM_BASE + 0x200, 2)
    with pytest.raises(RomError, match="outside ROM"):
        rom.read16(ROM_BASE + 0x200)
    with pytest.raises(RomError, match="outside ROM"):
        rom.read8(ROM_BASE - 1)


def test_load_reads_file(tmp_path):
    path = tmp_path / "game.gba"
    path.write_bytes(build_rom())
    assert RomImage.load(path).data == build_rom()


def test_repr_does_not_dump_rom_bytes():
    assert len(repr(RomImage(build_rom()))) < 100


def test_non_ascii_header_bytes_are_escaped():
    rom = RomImage(build_rom(title=b"POK\xe9MON"))
    assert parse_header(rom).title == "POK\\xe9MON"
