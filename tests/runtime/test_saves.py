import pytest
from romtest import build_test_rom, run_rom, run_test

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.native.build import rom_identity
from gbaport.rom.image import RomImage
from gbaport.rom.savetype import SaveType

SIGNATURE = b"GBAPORT\0"


def _twice(name: str, save, data: str = ""):
    first = run_test(name, data=data, save=save)
    first.assert_passed()
    assert "WROTE save" in first.lines
    second = run_test(name, data=data, save=save)
    second.assert_passed()
    assert "PASS the save survived" in second.lines
    return save.read_bytes()


def test_sram_works_and_its_save_file_persists(tmp_path):
    data = _twice("save_sram", tmp_path / "game.sav")
    assert len(data) == 0x8000
    assert data[0x100:0x108] == SIGNATURE


@pytest.mark.parametrize("flash_id,chip,banks,size", [
    ("FLASH_V126", 0x1B32, 1, 0x10000),     # 64 KiB, Panasonic
    ("FLASH1M_V103", 0x1362, 2, 0x20000),   # 128 KiB, Sanyo
])
def test_flash_works_and_its_save_file_persists(tmp_path, flash_id, chip, banks, size):
    header = f'#define FLASH_ID "{flash_id}"\n#define FLASH_CHIP 0x{chip:04x}u\n#define FLASH_BANKS {banks}\n'
    data = _twice("save_flash", tmp_path / "game.sav", header)
    assert len(data) == size
    assert data[0x100:0x108] == SIGNATURE


@pytest.mark.parametrize("bits,size", [(6, 0x200), (14, 0x2000)])
def test_eeprom_works_and_its_size_follows_the_dma_length(tmp_path, bits, size):
    data = _twice("save_eeprom", tmp_path / "game.sav", f"#define EEPROM_BITS {bits}\n")
    assert len(data) == size
    assert data[5 * 8 : 6 * 8] == SIGNATURE


def test_a_save_file_of_another_size_is_left_alone(tmp_path):
    save = tmp_path / "game.sav"
    save.write_bytes(bytes(100))
    run = run_rom(build_test_rom("save_sram"), save=save)
    assert run.status == 2
    assert "the save file has 100 bytes, but this game's save chip holds 32768" in run.stderr
    assert save.read_bytes() == bytes(100)


def test_a_save_written_before_a_runtime_error_reaches_the_file(tmp_path):
    save = tmp_path / "game.sav"
    run = run_test("save_then_fail", save=save)
    assert run.status == 3
    assert save.read_bytes()[0x40] == 0x42


def test_hard_reset_keeps_only_the_save(tmp_path):
    run_test("hard_reset", save=tmp_path / "game.sav").assert_passed()


def test_a_save_file_for_a_game_without_a_save_chip_is_ignored(tmp_path):
    save = tmp_path / "game.sav"
    save.write_bytes(b"old")
    run_test("hello", save=save).assert_passed()
    assert save.read_bytes() == b"old"


def test_the_save_type_comes_from_game_toml_or_the_library_id():
    rom = build_test_rom("save_sram")
    image = RomImage(rom.data)
    assert analyze_rom(image, parse_config(rom.config)).save is SaveType.SRAM
    configured = parse_config('[rom]\nsave = "flash128k"\n' + rom.config)
    assert analyze_rom(image, configured).save is SaveType.FLASH128K
    assert "gba_save_type = 3u;  /* flash128k */" in rom_identity(rom.data, SaveType.FLASH128K)
