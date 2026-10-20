"""Build the runtime test ROMs from C, recompile them and run them natively.

A test ROM is ``gbaroms/crt0.s`` + ``gbaroms/testlib.c`` + one test file from
``gbaroms``, compiled with clang for the ARM7TDMI (Thumb, like games) and linked with
ld.lld. Its game.toml lists every function symbol in the ELF as an entry and the IWRAM
section as RAM code, so these tests depend on the runtime and the lifter, not on how
much code discovery finds by itself. A test ROM reports through mGBA's debug log (one
``PASS name`` or ``FAIL name: ...`` line per check, then ``DONE n passed, m failed``)
and ends with the BIOS Stop call.

Runs use the headless host unless they ask for the window host (``host="sdl"``), which
then runs with SDL's dummy video driver: no window opens.

ROMs and native builds are cached in the system temp folder by the hash of their sources.
"""

import hashlib
import os
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.native.toolchain import find_clang, llvm_tool
from gbaport.rom.image import RomImage

ROMS = Path(__file__).parent / "gbaroms"
CACHE = Path(tempfile.gettempdir()) / "gbaport-romcache"
TARGET = ["--target=armv4t-none-eabi", "-mcpu=arm7tdmi"]
# No jump tables: clang's Thumb switch tables are a pattern discovery does not know (games are
# built with GCC or ARM's compiler), and these ROMs test the runtime, not discovery.
CFLAGS = [*TARGET, "-mthumb", "-O2", "-ffreestanding", "-fno-builtin", "-fno-jump-tables",
          "-Wall", "-Werror"]
STT_FUNC = 2


@dataclass(frozen=True)
class TestRom:
    data: bytes
    config: str  # game.toml text
    symbols: dict[str, int] = field(default_factory=dict)  # the ELF's, by name


def _digest(*parts: bytes | str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode() if isinstance(part, str) else part)
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{Path(command[0]).name} failed:\n{result.stderr[-4000:]}")


def elf_symbols(elf: bytes) -> dict[str, tuple[int, int]]:
    """Name -> (value, type) for every named symbol of a little-endian ELF32 file."""
    shoff, = struct.unpack_from("<I", elf, 0x20)
    shentsize, shnum = struct.unpack_from("<HH", elf, 0x2E)
    sections = [struct.unpack_from("<10I", elf, shoff + i * shentsize) for i in range(shnum)]
    symbols = {}
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        strtab = sections[section[6]]
        for offset in range(section[4], section[4] + section[5], 16):
            name, value, _, info = struct.unpack_from("<IIIB", elf, offset)
            start = strtab[4] + name
            text = elf[start : elf.index(b"\0", start)].decode()
            if text:
                symbols[text] = (value, info & 0xF)
    return symbols


def config_for(symbols: dict[str, tuple[int, int]]) -> str:
    """game.toml: every function as an entry (odd values are Thumb), IWRAM as RAM code."""
    functions = [value for value, kind in symbols.values() if kind == STT_FUNC]
    arm = sorted(v for v in functions if not v & 1)
    thumb = sorted(v - 1 for v in functions if v & 1)
    start, end = symbols["__iwram_start"][0], symbols["__iwram_end"][0]
    lines = [
        "[code]",
        f"entries = [{', '.join(hex(v) for v in arm)}]",
        f"thumb_entries = [{', '.join(hex(v) for v in thumb)}]",
        "scan_pointers = false",
    ]
    if end > start:
        lines += [
            "", "[[ram_code]]", f"rom = {symbols['__iwram_lma'][0]:#x}", f"ram = {start:#x}",
            f"size = {end - start:#x}", 'mode = "arm"',
        ]
    return "\n".join(lines) + "\n"


def _with_header(image: bytes) -> bytes:
    rom = bytearray(image)
    rom[0xA0:0xAC] = b"GBAPORTTEST\0"
    rom[0xAC:0xB0] = b"ATST"
    rom[0xB0:0xB2] = b"01"
    rom[0xB2] = 0x96
    rom[0xBD] = (-(sum(rom[0xA0:0xBD]) + 0x19)) & 0xFF
    return bytes(rom)


def build_test_rom(name: str, data: str = "") -> TestRom:
    """Compile ``gbaroms/<name>.c`` with crt0 and testlib into a ROM and its game.toml.

    ``data`` becomes ``testdata.h``, which the test file may include: inputs and expected
    results that the Python tests compute (with ``biosref``, for example).
    """
    sources = [ROMS / "crt0.s", ROMS / "testlib.c", ROMS / f"{name}.c"]
    inputs = [ROMS / "gba.ld", ROMS / "testlib.h", *sources]
    folder = CACHE / "roms" / _digest(*(path.read_bytes() for path in inputs), *CFLAGS, data)
    rom_path, config_path = folder / "game.gba", folder / "game.toml"
    if not rom_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "testdata.h").write_text(data, encoding="utf-8")
        objects = []
        for source in sources:
            obj = folder / f"{source.stem}.o"
            flags = TARGET if source.suffix == ".s" else CFLAGS
            includes = [f"-I{ROMS}", f"-I{folder}"]
            _run([find_clang(), *flags, *includes, "-c", str(source), "-o", str(obj)])
            objects.append(str(obj))
        elf = folder / "game.elf"
        _run([llvm_tool("ld.lld"), "-T", str(ROMS / "gba.ld"), *objects, "-o", str(elf)])
        binary = folder / "game.bin"
        _run([llvm_tool("llvm-objcopy"), "-O", "binary", str(elf), str(binary)])
        config_path.write_text(config_for(elf_symbols(elf.read_bytes())), encoding="utf-8")
        rom_path.write_bytes(_with_header(binary.read_bytes()))
    elf = elf_symbols((folder / "game.elf").read_bytes())
    symbols = {name: value for name, (value, _) in elf.items()}
    return TestRom(rom_path.read_bytes(), config_path.read_text(encoding="utf-8"), symbols)


