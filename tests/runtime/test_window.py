"""The window host (SDL3), run with SDL's dummy video driver: no window opens."""

import time

from romtest import build_test_rom, read_bmp, run_rom, run_test

MODE3 = "#define DISPCNT 0x0403\n"
FRAME_SECONDS = 280896 / 16777216  # one GBA frame


def test_the_window_shows_what_the_headless_host_shows(tmp_path):
    rom = build_test_rom("bitmap", MODE3)
    window, headless = tmp_path / "window.bmp", tmp_path / "headless.bmp"
    run = run_rom(rom, frames=10, host="sdl", args=("--scale", "1", "--screenshot", str(window)))
    assert run.status == 4, run.stderr
    assert run_rom(rom, frames=10, args=("--screenshot", str(headless))).status == 4
    assert read_bmp(window) == read_bmp(headless)


def test_the_window_runs_at_the_gba_frame_rate_unless_fast():
    rom = build_test_rom("bitmap", MODE3)
    run_rom(rom, frames=1, host="sdl")  # builds the program, outside the timing

    def seconds(*args: str) -> float:
        start = time.perf_counter()
        run = run_rom(rom, frames=60, host="sdl", args=args)
        assert run.status == 4, run.stderr
        return time.perf_counter() - start

    paced, fast = seconds(), seconds("--fast")
    assert paced >= 59 * FRAME_SECONDS  # the first frame is not waited for
    assert fast < paced / 2


def test_the_window_host_takes_scripted_presses():
    run = run_test("stop_wake", host="sdl", args=("--press", "30:START"))
    run.assert_passed()
    assert run.lines[:2] == ("stopping", "woke")


def test_the_window_host_refuses_a_bad_scale():
    for scale in ("0", "17"):
        run = run_test("stop_wake", host="sdl", args=("--scale", scale))
        assert run.status == 2
    assert "[--scale N] [--fast]" in run.stderr


def test_the_window_host_stores_a_save_written_before_a_runtime_error(tmp_path):
    save = tmp_path / "game.sav"
    run = run_test("save_then_fail", host="sdl", save=save)
    assert run.status == 3
    assert save.read_bytes()[0x40] == 0x42
