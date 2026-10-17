import itertools

import pytest
from gdbfake import SESSION_RUN, FakeGdbServer, State
from progkit import SESSION_PROGRAM, program_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode
from gbaport.rom.info import inspect_rom
from gbaport.tracing.gdb import GdbClient, GdbError
from gbaport.tracing.session import Site, TraceSession, breakpoint_sites, check_loaded_rom

ROM = program_rom(SESSION_PROGRAM)
SHA1 = inspect_rom(ROM).sha1

def analyze(trace):
    return analyze_rom(ROM, traces=(trace,)).exploration


def session(server, trace=None, **options):
    saved = []
    options.setdefault("reanalyze_every", 0)
    traced = TraceSession(
        GdbClient(server), analyze, trace or Trace(SHA1), save=saved.append, **options
    )
    return traced, saved


def test_breakpoint_sites():
    assert breakpoint_sites(analyze(Trace(SHA1))) == [Site(0x080000D4, Mode.ARM, True)]
    after = analyze(Trace(SHA1, {Hit(0x080000C8, 0x080000D8, Mode.ARM)}))
    assert breakpoint_sites(after) == [
        Site(0x080000D4, Mode.ARM, True),
        Site(0x080000E4, Mode.ARM, False),
    ]


def test_records_calls_and_follows_new_code():
    server = FakeGdbServer(SESSION_RUN)
    traced, saved = session(server)
    traced.run()
    assert traced.trace.hits == {
        Hit(0x080000C8, 0x080000D8, Mode.ARM),  # recorded at the bl, not the veneer
        Hit(0x080000E4, 0x080000F0, Mode.ARM),  # a site that only existed after re-analysis
    }
    assert saved[-1] is traced.trace
    assert server.breakpoints == {0x080000D4: 4, 0x080000E4: 4}  # the game exited


def test_steps_over_a_site_that_lands_on_another_site():
    known = Trace(SHA1, {Hit(0x080000C8, 0x080000D8, Mode.ARM)})
    run = [
        State(0x080000C0, thumb=False),
        State(0x080000D4, thumb=False, lr=0x080000CC),
        State(0x080000E4, thumb=False, lr=0x080000E8),
        State(0x080000F0, thumb=False),
    ]
    traced, _ = session(FakeGdbServer(run), known)
    traced.run()
    assert Hit(0x080000C8, 0x080000E4, Mode.ARM) in traced.trace.hits
    assert Hit(0x080000E4, 0x080000F0, Mode.ARM) in traced.trace.hits


def test_time_limit_stops_and_releases_the_game():
    server = FakeGdbServer([State(0x080000C0, thumb=False)], endless=True)
    ticks = itertools.count()
    traced, saved = session(server, clock=lambda: float(next(ticks)))
    traced.run(seconds=3)
    assert server.breakpoints == {}
    assert server.running  # left running in mGBA
    assert saved


def test_lost_connection_still_saves_the_trace():
    server = FakeGdbServer(SESSION_RUN, lose_at=3)
    traced, saved = session(server, reanalyze_every=1000)
    with pytest.raises(GdbError, match="connection lost"):
        traced.run()
    assert saved[-1].hits == {Hit(0x080000C8, 0x080000D8, Mode.ARM)}


def test_progress_is_reported():
    lines = []
    traced, _ = session(FakeGdbServer(SESSION_RUN), report=lines.append)
    traced.run()
    assert lines[0] == "0 hits (+0), 1 breakpoints"
    assert lines[-1].endswith("2 breakpoints")


def test_conditional_site_that_falls_through_records_nothing():
    source = "push {lr}\nldr r1, [r0]\ncmp r0, #0\nbxne r1\npop {lr}\nbx lr"
    rom = program_rom(source)
    sha1 = inspect_rom(rom).sha1
    run = [
        State(0x080000C0, thumb=False),
        State(0x080000CC, thumb=False, flags=0x40000000),  # Z set: bxne does not jump
        State(0x080000D0, thumb=False),
    ]
    traced = TraceSession(
        GdbClient(FakeGdbServer(run)),
        lambda trace: analyze_rom(rom, traces=(trace,)).exploration,
        Trace(sha1),
        reanalyze_every=0,
    )
    traced.run()
    assert traced.trace.hits == set()


# An IRQ is taken on the step: mGBA 0.10 runs the BIOS vector instead of the site.
IRQ_ON_STEP = [
    State(0x080000C0, thumb=False),
    State(0x080000D4, thumb=False, lr=0x080000CC),
    State(0x00000128, thumb=False, mode=0x12),
    State(0x080000D4, thumb=False, lr=0x080000CC),
    State(0x080000D8, thumb=False, lr=0x080000CC),
]


def test_irq_taken_during_a_step_records_nothing():
    traced, _ = session(FakeGdbServer(IRQ_ON_STEP))
    traced.run()
    assert traced.trace.hits == {Hit(0x080000C8, 0x080000D8, Mode.ARM)}


def test_step_that_runs_on_to_another_breakpoint_records_nothing():
    traced, _ = session(FakeGdbServer(IRQ_ON_STEP, step_skips_bios=True))
    traced.run()
    assert traced.trace.hits == {Hit(0x080000C8, 0x080000D8, Mode.ARM)}


def test_step_that_never_comes_back_records_nothing():
    run = IRQ_ON_STEP[:3]
    ticks = itertools.count()
    server = FakeGdbServer(run, step_skips_bios=True, endless=True)
    traced, _ = session(server, clock=lambda: float(next(ticks)))
    traced.run(seconds=5)
    assert traced.trace.hits == set()


def test_time_limit_holds_while_breakpoints_keep_firing():
    run = [State(0x080000C0, thumb=False)] + [
        State(0x080000D4, thumb=False, lr=0x080000CC),
        State(0x080000D8, thumb=False, lr=0x080000CC),
    ] * 200
    server = FakeGdbServer(run)
    ticks = itertools.count()
    traced, _ = session(server, clock=lambda: float(next(ticks)), reanalyze_every=1000)
    traced.run(seconds=10)
    assert server.index < 40
    assert server.breakpoints == {}
    assert server.running


def test_ctrl_c_with_a_stop_in_flight_releases_the_game():
    server = FakeGdbServer(SESSION_RUN, interrupt_in_flight=True)
    traced, saved = session(server)
    traced.run()
    assert server.breakpoints == {}
    assert server.running
    assert saved


def test_ctrl_c_while_setting_breakpoints_releases_them():
    known = Trace(SHA1, {Hit(0x080000C8, 0x080000D8, Mode.ARM)})
    server = FakeGdbServer(SESSION_RUN, raise_after="Z0,80000e4")
    traced, _ = session(server, known)
    traced.run()
    assert server.breakpoints == {}
    assert server.running


def test_check_loaded_rom():
    check_loaded_rom(GdbClient(FakeGdbServer(SESSION_RUN, rom=ROM.data)), ROM)
    other = program_rom("bx lr")
    with pytest.raises(GdbError, match="different ROM"):
        check_loaded_rom(GdbClient(FakeGdbServer(SESSION_RUN, rom=other.data)), ROM)