# ---- running a test ROM natively --------------------------------------------------------


@dataclass(frozen=True)
class Run:
    status: int
    lines: tuple[str, ...]  # the debug log
    stderr: str

    @property
    def failures(self) -> list[str]:
        return [line for line in self.lines if line.startswith("FAIL")]

    def assert_passed(self) -> None:
        assert self.status == 0, f"exit status {self.status}: {self.stderr}\n" + "\n".join(self.lines)
        assert self.failures == [], "\n".join(self.lines)
        assert self.lines and self.lines[-1].startswith("DONE "), "\n".join(self.lines)


def native_program(rom: TestRom, host: str = "headless") -> Path:
    """Recompile ``rom`` and build it with ``host`` (cached by the C sources)."""
    image = RomImage(rom.data)
    analysis = analyze_rom(image, parse_config(rom.config), ())
    lifted = lift_program(analysis.program, analysis.exploration)
    files = native.generated_sources(lifted, rom.data, analysis.save)
    runtime = [path.read_bytes() for path in sorted(native.RUNTIME.glob("*.[ch]"))]
    flags = " ".join([*native.CFLAGS, *native.RUNTIME_SOURCES])
    sources = (f"{name}\n{text}" for name, text in sorted(files.items()))
    folder = CACHE / "native" / _digest(*sources, *runtime, flags, host)
    built = folder / "program.txt"  # written last: the build finished
    if not built.exists():
        native.write_sources(files, folder / "generated")
        program = native.compile_native(folder / "generated", folder / "build", "game", host)
        built.write_text(str(program), encoding="utf-8")
    return Path(built.read_text(encoding="utf-8"))


def run_program(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run a native program. Windows' Smart App Control sometimes blocks a program the
    first time it starts after being built (WinError 4551); a later start works."""
    for attempt in range(5):
        try:
            return subprocess.run(
                command, capture_output=True, text=True, timeout=120, check=False, env=env
            )
        except OSError as error:
            if getattr(error, "winerror", None) != 4551 or attempt == 4:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def run_rom(
    rom: TestRom, *, frames: int = 600, rom_file: bytes | None = None, save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (), env: dict[str, str] | None = None,
) -> Run:
    """Run the native build of ``rom`` (given ``rom_file`` instead of the ROM, if set).

    The game's save file is ``save``; without one, every run starts with a blank save.
    ``args`` go to the program after the usual ones. The window host runs with SDL's dummy
    video and sound drivers (no window opens, nothing plays), unless ``env`` says otherwise.
    """
    program = native_program(rom, host)
    path = program.parent / f"input-{_digest(rom_file or rom.data)}.gba"
    path.write_bytes(rom_file or rom.data)
    if host == "sdl":
        env = {**os.environ, "SDL_VIDEO_DRIVER": "dummy", "SDL_AUDIO_DRIVER": "dummy", **(env or {})}
    elif env:
        env = {**os.environ, **env}
    with tempfile.TemporaryDirectory() as scratch:
        save_path = save or Path(scratch) / "game.sav"
        command = [str(program), str(path), "--frames", str(frames), "--save", str(save_path), *args]
        result = run_program(command, env)
    return Run(result.returncode, tuple(result.stdout.splitlines()), result.stderr)


def run_test(
    name: str, *, frames: int = 600, data: str = "", save: Path | None = None,
    host: str = "headless", args: tuple[str, ...] = (),
) -> Run:
    return run_rom(build_test_rom(name, data), frames=frames, save=save, host=host, args=args)


def read_bmp(path: Path) -> list[int]:
    """A 240x160, 24-bit BMP's pixels as 0x00RRGGBB values, top row first."""
    data = path.read_bytes()
    offset, = struct.unpack_from("<I", data, 10)
    width, height = struct.unpack_from("<ii", data, 18)
    assert (width, abs(height), data[28]) == (240, 160, 24), "not a 240x160 24-bit BMP"
    pixels = []
    for y in range(160):
        row = offset + (159 - y if height > 0 else y) * 720  # bottom-up unless the height is negative
        for x in range(240):
            b, g, r = data[row + 3 * x : row + 3 * x + 3]
            pixels.append(r << 16 | g << 8 | b)
    return pixels
