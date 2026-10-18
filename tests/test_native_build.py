from romtest import build_test_rom

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage


def test_a_build_windows_refuses_is_linked_again_with_a_salt(tmp_path, monkeypatch):
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    verdicts = iter([False, True])  # Smart App Control refuses the first file, takes the next
    builds = []

    def starts(program):
        builds.append(program.read_bytes())
        return next(verdicts)

    monkeypatch.setattr(native, "_starts", starts)
    program = native.compile_native(tmp_path / "generated", tmp_path / "build", "game")
    assert len(builds) == 2 and builds[0] != builds[1]  # the salt changed the program's bytes
    assert program.read_bytes() == builds[1]
    assert (tmp_path / "build" / "obj" / "gba_salt.c").exists()
