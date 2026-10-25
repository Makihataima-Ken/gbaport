import re

import pytest

from gbaport.analysis.config import (
    ConfigError,
    GameConfig,
    JumpTableOverride,
    RamCode,
    default_config_path,
    load_config,
    parse_config,
)
from gbaport.isa.model import Mode
from gbaport.rom.savetype import SaveType

FULL = """
[rom]
sha1 = "ABCDEF0123456789ABCDEF0123456789ABCDEF01"
save = "flash128k"

[code]
entries = [0x08000204]
thumb_entries = [0x08012345, 0x08012400]
data = [[0x08100000, 0x08180000]]
jump_tables = [{ at = 0x0801F00C, table = 0x0801F010, count = 12 }]

[[ram_code]]
rom = 0x080F0000
ram = 0x03000000
size = 0x800
mode = "arm"

[timing]
model = "frame"
"""


def test_parses_full_config():
    assert parse_config(FULL) == GameConfig(
        rom_sha1="abcdef0123456789abcdef0123456789abcdef01",
        save=SaveType.FLASH128K,
        entries=(0x08000204,),
        thumb_entries=(0x08012345, 0x08012400),
        data=((0x08100000, 0x08180000),),
        jump_tables=(JumpTableOverride(0x0801F00C, 0x0801F010, 12),),
        ram_code=(RamCode(0x080F0000, 0x03000000, 0x800, Mode.ARM),),
        timing_model="frame",
    )


def test_empty_config_has_defaults():
    assert parse_config("") == GameConfig()
    assert GameConfig().scan_pointers is True


def test_pointer_scan_can_be_turned_off():
    assert parse_config("[code]\nscan_pointers = false").scan_pointers is False


def test_the_sweep_is_for_games_that_ask_for_it():
    assert GameConfig().sweep is False
    assert parse_config("[code]\nsweep = true").sweep is True


@pytest.mark.parametrize(
    "text,message",
    [
        ("[cod]\nentries = []", "unknown key(s): cod"),
        ("[code]\nentrys = [1]", "[code]: unknown key(s): entrys"),
        ("[code]\nentries = [-1]", "non-negative integer"),
        ("[code]\nentries = [true]", "non-negative integer"),
        ("[code]\nentries = 5", "list of addresses"),
        ("[code]\ndata = [[2, 1]]", "is empty"),
        ("[code]\nscan_pointers = 1", "scan_pointers must be true or false"),
        ("[code]\nsweep = 1", "sweep must be true or false"),
        ("[code]\ndata = [[1, 2, 3]]", "[start, end] pairs"),
        ("[code]\njump_tables = [{ at = 1, count = 2 }]", "missing key(s): table"),
        ("[code]\njump_tables = [{ at = 1, table = 2, count = 0 }]", "at least 1"),
        ('[[ram_code]]\nrom = 1\nram = 2\nsize = 3\nmode = "arm64"', "mode must be"),
        ('[[ram_code]]\nrom = 1\nram = 2\nmode = "arm"', "missing key(s): size"),
        ('[rom]\nsave = "floppy"', "save must be one of"),
        ('[rom]\nsha1 = "abc"', "40-character"),
        ('[timing]\nmodel = "cycle"', "model must be"),
        ("rom = 5", "[rom] must be a table"),
        ("[code\n", "game.toml"),
    ],
)
def test_rejects_bad_config(text, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        parse_config(text)


def test_load_config_reads_file(tmp_path):
    path = tmp_path / "game.toml"
    path.write_text("[code]\nentries = [0x08000100]\n")
    assert load_config(path).entries == (0x08000100,)


def test_load_config_names_the_file_in_errors(tmp_path):
    path = tmp_path / "mygame.toml"
    path.write_text("[code]\nbogus = 1\n")
    with pytest.raises(ConfigError, match="mygame.toml"):
        load_config(path)


def test_default_config_path(tmp_path):
    assert default_config_path("ATST", tmp_path) is None
    target = tmp_path / "games" / "ATST" / "game.toml"
    target.parent.mkdir(parents=True)
    target.write_text("")
    assert default_config_path("ATST", tmp_path) == target
