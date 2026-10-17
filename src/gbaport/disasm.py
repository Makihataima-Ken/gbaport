"""Linear-sweep disassembly. Following control flow is Plan 2's job."""

from gbaport.isa.arm import decode_arm
from gbaport.isa.fmt import format_instruction
from gbaport.isa.model import Instruction, Mode
from gbaport.isa.thumb import decode_thumb
from gbaport.rom.image import RomError, RomImage


def disassemble(rom: RomImage, start: int, count: int, mode: Mode) -> list[Instruction]:
    """Decode up to ``count`` consecutive instructions from ``start``; stops at the ROM end."""
    width = 4 if mode is Mode.ARM else 2
    if start % width:
        raise ValueError(f"start {start:#010x} is not {width}-byte aligned for {mode.value} code")
    if not rom.contains(start, width):
        raise RomError(f"start {start:#010x} is outside ROM")
    listing: list[Instruction] = []
    addr = start
    while len(listing) < count and rom.contains(addr, width):
        if mode is Mode.ARM:
            ins = decode_arm(rom.read32(addr), addr)
        else:
            following = rom.read16(addr + 2) if rom.contains(addr + 2, 2) else None
            ins = decode_thumb(rom.read16(addr), addr, following)
        listing.append(ins)
        addr += ins.size
    return listing


def format_line(ins: Instruction) -> str:
    if ins.mode is Mode.THUMB and ins.size == 4:
        raw = f"{ins.raw & 0xFFFF:04x} {ins.raw >> 16:04x}"
    else:
        raw = f"{ins.raw:0{ins.size * 2}x}"
    return f"{ins.addr:08x}:  {raw:<9}  {format_instruction(ins)}"
