from ksasm import assemble
from romkit import ROM_BASE, build_rom

from gbaport.cli import main
from gbaport.disasm import disassemble
from gbaport.isa.model import Mode, Op
from gbaport.rom.image import RomImage

CODE_ADDR = ROM_BASE + 0xC0


def write(tmp_path, data: bytes):
    path = tmp_path / "game.gba"
    path.write_bytes(data)
    return path


def test_arm_listing(tmp_path, capsys):
    code = assemble("mov r0, #0x04000000\nldr r1, [pc, #4]\nstr r1, [r0]", addr=CODE_ADDR)
    path = write(tmp_path, build_rom(code))
    assert main(["disasm", str(path), "--start", hex(CODE_ADDR), "--count", "3"]) == 0
    words = [int.from_bytes(code[i:i + 4], "little") for i in range(0, 12, 4)]
    texts = ["mov r0, #0x4000000", "ldr r1, [pc, #4]", "str r1, [r0]"]
    expected = [
        f"{CODE_ADDR + 4 * i:08x}:  {word:08x}   {text}"
        for i, (word, text) in enumerate(zip(words, texts))
    ]
    assert capsys.readouterr().out.splitlines() == expected


def test_thumb_listing_joins_bl_halves(tmp_path, capsys):
    code = assemble("movs r0, #1\nbl #0x08000100", thumb=True, addr=CODE_ADDR)
    path = write(tmp_path, build_rom(code))
    args = ["disasm", str(path), "--start", hex(CODE_ADDR), "--count", "2", "--thumb"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "080000c0:  2001       movs r0, #1",
        "080000c2:  f000 f81d  bl #0x8000100",
    ]


def test_stops_at_rom_end():
    rom = RomImage(build_rom(size=0x200))
    listing = disassemble(rom, ROM_BASE + 0x1F8, 10, Mode.ARM)
    assert [ins.addr for ins in listing] == [ROM_BASE + 0x1F8, ROM_BASE + 0x1FC]


def test_bl_prefix_in_last_halfword_decodes_alone():
    rom = RomImage(build_rom(size=0x200, patches={0x1FE: (0xF000).to_bytes(2, "little")}))
    listing = disassemble(rom, ROM_BASE + 0x1FE, 5, Mode.THUMB)
    assert len(listing) == 1 and listing[0].op is Op.BL_HI


def test_unaligned_start_is_an_error(tmp_path, capsys):
    path = write(tmp_path, build_rom())
    assert main(["disasm", str(path), "--start", hex(CODE_ADDR + 2)]) == 1
    assert "not 4-byte aligned" in capsys.readouterr().err


def test_start_outside_rom_is_an_error(tmp_path, capsys):
    path = write(tmp_path, build_rom())
    assert main(["disasm", str(path), "--start", "0x02000000"]) == 1
    assert "outside ROM" in capsys.readouterr().err
