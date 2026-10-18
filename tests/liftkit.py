"""Run small programs both lifted to C and in Unicorn, and compare the end states.

A case is a snippet of assembly plus an initial state. The kit appends
``stop: svc`` with BIOS number 0xFF (``b .`` after it keeps the analysis short);
both runs end there, and snippets may branch to ``stop`` themselves.
``run_lifted`` analyses and lifts every case, builds one test binary for the whole
batch (cached by the hash of its sources) and runs it; ``run_oracle`` executes the
same cases in Unicorn's ARM926 model. Both report an ``Outcome``.

Memory is three 4 KiB windows: the ROM at 0x08000000 (the assembled snippet), EWRAM
at 0x02000000 and IWRAM at 0x03000000. Unicorn is an ARMv5 core, so tests stay
inside the behaviour ARMv4T shares with it: aligned memory accesses, and no
dependence on C or V after a multiply.
"""

import functools
import hashlib
import random
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ksasm import assemble
from progkit import CODE_ADDR
from romkit import build_rom
from unicorn import UC_ARCH_ARM, UC_MODE_ARM, UC_MODE_THUMB, Uc, UcError
from unicorn import arm_const as uc_arm

import gbaport.lift
from gbaport.analysis.cfg import build_program
from gbaport.analysis.discover import explore
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.lift.function import function_name
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage

WINDOW = 0x1000
ROM, EWRAM, IWRAM = 0x08000000, 0x02000000, 0x03000000
SYS_MODE = 0x1F
STATUSES = ("stopped", "returned", "undefined", "missing", "fault", "runaway")
HOST = Path(__file__).with_name("lifthost.c")
INCLUDE = Path(gbaport.lift.__file__).parent
CACHE = Path(tempfile.gettempdir()) / "gbaport-liftcache"
_UC_REGS = [getattr(uc_arm, f"UC_ARM_REG_R{n}") for n in range(13)] + [
    uc_arm.UC_ARM_REG_SP,
    uc_arm.UC_ARM_REG_LR,
]


@dataclass
class Case:
    source: str
    thumb: bool = False
    regs: list[int] = field(default_factory=lambda: [0] * 15)  # r0-r14
    flags: int = 0  # NZCV in bits 31-28
    mode: int = SYS_MODE
    ewram: bytes = bytes(WINDOW)
    iwram: bytes = bytes(WINDOW)

    @property
    def cpsr(self) -> int:
        return self.flags | self.mode | (0x20 if self.thumb else 0)

    def rom(self) -> bytes:
        return _rom(self.source, self.thumb)


# The number is in bits 16-23 of an ARM svc and in the low byte of a Thumb one.
TERMINATOR = {  # back in the case's own state: snippets may switch with .thumb / .arm
    False: "\n.align 2\n.arm\nstop:\n    svc #0xff0000\n    b .\n",
    True: "\n.align 1\n.thumb\nstop:\n    svc #0xff\n    b .\n",
}
STOP_MARKER = {False: bytes.fromhex("0000ffef"), True: bytes.fromhex("ffdf")}


@functools.lru_cache(maxsize=4096)
def _rom(source: str, thumb: bool) -> bytes:
    code = assemble(source + TERMINATOR[thumb], thumb=thumb, addr=CODE_ADDR)
    return build_rom(code, size=WINDOW)


@dataclass(frozen=True)
class Outcome:
    status: str
    regs: tuple[int, ...]  # r0-r14
    cpsr: int
    ewram: bytes
    iwram: bytes


def random_case(rng: random.Random, source: str, *, thumb: bool = False, **fields) -> Case:
    """A case with random registers, flags and RAM; ``fields`` override any of them."""
    regs = [interesting(rng) for _ in range(15)]
    case = Case(
        source,
        thumb=thumb,
        regs=regs,
        flags=rng.randrange(16) << 28,
        ewram=rng.randbytes(WINDOW),
        iwram=rng.randbytes(WINDOW),
    )
    for name, value in fields.items():
        setattr(case, name, value)
    return case


def interesting(rng: random.Random) -> int:
    """Mostly random words, often the edge values flags and shifts care about."""
    if rng.random() < 0.3:
        return rng.choice([0, 1, 2, 31, 32, 33, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0xFFFFFFFE])
    return rng.getrandbits(32)


def clang() -> str:
    found = shutil.which("clang") or r"C:\Program Files\LLVM\bin\clang.exe"
    if not Path(found).exists():
        raise RuntimeError("clang not found: install LLVM (winget install LLVM.LLVM)")
    return found


def lift_cases(cases: list[Case]) -> str:
    """One C translation unit with every case's program and the harness case table."""
    parts = ['#include "lifthost.h"\n']
    entries = []
    for i, case in enumerate(cases):
        space = CodeSpace(RomImage(case.rom()))
        mode = Mode.THUMB if case.thumb else Mode.ARM
        ex = explore(space, [(CODE_ADDR, mode, "seed")])
        lifted = lift_program(build_program(ex), ex, prefix=f"c{i}_")
        parts += [lifted.prototypes, *lifted.functions.values(), lifted.dispatch]
        entries.append((function_name(CODE_ADDR, lifted.prefix), lifted.lookup_name))
    parts.append("const HarnessCase HARNESS_CASES[] = {")
    parts += [f"    {{{entry}, {lookup}}}," for entry, lookup in entries]
    parts.append("};")
    parts.append(f"const unsigned HARNESS_CASE_COUNT = {len(cases)};")
    return "\n".join(parts) + "\n"


