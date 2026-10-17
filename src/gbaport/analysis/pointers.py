"""Function-pointer candidates: ROM words that point at a plausible function start.

Callbacks and state-machine tables are reached only through pointers the game
loads at run time, so recursive descent never sees them. A word holding a code
address is a candidate when its target starts with a frame-saving prologue
(Thumb ``push {..., lr}``, ARM ``stmdb sp!, {..., lr}`` or ``mov r12, sp``)
and decodes cleanly up to its first unconditional transfer. Discovery walks
candidates only after everything reachable from trusted seeds is decoded, so a
wrong guess cannot claim real code first.
"""

import sys
from array import array

from gbaport.analysis.flow import writes_pc
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Cond, Mode, Op
from gbaport.rom.image import ROM_BASE

MAX_PROBE = 256  # instructions decoded before a candidate is given up on
_SUSPECT = frozenset({Op.UNDEFINED, Op.BL_HI, Op.BL_LO})


def pointer_candidates(space: CodeSpace) -> list[tuple[int, Mode, str]]:
    """(address, mode, "pointer") for each plausible function some aligned ROM word points at."""
    data = space.rom.data
    words = array("I")
    words.frombytes(data[: len(data) - len(data) % 4])
    if sys.byteorder == "big":
        words.byteswap()
    rom_end = ROM_BASE + len(data)
    pointers = {word for word in words if ROM_BASE <= word < rom_end}
    for blob in space.overlays:
        pointers |= {word for word in words if blob.ram <= word < blob.ram + blob.size}
    found = []
    for word in sorted(pointers):
        if word & 1:
            addr, mode = word - 1, Mode.THUMB
        elif word & 2 == 0:
            addr, mode = word, Mode.ARM
        else:
            continue
        if _has_prologue(space, addr, mode) and _decodes_cleanly(space, addr, mode):
            found.append((addr, mode, "pointer"))
    return found


def _has_prologue(space: CodeSpace, addr: int, mode: Mode) -> bool:
    if mode is Mode.THUMB:
        return space.contains(addr, 2) and space.read16(addr) >> 8 == 0xB5  # push {..., lr}
    if not space.contains(addr, 4):
        return False
    word = space.read32(addr)
    return (word & 0xFFFF4000) == 0xE92D4000 or word == 0xE1A0C00D  # stmdb sp!, {..lr} / mov ip, sp


def _decodes_cleanly(space: CodeSpace, addr: int, mode: Mode) -> bool:
    """Decode straight on up to the first unconditional transfer; False on anything odd."""
    for _ in range(MAX_PROBE):
        ins = space.decode(addr, mode)
        if ins is None or ins.op in _SUSPECT:
            return False
        if ins.cond is Cond.AL and (ins.op is Op.B or writes_pc(ins)):
            return True
        addr += ins.size
    return False
