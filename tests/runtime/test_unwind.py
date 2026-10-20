"""Returns past calls in progress: when code returns to an outer call's return address (a
task switch, say), the recompiled functions in between return too, as the runtime unwinds
them, and the calls are as deep as before."""

from romtest import build_test_rom, run_rom

from gbaport.analysis.traces import load_trace
from gbaport.cli import main


def traced(rom, tmp_path):
    path = tmp_path / "tasks.gba"
    path.write_bytes(rom.data)
    out = tmp_path / "tasks.trace"
    assert main(["trace", str(path), "--frames", "30", "--out", str(out)]) == 0
    return load_trace(out)


def test_a_task_switch_returns_past_the_other_tasks_calls(tmp_path):
    rom = build_test_rom("tasks")
    run = run_rom(rom, frames=30, traces=(traced(rom, tmp_path),))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 5 passed, 0 failed"


def test_two_thousand_switches_leave_the_calls_as_deep_as_before(tmp_path):
    """The runtime allows 1024 calls in progress: without unwinding, these would pile up.
    Interrupts come in while they run, at times inside the second task's calls."""
    rom = build_test_rom("tasks", "#define TURNS 2000\n")
    run = run_rom(rom, frames=600, traces=(traced(rom, tmp_path),))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 2001 passed, 0 failed"
