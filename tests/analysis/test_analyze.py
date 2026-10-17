import json

import pytest
from ksasm import assemble
from progkit import CRT0, program_rom

from gbaport.analysis.analyze import Coverage, analysis_to_dict, analyze_rom, summary_lines
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.isa.model import Mode


def test_analyze_crt0_rom():
    analysis = analyze_rom(program_rom(CRT0))
    assert sorted(analysis.program.functions) == [0x080000C0, 0x080000E4, 0x080000E8, 0x080000F6]
    assert analysis.coverage == Coverage(
        rom_bytes=0x400, code_bytes=54, literal_bytes=8, data_bytes=0xC0
    )


def test_summary_lines():
    lines = summary_lines(analyze_rom(program_rom(CRT0)))
    assert lines[0] == "functions    4 (0 veneers)"
    assert "classified   24.8% of 1024 bytes" in lines
    assert lines[-1] == "issues       0 (none)"


def test_json_document():
    doc = analysis_to_dict(analyze_rom(program_rom(CRT0)))
    assert doc["format"] == "gbaport-analysis/1"
    assert doc["rom"]["game_code"] == "ATST"
    assert doc["functions"][0] == {
        "entry": "0x080000c0",
        "mode": "arm",
        "kind": "seed",
        "blocks": ["0x080000c0"],
        "calls": ["0x080000e8"],
        "tail_calls": [],
    }
    assert doc["blocks"][0] == {
        "start": "0x080000c0",
        "end": "0x080000dc",
        "mode": "arm",
        "successors": ["0x080000c0"],
    }
    assert doc["literals"] == [
        {"addr": "0x080000dc", "size": 4},
        {"addr": "0x080000e0", "size": 4},
    ]
    assert doc["coverage"] == {
        "rom_bytes": 1024, "code_bytes": 54, "literal_bytes": 8, "data_bytes": 192,
    }
    assert json.loads(json.dumps(doc)) == doc


def test_config_entries_and_ram_code():
    patches = {
        0x200: assemble("bx lr", thumb=True, addr=0x08000200),
        0x300: assemble("bx lr", addr=0x03000000),
    }
    rom = program_rom("bx lr", patches=patches)
    config = GameConfig(
        thumb_entries=(0x08000200,),
        ram_code=(RamCode(0x08000300, 0x03000000, 4, Mode.ARM),),
    )
    analysis = analyze_rom(rom, config)
    assert analysis.program.functions[0x08000200].mode is Mode.THUMB
    assert analysis.program.functions[0x03000000].mode is Mode.ARM
    assert analysis.coverage.code_bytes == 4 + 2 + 4


def test_sha1_mismatch_is_rejected():
    with pytest.raises(ConfigError, match="sha1"):
        analyze_rom(program_rom("bx lr"), GameConfig(rom_sha1="0" * 40))


def test_data_range_outside_rom_is_rejected():
    config = GameConfig(data=((0x08100000, 0x08100010),))
    with pytest.raises(ConfigError, match="outside the ROM"):
        analyze_rom(program_rom("bx lr"), config)


def test_data_ranges_count_as_data():
    config = GameConfig(data=((0x08000200, 0x08000300),))
    assert analyze_rom(program_rom("bx lr"), config).coverage.data_bytes == 0xC0 + 0x100
