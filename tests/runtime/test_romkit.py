from romtest import build_test_rom, run_test

from gbaport.analysis.config import parse_config
from gbaport.rom.header import parse_header
from gbaport.rom.image import RomImage


def test_a_test_rom_has_a_valid_header_and_entry_branch():
    rom = build_test_rom("hello")
    header = parse_header(RomImage(rom.data))
    assert header.game_code == "ATST"
    assert header.checksum_ok
    assert header.entry_point == 0x080000C0  # crt0's start, after the 0xC0-byte header


def test_the_config_lists_every_function_and_the_iwram_code():
    config = parse_config(build_test_rom("hello").config)
    assert config.scan_pointers is False
    assert len(config.thumb_entries) >= 8  # main, print, check, expect, ... are Thumb
    assert all(0x08000000 <= addr < 0x08010000 for addr in config.thumb_entries)
    assert 0x03000000 in config.entries  # the IRQ handler: ARM code in IWRAM
    (blob,) = config.ram_code
    assert (blob.ram, blob.mode.value) == (0x03000000, "arm")
    assert 0x08000000 < blob.rom < 0x08010000 and blob.size > 0


def test_a_test_rom_can_include_data_from_python():
    run = run_test("data_echo", data='#define ECHO "made in Python"\n')
    assert run.lines[0] == "made in Python"
    run.assert_passed()
