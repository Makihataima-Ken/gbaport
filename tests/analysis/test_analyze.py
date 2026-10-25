import json

import pytest
from ksasm import assemble
from progkit import CRT0, DMA_COPY, program_rom

from gbaport.analysis.analyze import Coverage, analysis_to_dict, analyze_rom, summary_lines
from gbaport.analysis.config import ConfigError, GameConfig, RamCode
from gbaport.analysis.traces import Hit, Trace, TraceError
from gbaport.isa.model import Mode
from gbaport.rom.info import inspect_rom


def test_analyze_crt0_rom():
    analysis = analyze_rom(program_rom(CRT0))
    assert sorted(analysis.program.functions) == [0x080000C0, 0x080000E4, 0x080000E8, 0x080000F6]
    assert analysis.coverage == Coverage(
        rom_bytes=0x400, code_bytes=54, literal_bytes=8, data_bytes=0xC0
    )


def test_summary_lines():
    lines = summary_lines(analyze_rom(program_rom(CRT0)))
    assert lines[0] == "functions    4 (0 veneers)"
    assert lines[1] == "found by     call 2, irq 1, seed 1"
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


def test_traces_must_match_the_rom():
    with pytest.raises(TraceError, match="sha1"):
        analyze_rom(program_rom("bx lr"), traces=(Trace("0" * 40),))


def test_trace_targets_become_functions():
    rom = program_rom("ldr r0, [r1]\nbx r0\nt: bx lr")
    trace = Trace(inspect_rom(rom).sha1, {Hit(0x080000C4, 0x080000C8, Mode.ARM)})
    analysis = analyze_rom(rom, traces=(trace,))
    assert analysis.program.functions[0x080000C8].kind == "trace"
    assert analysis.program.functions[0x080000C0].tail_calls == (0x080000C8,)
    assert analysis_to_dict(analysis)["traced"] == [
        {"site": "0x080000c4", "targets": ["0x080000c8"]}
    ]
    assert "found by     seed 1, trace 1" in summary_lines(analysis)


def test_pointer_scan_finds_callbacks():
    rom = program_rom("bx lr\n.word cb+1\n.thumb\ncb:\n push {lr}\n pop {r0}\n bx r0")
    assert analyze_rom(rom).program.functions[0x080000C8].kind == "pointer"
    without = analyze_rom(rom, GameConfig(scan_pointers=False))
    assert 0x080000C8 not in without.program.functions


def test_the_sweep_finds_functions_for_games_that_ask_for_it():
    rom = program_rom("bx lr\n.thumb\nnext:\n movs r0, #1\n bx lr")
    assert 0x080000C4 not in analyze_rom(rom).program.functions
    swept = analyze_rom(rom, GameConfig(sweep=True))
    assert swept.program.functions[0x080000C4].kind == "neighbour"
    assert "found by     neighbour 1, seed 1" in summary_lines(swept)


def copied_code_rom(source: str = DMA_COPY):
    return program_rom(source, patches={0x200: assemble("bx lr\nbx lr", addr=0x03000000)})


def test_copied_ram_code_is_detected():
    analysis = analyze_rom(copied_code_rom())
    blob = RamCode(0x08000200, 0x03000000, 8, Mode.ARM)
    assert analysis.detected == (blob,)
    assert analysis.ram_code == (blob,)
    assert analysis.program.functions[0x03000004].kind == "jump"
    assert analysis.exploration.issues == []
    assert "ram code     0 configured, 1 detected" in summary_lines(analysis)
    assert analysis_to_dict(analysis)["ram_code"] == [
        {"rom": "0x08000200", "ram": "0x03000000", "size": 8, "mode": "arm", "detected": True}
    ]


def test_copies_without_wanted_code_are_not_adopted():
    analysis = analyze_rom(copied_code_rom(DMA_COPY.replace("0x03000004", "0x03000100")))
    assert analysis.detected == ()
    assert [i.kind for i in analysis.exploration.issues] == ["outside_code"]


def test_copies_from_ram_are_not_adopted():
    analysis = analyze_rom(copied_code_rom(DMA_COPY.replace("0x08000200", "0x02000000")))
    assert analysis.detected == ()


def test_detected_copies_never_overlap_configured_ram_code():
    configured = RamCode(0x08000300, 0x03000000, 4, Mode.ARM)  # overlaps the copy, not the target
    analysis = analyze_rom(copied_code_rom(), GameConfig(ram_code=(configured,)))
    assert analysis.detected == ()
    assert analysis.ram_code == (configured,)
