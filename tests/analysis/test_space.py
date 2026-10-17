import pytest
from romkit import build_rom

from gbaport.analysis.config import ConfigError, RamCode
from gbaport.analysis.space import CodeSpace
from gbaport.isa.model import Mode
from gbaport.rom.image import RomError, RomImage


def rom_with_blob() -> RomImage:
    return RomImage(build_rom(size=0x400, patches={0x200: bytes(range(16))}))


def test_reads_rom_and_its_mirrors():
    space = CodeSpace(RomImage(build_rom(code=bytes([1, 2, 3, 4]))))
    assert space.read32(0x080000C0) == 0x04030201
    assert space.read32(0x0A0000C0) == 0x04030201
    assert space.read16(0x0C0000C2) == 0x0403
    assert space.canonical(0x0A0000C0) == 0x080000C0
    assert space.canonical(0x03000000) == 0x03000000


def test_ram_overlay_reads_blob_from_rom():
    blob = RamCode(rom=0x08000200, ram=0x03000000, size=16, mode=Mode.ARM)
    space = CodeSpace(rom_with_blob(), (blob,))
    assert space.read32(0x03000004) == 0x07060504
    assert space.contains(0x0300000C, 4)
    assert not space.contains(0x0300000E, 4)
    assert space.rom_offset(0x03000004) == 0x204


def test_reads_outside_raise():
    space = CodeSpace(RomImage(build_rom(size=0x400)))
    assert not space.contains(0x02000000)
    assert space.rom_offset(0x08000400) is None
    with pytest.raises(RomError, match="outside analysable code"):
        space.read16(0x02000000)


@pytest.mark.parametrize(
    "blobs,message",
    [
        ((RamCode(0x08000300, 0x03000000, 0x200, Mode.ARM),), "outside the ROM"),
        ((RamCode(0x08000200, 0x08001000, 0x10, Mode.ARM),), "inside cartridge space"),
        (
            (
                RamCode(0x08000200, 0x03000000, 0x10, Mode.ARM),
                RamCode(0x08000200, 0x03000008, 0x10, Mode.ARM),
            ),
            "overlap",
        ),
    ],
)
def test_rejects_bad_overlays(blobs, message):
    with pytest.raises(ConfigError, match=message):
        CodeSpace(rom_with_blob(), blobs)
