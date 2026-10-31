import re

from romtest import build_test_rom, run_rom, run_test


def test_a_test_rom_runs_natively_and_reports_through_the_debug_log():
    run = run_test("hello")
    assert run.lines == ("hello from the GBA", "PASS arithmetic", "DONE 1 passed, 0 failed")
    run.assert_passed()


def test_the_memory_map():
    run_test("mem_map").assert_passed()


def test_bios_resets_and_unknown_calls():
    run = run_test("bios_calls")
    run.assert_passed()
    assert "ignoring SWI 0x2b" in run.stderr


def test_the_bios_sound_driver_is_ignored_with_a_warning():
    run = run_test("bios_sound")
    run.assert_passed()
    assert run.lines[:2] == ("before", "after")
    assert "ignoring the BIOS sound driver (SWI 0x1c)" in run.stderr


def test_code_that_was_not_recompiled_runs_in_the_interpreter():
    run = run_test("calls", frames=30, args=("--press", "5:A"))  # game.toml lacks its hooks
    run.assert_passed()
    assert re.search(r"^interpreted \d+ instructions at 3 places$", run.stderr, re.MULTILINE)


def test_a_jump_to_where_there_can_be_no_code_names_the_address():
    run = run_test("err_missing")
    assert run.status == 3
    assert "no recompiled code at 0x08100000 (Thumb state, lr = 0x" in run.stderr
    assert ", frame 0), and none can be there: it is past the end of the ROM" in run.stderr


def test_the_frame_limit_ends_a_game_that_never_stops():
    run = run_test("forever", frames=3)
    assert run.status == 4
    assert "stopped after 3 frames" in run.stderr


def test_a_build_refuses_a_different_rom():
    rom = build_test_rom("hello")
    other = bytearray(rom.data)
    other[-1] ^= 0xFF
    run = run_rom(rom, rom_file=bytes(other))
    assert run.status == 2
    assert "recompiled from a different ROM" in run.stderr
