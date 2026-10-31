"""A game runs in the interpreter as its recompiled code runs: the same lines, the same
picture every frame, the same cycle counts (the hosts' --interpret-all runs no recompiled
code at all). tests/runtime/test_public_roms.py runs jsmolka's ROMs interpreted too."""

import pytest
from romtest import build_test_rom, run_rom

ROMS = [  # test ROMs that need no keys and no test data: timing, interrupts, DMA, BIOS
    "cycles", "interrupts", "intrwait_ime", "timers", "timer_rewrite", "dma", "hblank_dma",
    "hblank_irq", "bios_calls", "tasks", "mem_map", "ramreset_waits", "eeprom_busy",
    "reset_in_irq",
]


def test_a_call_runs_the_code_in_the_state_it_calls_in():
    rom = build_test_rom("wrong_state")
    assert f"{rom.symbols['veneer_as_arm']:#x}" in rom.config  # listed as ARM code
    run = run_rom(rom, frames=30)
    run.assert_passed()  # the Thumb call ran it in Thumb state, in the interpreter
    assert "interpreted" in run.stderr


@pytest.mark.parametrize("name", ROMS)
def test_a_game_interpreted_runs_as_it_runs_recompiled(name, tmp_path):
    rom = build_test_rom(name)
    recompiled = run_rom(rom, frames=300, args=("--hashes", str(tmp_path / "recompiled")))
    interpreted = run_rom(rom, frames=300, args=("--hashes", str(tmp_path / "interpreted"),
                                                 "--interpret-all"))
    assert interpreted.lines == recompiled.lines
    assert interpreted.status == recompiled.status
    assert (tmp_path / "interpreted").read_text() == (tmp_path / "recompiled").read_text()
    assert "interpreted" in interpreted.stderr
