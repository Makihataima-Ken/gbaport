"""Build the runtime test ROMs from C.

A test ROM is ``gbaroms/crt0.s`` + ``gbaroms/testlib.c`` + one test file from
``gbaroms``, compiled with clang for the ARM7TDMI (Thumb, like games) and linked with
ld.lld. Its game.toml lists every function symbol in the ELF as an entry and the IWRAM
section as RAM code, so tests that run it depend on the runtime and the lifter, not on
how much code discovery finds by itself.

ROMs are cached in the system temp folder by the hash of their sources.
"""

import hashlib
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gbaport.native.toolchain import find_clang, llvm_tool

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


def build_test_rom(name: str) -> TestRom:
    """Compile ``gbaroms/<name>.c`` with crt0 and testlib into a ROM and its game.toml."""
    sources = [ROMS / "crt0.s", ROMS / "testlib.c", ROMS / f"{name}.c"]
    inputs = [ROMS / "gba.ld", ROMS / "testlib.h", *sources]
    folder = CACHE / "roms" / _digest(*(path.read_bytes() for path in inputs), *CFLAGS)
    rom_path, config_path = folder / "game.gba", folder / "game.toml"
    if not rom_path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        objects = []
        for source in sources:
            obj = folder / f"{source.stem}.o"
            flags = TARGET if source.suffix == ".s" else CFLAGS
            _run([find_clang(), *flags, f"-I{ROMS}", "-c", str(source), "-o", str(obj)])
            objects.append(str(obj))
        elf = folder / "game.elf"
        _run([llvm_tool("ld.lld"), "-T", str(ROMS / "gba.ld"), *objects, "-o", str(elf)])
        binary = folder / "game.bin"
        _run([llvm_tool("llvm-objcopy"), "-O", "binary", str(elf), str(binary)])
        config_path.write_text(config_for(elf_symbols(elf.read_bytes())), encoding="utf-8")
        rom_path.write_bytes(_with_header(binary.read_bytes()))
    return TestRom(rom_path.read_bytes(), config_path.read_text(encoding="utf-8"))
