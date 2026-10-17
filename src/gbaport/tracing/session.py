"""Record where indirect branches and calls go while the game runs in mGBA.

Breakpoints go on every indirect site the analysis could not resolve: each
``bx rN`` call veneer, each unresolved ``bx``/``mov pc``/``ldr pc``, and each
jump table without a bound. When the game stops on one, the session steps that
single instruction and records where it went. A call through a veneer is
recorded at the ``bl`` that called the veneer (found from LR), so it resolves
per call site. While the game runs, new targets are fed back into the
analysis and the breakpoints follow the code that becomes reachable.

A step is recorded only when it plainly finished the site: the site's
condition held, the server answered with a finished step, the CPU mode did
not change (no interrupt was taken) and the game did not land in the BIOS.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from gbaport.analysis.discover import Exploration
from gbaport.analysis.traces import Hit, Trace
from gbaport.isa.model import Cond, Mode, Op
from gbaport.rom.image import ROM_BASE, RomImage
from gbaport.tracing.gdb import GdbClient, GdbError, Registers

MAX_BREAKPOINTS = 256  # mGBA checks every instruction against them; keep the game fast
STEP_TIMEOUT = 1.0
POLL = 0.25  # seconds between checks for the end of the session while the game runs
GAME_MEMORY = 0x02000000  # below this is the BIOS, where no traced target can be
ROM_SAMPLES = 4  # chunks compared besides the header to recognise the loaded ROM
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


def check_loaded_rom(client: GdbClient, rom: RomImage) -> None:
    """Raise ``GdbError`` unless the emulator runs ``rom``: header and samples must match."""
    size = len(rom.data)
    offsets = [0] + [size * k // (ROM_SAMPLES + 1) & ~3 for k in range(1, ROM_SAMPLES + 1)]
    for offset in offsets:
        length = min(0xC0, size - offset)
        if client.read_memory(ROM_BASE + offset, length) != rom.data[offset : offset + length]:
            raise GdbError(
                f"mGBA has a different ROM loaded (it differs at {ROM_BASE + offset:#010x}); "
                "open the same file in mGBA"
            )


def condition_passed(cond: Cond, cpsr: int) -> bool:
    n, z, c, v = (bool(cpsr >> bit & 1) for bit in (31, 30, 29, 28))
    return {
        Cond.EQ: z,
        Cond.NE: not z,
        Cond.CS: c,
        Cond.CC: not c,
        Cond.MI: n,
        Cond.PL: not n,
        Cond.VS: v,
        Cond.VC: not v,
        Cond.HI: c and not z,
        Cond.LS: not c or z,
        Cond.GE: n == v,
        Cond.LT: n != v,
        Cond.GT: not z and n == v,
        Cond.LE: z or n != v,
    }.get(cond, True)


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
        self.sites: dict[int, Site] = {}  # breakpoints that are (or may be) set in the emulator
        self.ex = Exploration()
        self.new_hits = 0
        self.last_refresh = 0.0

    def run(self, seconds: float | None = None) -> None:
        """Trace until ``seconds`` pass, the game exits, or Ctrl+C.

        The trace is always saved. Unless the game exited, the breakpoints
        are then cleared and the game left running, as far as the connection
        still allows.
        """
        deadline = None if seconds is None else self.clock() + seconds
        exited = False
        try:
            self.client.handshake()
            self.client.halt()  # breakpoints are set while the game is stopped
            self._refresh()
            while not self._expired(deadline):
                self.client.cont()
                stop = self._wait(deadline)
                if stop is None or stop.exited:
                    exited = stop is not None
                    break
                self._handle_stop()
                if self.new_hits and self.clock() - self.last_refresh >= self.reanalyze_every:
                    self._refresh()
        except KeyboardInterrupt:
            pass
        finally:
            self.save(self.trace)
            if not exited:
                self._release()

    def _expired(self, deadline: float | None) -> bool:
        return deadline is not None and self.clock() >= deadline

    def _wait(self, deadline: float | None):
        """The next stop, or None once the deadline passes (the game is then halted)."""
        while True:
            stop = self.client.wait_stop(POLL)
            if stop is not None:
                return stop
            if self._expired(deadline):
                self.client.halt()
                return None

    def _handle_stop(self) -> None:
        regs = self.client.registers()
        for _ in range(64):  # never resume from a breakpoint: step over each one first
            site = self.sites.get(regs.pc)
            if site is None:
                return
            origin = self._call_site(site, regs.lr)
            ins = self.ex.instructions.get(site.addr)
            taken = condition_passed(ins.cond if ins is not None else Cond.AL, regs.cpsr)
            stop = self.client.step(STEP_TIMEOUT)
            if stop is None:  # mGBA 0.11 runs on after a step into the BIOS
                self.client.halt()
            after = self.client.registers()
            if taken and stop is not None and stop.step and _plausible(regs, after, site):
                mode = Mode.THUMB if after.thumb else Mode.ARM
                if self.trace.add(Hit(origin, after.pc, mode)):
                    self.new_hits += 1
            if stop is not None and stop.step and after.pc == regs.pc:
                return  # a site that jumps to itself
            regs = after  # after a breakpoint stop or a timeout, pc may be another site

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
            del self.sites[addr]
        for addr in sorted(wanted.keys() - self.sites.keys()):
            self.sites[addr] = wanted[addr]  # first, so a release clears it even if cut short
            self.client.set_breakpoint(addr, wanted[addr].size)
        self.report(f"{len(self.trace.hits)} hits (+{self.new_hits}), {len(wanted)} breakpoints")
        self.new_hits = 0
        self.last_refresh = self.clock()
        self.save(self.trace)

    def _release(self) -> None:
        """Best effort: resynchronise, clear the breakpoints and let the game run on."""
        try:
            self.client.halt()
        except GdbError:
            return  # the connection is gone
        for addr, site in sorted(self.sites.items()):
            try:
                self.client.clear_breakpoint(addr, site.size)
            except GdbError:
                pass  # never set (cut short), or the connection just went
        self.sites = {}
        try:
            self.client.cont()
        except GdbError:
            pass


def _plausible(before: Registers, after: Registers, site: Site) -> bool:
    """The step went somewhere a game can jump: no exception entry, no BIOS, not stuck."""
    return (
        after.pc >= GAME_MEMORY
        and after.cpsr & 0x1F == before.cpsr & 0x1F
        and after.pc != site.addr
    )