def build(source: str) -> Path:
    """Compile the harness with ``source``; reuses an earlier build of the same sources."""
    digest = hashlib.sha1()
    for text in (source, HOST.read_text(), (INCLUDE / "gba_cpu.h").read_text()):
        digest.update(text.encode())
    folder = CACHE / digest.hexdigest()[:16]
    exe = folder / "lifthost.exe"
    if exe.exists():
        return exe
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cases.c").write_text(source, encoding="utf-8")
    command = [
        clang(), "-std=c11", "-O1", "-Wall", "-Werror", "-Wno-unused-label",
        f"-I{INCLUDE}", f"-I{HOST.parent}", str(HOST), str(folder / "cases.c"), "-o", str(exe),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"clang failed:\n{result.stderr[-4000:]}")
    return exe


def run_compiled(source: str, cases: list[Case]) -> list[Outcome]:
    """Run ``cases`` with the harness built around ``source`` (it defines HARNESS_CASES)."""
    exe = build(source)
    with tempfile.TemporaryDirectory() as tmp:
        inp, out = Path(tmp) / "in.bin", Path(tmp) / "out.bin"
        with open(inp, "wb") as f:
            f.write(struct.pack("<I", len(cases)))
            for i, case in enumerate(cases):
                f.write(struct.pack("<16I", i, *case.regs))
                f.write(struct.pack("<I", case.cpsr))
                f.write(case.rom().ljust(WINDOW, b"\0")[:WINDOW] + case.ewram + case.iwram)
        subprocess.run([str(exe), str(inp), str(out)], check=True, timeout=30)
        data = out.read_bytes()
    size = 17 * 4 + 2 * WINDOW
    outcomes = []
    for i in range(len(cases)):
        chunk = data[i * size : (i + 1) * size]
        words = struct.unpack_from("<17I", chunk)
        ram = chunk[68:]
        outcomes.append(
            Outcome(STATUSES[words[0]], words[1:16], words[16], ram[:WINDOW], ram[WINDOW:])
        )
    return outcomes


def run_lifted(cases: list[Case]) -> list[Outcome]:
    return run_compiled(lift_cases(cases), cases)


def run_oracle(cases: list[Case]) -> list[Outcome]:
    return [_oracle(case) for case in cases]


def _stop_address(case: Case, code: bytes) -> int:
    marker, step = STOP_MARKER[case.thumb], 2 if case.thumb else 4
    for offset in range(len(code) - step, 0xBF, -step):  # the terminator is the last code
        if code[offset : offset + len(marker)] == marker:
            return ROM + offset
    raise ValueError("no stop marker in the case")


def _oracle(case: Case) -> Outcome:
    code = case.rom()
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB if case.thumb else UC_MODE_ARM)
    uc.ctl_set_cpu_model(uc_arm.UC_CPU_ARM_926)
    for base in (ROM, EWRAM, IWRAM):
        uc.mem_map(base, WINDOW)
    uc.mem_write(ROM, code[:WINDOW])
    uc.mem_write(EWRAM, case.ewram)
    uc.mem_write(IWRAM, case.iwram)
    uc.reg_write(uc_arm.UC_ARM_REG_CPSR, case.cpsr)
    for reg, value in zip(_UC_REGS, case.regs):
        uc.reg_write(reg, value)
    status = "stopped"
    try:
        uc.emu_start(CODE_ADDR | (1 if case.thumb else 0), _stop_address(case, code), count=100000)
        if uc.reg_read(uc_arm.UC_ARM_REG_PC) != _stop_address(case, code):
            status = "runaway"
    except UcError:
        status = "fault"
    regs = tuple(uc.reg_read(reg) for reg in _UC_REGS)
    return Outcome(
        status, regs, uc.reg_read(uc_arm.UC_ARM_REG_CPSR),
        bytes(uc.mem_read(EWRAM, WINDOW)), bytes(uc.mem_read(IWRAM, WINDOW)),
    )


def differences(lifted: Outcome, oracle: Outcome, *, ignore_cv: bool = False) -> list[str]:
    """What differs between two outcomes, ignoring the T bit (and C and V if asked)."""
    flags = 0xF00000DF & ~(0x30000000 if ignore_cv else 0)
    found = []
    if lifted.status != oracle.status:
        found.append(f"status {lifted.status} != {oracle.status}")
    for n, (a, b) in enumerate(zip(lifted.regs, oracle.regs)):
        if a != b:
            found.append(f"r{n} {a:#010x} != {b:#010x}")
    if lifted.cpsr & flags != oracle.cpsr & flags:
        found.append(f"cpsr {lifted.cpsr:#010x} != {oracle.cpsr:#010x}")
    for name in ("ewram", "iwram"):
        a, b = getattr(lifted, name), getattr(oracle, name)
        if a != b:
            first = next(i for i in range(WINDOW) if a[i] != b[i])
            found.append(f"{name} differs from +{first:#x}")
    return found


def assert_same(cases: list[Case], *, ignore_cv: bool = False) -> None:
    """Run ``cases`` both ways and fail with the first few mismatches."""
    failures = []
    for case, lifted, oracle in zip(cases, run_lifted(cases), run_oracle(cases)):
        diff = differences(lifted, oracle, ignore_cv=ignore_cv)
        if diff:
            failures.append(f"{case.source.strip()!r} (thumb={case.thumb}): {'; '.join(diff)}")
    assert not failures, f"{len(failures)} of {len(cases)} cases differ:\n" + "\n".join(
        failures[:10]
    )
