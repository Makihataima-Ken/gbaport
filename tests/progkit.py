"""Small programs assembled at test time, and helpers to decode them.

Address comments assume the program starts at CODE_ADDR (0x080000C0).
"""

from ksasm import assemble
from romkit import build_rom

from gbaport.analysis.config import GameConfig
from gbaport.analysis.discover import Exploration, Traced, explore
from gbaport.analysis.space import CodeSpace
from gbaport.isa.arm import decode_arm
from gbaport.isa.model import Instruction, Mode
from gbaport.isa.thumb import decode_thumb
from gbaport.rom.image import RomImage

CODE_ADDR = 0x080000C0

# ARM start-up code: installs an ARM IRQ handler and calls Thumb main via `mov lr, pc; bx`.
#   c0 start (ARM)   dc irqvec   e0 mainptr   e4 irq (ARM)
#   e8 main (Thumb)  f6 helper   fa, fc: helper's later blocks
CRT0 = """
start:
    ldr r1, irqvec
    adr r0, irq
    str r0, [r1]
    ldr r1, mainptr
    mov lr, pc
    bx r1
    b start
irqvec: .word 0x03007FFC
mainptr: .word main+1
irq:
    bx lr
.thumb
main:
    push {r4, lr}
    bl helper
    movs r0, #0
    pop {r4}
    pop {r1}
    bx r1
helper:
    cmp r0, #3
    beq done
    adds r0, #1
done:
    bx lr
"""

# Thumb call through an agbcc-style `bx r3` veneer.
#   c0 main   c4 bl via_r3   cc fptr   d0 via_r3   d4 target
VENEER = """
main:
    push {lr}
    ldr r3, fptr
    bl via_r3
    pop {r0}
    bx r0
.align 2
fptr: .word target+1
via_r3:
    bx r3
    mov r8, r8
target:
    bx lr
"""

# agbcc Thumb switch: bound check, scale, add table base, load, mov pc.
#   cc dispatch   d0 tabaddr   d4 table (3 words)   e0 c0   e2 c1   e4 c2   e6 dflt
THUMB_TABLE = """
disp:
    cmp r0, #2
    bhi dflt
    lsls r0, r0, #2
    ldr r1, tabaddr
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
.align 2
tabaddr: .word tab
tab:
    .word c0
    .word c1
    .word c2
c0: bx lr
c1: bx lr
c2: bx lr
dflt: bx lr
"""

# The same switch without its bound check.
#   c8 dispatch   cc tabaddr   d0 table (2 words)   d8 c0   da c1
UNBOUNDED_TABLE = """
disp:
    lsls r0, r0, #2
    ldr r1, tabaddr
    adds r0, r0, r1
    ldr r0, [r0]
    mov pc, r0
.align 2
tabaddr: .word tab
tab:
    .word c0
    .word c1
c0: bx lr
c1: bx lr
"""

# ARM `ldrls pc, [pc, r0, lsl #2]` address table, then an `addls pc, pc` branch table.
#   c4 dispatch 1   cc table   d4 c0   d8 c1   dc dflt   e0 dispatch 2   e8/ec branches   f0 out
ARM_TABLES = """
disp:
    cmp r0, #1
    ldrls pc, [pc, r0, lsl #2]
    b dflt
    .word c0
    .word c1
c0: bx lr
c1: bx lr
dflt:
    cmp r1, #1
    addls pc, pc, r1, lsl #2
    b out
    b c0
    b c1
out:
    bx lr
"""

# ARM code storing a RAM address into the IRQ vector.   c8 the store
IRQ_IN_RAM = """
    ldr r1, vec
    ldr r0, handler
    str r0, [r1]
    bx lr
vec: .word 0x03007FFC
handler: .word 0x03001000
"""

# Thumb: f ends with a plain branch into another function.   c0 main   ca f   cc g
TAIL_CALLS = """
main:
    push {lr}
    bl g
    pop {r0}
    bx r0
f:
    b g
g:
    bx lr
"""

# Thumb jump through a known pointer.   c2 bx r0   c4 pointer   c8 other
KNOWN_JUMP = """
    ldr r0, ptr
    bx r0
.align 2
ptr: .word other+1
other:
    bx lr
"""

# Thumb mutual recursion plus a branch-to-self loop.   c0 fa   c6 fb   cc spin
RECURSION = """
fa:
    bl fb
    bx lr
fb:
    bl fa
    b spin
spin:
    b spin
"""


def program_rom(
    source: str, *, thumb: bool = False, size: int = 0x400, patches: dict | None = None
) -> RomImage:
    code = assemble(source, thumb=thumb, addr=CODE_ADDR)
    return RomImage(build_rom(code, size=size, patches=patches))


def program_space(source: str, *, thumb: bool = False, size: int = 0x400) -> CodeSpace:
    return CodeSpace(program_rom(source, thumb=thumb, size=size))


def decode_one(text: str, *, thumb: bool = False, addr: int = CODE_ADDR) -> Instruction:
    code = assemble(text, thumb=thumb, addr=addr)
    if thumb:
        following = int.from_bytes(code[2:4], "little") if len(code) >= 4 else None
        return decode_thumb(int.from_bytes(code[:2], "little"), addr, following)
    return decode_arm(int.from_bytes(code[:4], "little"), addr)


def decode_program(
    space: CodeSpace, count: int, *, thumb: bool = False, start: int = CODE_ADDR
) -> list[Instruction]:
    """Decode ``count`` consecutive instructions (a Thumb BL pair counts once)."""
    listing, addr = [], start
    for _ in range(count):
        if thumb:
            ins = decode_thumb(space.read16(addr), addr, space.read16(addr + 2))
        else:
            ins = decode_arm(space.read32(addr), addr)
        listing.append(ins)
        addr += ins.size
    return listing


def explore_program(
    source: str,
    *,
    thumb: bool = False,
    seeds: list[tuple[int, Mode, str]] | None = None,
    config: GameConfig | None = None,
    size: int = 0x400,
    traced: Traced | None = None,
    candidates: list[tuple[int, Mode, str]] | None = None,
) -> Exploration:
    space = program_space(source, thumb=thumb, size=size)
    mode = Mode.THUMB if thumb else Mode.ARM
    seeds = seeds or [(CODE_ADDR, mode, "seed")]
    return explore(space, seeds, config, traced=traced, candidates=candidates or [])


# ARM DMA3 copy of two words from ROM 0x08000200 to IWRAM 0x03000000, then a jump into the copy.
#   d8 the CNT store that starts the copy   e8 cnt   ec entry
DMA_COPY = """
    mov r0, #0x04000000
    ldr r1, src
    str r1, [r0, #0xd4]
    ldr r1, dst
    str r1, [r0, #0xd8]
    ldr r1, cnt
    str r1, [r0, #0xdc]
    ldr pc, entry
src: .word 0x08000200
dst: .word 0x03000000
cnt: .word 0x84000002
entry: .word 0x03000004
"""
