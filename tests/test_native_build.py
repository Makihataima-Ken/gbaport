from romtest import build_test_rom

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage


def _build(tmp_path, monkeypatch, verdicts: list[bool]):
    """Build the hello ROM while Smart App Control gives ``verdicts``, one per start."""
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    answers, builds = iter(verdicts), []

    def starts(program):
        builds.append(program.read_bytes())
        return next(answers)

    monkeypatch.setattr(native, "_starts", starts)
    return native.compile_native(tmp_path / "generated", tmp_path / "build", "game"), builds


def test_a_build_windows_refuses_is_linked_again_with_a_salt(tmp_path, monkeypatch):
    program, builds = _build(tmp_path, monkeypatch, [False, True])  # refuses the first file
    assert len(builds) == 2 and builds[0] != builds[1]  # the salt changed the program's bytes
    assert program.read_bytes() == builds[1]
    assert (tmp_path / "build" / "obj" / "gba_salt.c").exists()


def test_a_build_windows_refuses_many_times_in_a_row_is_still_linked_again(tmp_path, monkeypatch):
    # Seen in a full test run: Windows refused one program 8 times before it took one.
    program, builds = _build(tmp_path, monkeypatch, [False] * 8 + [True])
    assert len(set(builds)) == 9
    assert program.read_bytes() == builds[-1]
