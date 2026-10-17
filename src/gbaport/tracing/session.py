"""Record where indirect branches and calls go while the game runs in mGBA.

Breakpoints go on every indirect site the analysis could not resolve: each
``bx rN`` call veneer, each unresolved ``bx``/``mov pc``/``ldr pc``, and each
jump table without a bound. When the game stops on one, the session steps that
single instruction and records where it went. A call through a veneer is
recorded at the ``bl`` that called the veneer (found from LR), so it resolves
per call site. While the game runs, new targets are fed back into the
analysis and the breakpoints follow the code that becomes reachable.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from gbaport.analysis.discover import Exploration
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Mode, Op
from gbaport.tracing.gdb import GdbClient

MAX_BREAKPOINTS = 256  # mGBA checks every instruction against them; keep the game fast
STEP_TIMEOUT = 1.0
POLL = 0.25  # seconds between checks for the end of the session while the game runs
_SITE_ISSUES = ("unresolved_jump", "unbounded_table", "unresolved_call")


@dataclass(frozen=True)
class Site:
    addr: int
    mode: Mode
    veneer: bool  # a shared ``bx rN`` veneer: record the calling ``bl`` instead

    @property
    def size(self) -> int:
        return 2 if self.mode is Mode.THUMB else 4


def breakpoint_sites(ex: Exploration) -> list[Site]:
    """Indirect sites worth a breakpoint: veneers first, then the rest by address."""
    veneers = sorted(addr for addr, kind in ex.entry_kinds.items() if kind == "veneer")
    others = {issue.addr for issue in ex.issues if issue.kind in _SITE_ISSUES}
    others |= set(ex.traced)  # a traced site may still go somewhere not seen yet
    others = {
        addr
        for addr in others - set(veneers)
        if addr in ex.instructions and ex.instructions[addr].op is not Op.BL
    }
    sites = [Site(a, ex.instructions[a].mode, True) for a in veneers if a in ex.instructions]
    sites += [Site(a, ex.instructions[a].mode, False) for a in sorted(others)]
    return sites[:MAX_BREAKPOINTS]


class TraceSession:
    def __init__(
        self,
        client: GdbClient,
        analyze: Callable[[Trace], Exploration],
        trace: Trace,
        *,
        save: Callable[[Trace], None] = lambda trace: None,
        report: Callable[[str], None] = lambda line: None,
        reanalyze_every: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.analyze = analyze  # analysis with the traces recorded so far
        self.trace = trace
        self.save = save
        self.report = report
        self.reanalyze_every = reanalyze_every
        self.clock = clock
        self.sites: dict[int, Site] = {}
        self.ex = Exploration()
        self.new_hits = 0
        self.last_refresh = 0.0

    def run(self, seconds: float | None = None) -> None:
        """Trace until ``seconds`` pass, the game exits, or Ctrl+C; the trace is always saved."""
        deadline = None if seconds is None else self.clock() + seconds
        running = exited = False
        try:
            self.client.handshake()
            self.client.interrupt()  # mGBA may be running already; stop it to set breakpoints
            self.client.wait_stop(STEP_TIMEOUT)
            self._refresh()
            while True:
                self.client.cont()
                running = True
                stop = self._wait(deadline)
                running = False
                if stop is None or stop.exited:
                    exited = stop is not None
                    break
                self._handle_stop()
                if self.new_hits and self.clock() - self.last_refresh >= self.reanalyze_every:
                    self._refresh()
        except KeyboardInterrupt:
            if running:
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
        finally:
            self.save(self.trace)
        if not exited:
            self._release()

    def _wait(self, deadline: float | None):
        """The next stop, or None once the deadline passes (the game is then stopped)."""
        while True:
            stop = self.client.wait_stop(POLL)
            if stop is not None:
                return stop
            if deadline is not None and self.clock() >= deadline:
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
                return None

    def _handle_stop(self) -> None:
        regs = self.client.registers()
        for _ in range(64):  # never resume from a breakpoint: step over each one first
            site = self.sites.get(regs.pc)
            if site is None:
                return
            origin = self._call_site(site, regs.lr)
            if self.client.step(STEP_TIMEOUT) is None:  # stepped into a BIOS call
                self.client.interrupt()
                self.client.wait_stop(STEP_TIMEOUT)
            regs = self.client.registers()
            mode = Mode.THUMB if regs.thumb else Mode.ARM
            if self.trace.add(Hit(origin, regs.pc, mode)):
                self.new_hits += 1
            if regs.pc == site.addr:
                return

    def _call_site(self, site: Site, lr: int) -> int:
        """The ``bl`` that called a veneer, or the site itself."""
        if site.veneer:
            caller = (lr & ~1) - 4
            ins = self.ex.instructions.get(caller)
            if ins is not None and ins.op is Op.BL:
                return caller
        return site.addr

    def _refresh(self) -> None:
        """Re-analyse with the hits so far and move the breakpoints to the new sites."""
        self.ex = self.analyze(self.trace)
        wanted = {site.addr: site for site in breakpoint_sites(self.ex)}
        for addr in sorted(self.sites.keys() - wanted.keys()):
            self.client.clear_breakpoint(addr, self.sites[addr].size)
        for addr in sorted(wanted.keys() - self.sites.keys()):
            self.client.set_breakpoint(addr, wanted[addr].size)
        self.sites = wanted
        self.report(f"{len(self.trace.hits)} hits (+{self.new_hits}), {len(wanted)} breakpoints")
        self.new_hits = 0
        self.last_refresh = self.clock()
        self.save(self.trace)

    def _release(self) -> None:
        """Clear the breakpoints and let the game run on."""
        for addr, site in sorted(self.sites.items()):
            self.client.clear_breakpoint(addr, site.size)
        self.sites = {}
        self.client.cont()
