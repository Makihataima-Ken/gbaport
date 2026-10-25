import os

from romtest import build_test_rom

import gbaport.native.build as native
from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.rom.image import RomImage


def _sources(tmp_path) -> dict[str, str]:
    """The hello ROM's generated sources, written to tmp_path/generated."""
    rom = build_test_rom("hello")
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration), rom.data)
    native.write_sources(files, tmp_path / "generated")
    return files


def test_a_rebuild_compiles_only_the_files_that_changed(tmp_path):
    _sources(tmp_path)
    said = []
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    total = int(said[0].split()[3])  # "compiled N of N files"
    assert said == [f"compiled {total} of {total} files"]
    native.compile_native(tmp_path / "generated", tmp_path / "build", "game", log=said.append)
    assert said[-1] == f"compiled 0 of {total} files"
    dispatch = tmp_path / "generated" / "gba_dispatch.c"
    dispatch.write_text(dispatch.read_text(encoding="utf-8") + "/* changed */\n", encoding="utf-8")
    program = native.compile_native(tmp_path / "generated", tmp_path / "build", "game",
                                    log=said.append)
    assert said[-1] == f"compiled 1 of {total} files"
    assert program.exists()


def test_writing_the_same_sources_again_leaves_their_files_alone(tmp_path):
    native.write_sources({"gba_code_08000000.c": "a", "gba_code_08002000.c": "b",
                          "gba_dispatch.c": "c"}, tmp_path)
    for path in tmp_path.iterdir():
        os.utime(path, (1_000_000_000, 1_000_000_000))
    native.write_sources({"gba_code_08000000.c": "a", "gba_dispatch.c": "d"}, tmp_path)
    assert (tmp_path / "gba_code_08000000.c").stat().st_mtime == 1_000_000_000  # the same text
    assert (tmp_path / "gba_dispatch.c").read_text(encoding="utf-8") == "d"
    assert not (tmp_path / "gba_code_08002000.c").exists()  # gone from the program


def _build(tmp_path, monkeypatch, verdicts: list[bool]):
    """Build the hello ROM while Smart App Control gives ``verdicts``, one per start."""
    _sources(tmp_path)
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
