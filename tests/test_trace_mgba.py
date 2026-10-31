"""``gbaport trace --frames N``: the game plays in gbaport's own mGBA, and the calls and
jumps it made through registers become a trace that leads discovery to the code there."""

from romtest import build_test_rom, run_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.analysis.traces import Hit, load_trace
from gbaport.cli import main
from gbaport.isa.model import Mode
from gbaport.rom.image import RomImage
from gbaport.tracing.session import breakpoint_sites


def traced(name: str, tmp_path, *args: str):
    rom = build_test_rom(name)
    path = tmp_path / f"{name}.gba"
    path.write_bytes(rom.data)
    out = tmp_path / f"{name}.trace"
    assert main(["trace", str(path), "--frames", "30", "--out", str(out), *args]) == 0
    return rom, load_trace(out)


def unresolved_calls(rom) -> list[int]:
    ex = analyze_rom(RomImage(rom.data), parse_config(rom.config), ()).exploration
    return sorted(issue.addr for issue in ex.issues if issue.kind == "unresolved_call")


def test_trace_records_the_calls_discovery_could_not_follow(tmp_path, capsys):
    """Each at the bl that called the shared bx veneer, so each call site has its own."""
    rom, trace = traced("calls", tmp_path)
    thumb_call, arm_call, _ = unresolved_calls(rom)
    assert Hit(thumb_call, rom.symbols["hidden_thumb"], Mode.THUMB) in trace.hits
    assert Hit(arm_call, rom.symbols["hidden_arm"], Mode.ARM) in trace.hits
    out = capsys.readouterr().out.splitlines()
    assert out[-2].startswith("played 30 frames in mGBA: ")
    assert out[-1] == f"wrote {tmp_path / 'calls.trace'} ({len(trace.hits)} hits)"


def test_a_traced_game_runs_recompiled(tmp_path):
    rom, trace = traced("calls", tmp_path)
    assert "interpreted" in run_rom(rom, frames=30).stderr  # the calls went to code it missed
    run = run_rom(rom, frames=30, traces=(trace,))
    assert run.status == 0, run.stderr
    assert run.lines[-1] == "DONE 2 passed, 0 failed"
    assert "interpreted" not in run.stderr


def test_trace_plays_an_input_file(tmp_path):
    """Saved by a Windows editor: a UTF-8 byte order mark and CRLF line ends."""
    (tmp_path / "a.input").write_bytes(b"\xef\xbb\xbf# A from frame 5\r\n5 A\r\n")
    rom, trace = traced("calls", tmp_path, "--input", str(tmp_path / "a.input"))
    pressed_call = unresolved_calls(rom)[2]
    assert Hit(pressed_call, rom.symbols["hidden_pressed"], Mode.THUMB) in trace.hits
    run = run_rom(rom, frames=30, traces=(trace,), args=("--input", str(tmp_path / "a.input")))
    assert run.lines[-1] == "DONE 3 passed, 0 failed", run.stderr


def test_trace_adds_to_the_hits_already_recorded(tmp_path, capsys):
    (tmp_path / "a.input").write_text("5 A\n", encoding="utf-8")
    _, first = traced("calls", tmp_path, "--input", str(tmp_path / "a.input"))
    _, second = traced("calls", tmp_path)  # A not pressed: nothing new, nothing lost
    assert second.hits == first.hits
    assert capsys.readouterr().out.splitlines()[-2].endswith(", 0 new hits")


def test_trace_checks_its_file_before_playing(tmp_path, capsys):
    """A trace of another ROM in the way: nothing is played, nothing is overwritten."""
    rom = tmp_path / "calls.gba"
    rom.write_bytes(build_test_rom("calls").data)
    other = "gbaport-trace/1 " + "0" * 40 + "\n"
    (tmp_path / "calls.trace").write_text(other, encoding="utf-8")
    args = ["trace", str(rom), "--frames", "30", "--out", str(tmp_path / "calls.trace")]
    assert main(args) == 1
    assert "calls.trace: recorded on ROM sha1 0000" in capsys.readouterr().err
    assert (tmp_path / "calls.trace").read_text(encoding="utf-8") == other


def test_an_input_file_needs_frames(tmp_path, capsys):
    rom = tmp_path / "calls.gba"
    rom.write_bytes(build_test_rom("calls").data)
    (tmp_path / "a.input").write_text("5 A\n", encoding="utf-8")
    assert main(["trace", str(rom), "--input", str(tmp_path / "a.input")]) == 1
    assert "--input needs --frames" in capsys.readouterr().err


def test_returns_the_trace_saw_going_elsewhere_lead_discovery_there(tmp_path):
    """switch_task returns into the other task, where that task last called it."""
    rom, trace = traced("tasks", tmp_path)
    ex = analyze_rom(RomImage(rom.data), parse_config(rom.config), (trace,)).exploration
    assert {rom.symbols["yield_b_resumes"], rom.symbols["task_b_resumes"]} <= set(ex.entries)


def test_the_gdb_recorder_leaves_traced_returns_alone(tmp_path):
    """It has no call stack: at a return it would also record the returns to calls further
    out, and those, made entries, would keep the runtime from unwinding."""
    rom, trace = traced("tasks", tmp_path)
    ex = analyze_rom(RomImage(rom.data), parse_config(rom.config), (trace,)).exploration
    returns = {(rom.symbols["switch_task"] & ~1) + 8, rom.symbols["yield_b_resumes"]}  # the pops
    assert not returns & {site.addr for site in breakpoint_sites(ex)}
