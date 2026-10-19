"""Finding the tools SDL3's build needs, and what a failed build says (the real build runs
in tests/runtime/test_window.py)."""

import pytest

from gbaport.native import sdl3, toolchain
from gbaport.native.toolchain import ToolchainError


def test_the_cache_folder_can_be_moved(monkeypatch, tmp_path):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path))
    assert sdl3.cache_folder() == tmp_path


def test_missing_cmake_and_ninja_say_how_to_get_them(monkeypatch, tmp_path):
    for name in ("GBAPORT_CMAKE", "GBAPORT_NINJA"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: None)
    monkeypatch.setattr(toolchain, "PROGRAM_FILES", (tmp_path,))  # no Visual Studio here
    with pytest.raises(ToolchainError, match="winget install Kitware.CMake"):
        toolchain.find_cmake()
    with pytest.raises(ToolchainError, match="winget install Ninja-build.Ninja"):
        toolchain.find_ninja()


def test_a_failed_download_stops_the_build_with_cmake_s_output(monkeypatch, tmp_path):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path))
    monkeypatch.setattr(sdl3, "SDL3_URL", (tmp_path / "missing.tar.gz").as_posix())
    with pytest.raises(ToolchainError, match="building SDL3 failed"):
        sdl3.sdl3_prefix(log=lambda text: None)
    assert not (tmp_path / f"sdl3-{sdl3.SDL3_VERSION}" / "lib").exists()


def test_the_link_flags_come_from_sdl3_pc(tmp_path):
    (tmp_path / "lib" / "pkgconfig").mkdir(parents=True)
    (tmp_path / "lib" / "pkgconfig" / "sdl3.pc").write_text(
        "prefix=/somewhere\nLibs: -L${libdir}  -lSDL3-static -lwinmm\nCflags: -I${includedir}\n",
        encoding="utf-8",
    )
    include, libraries = sdl3.sdl3_flags(tmp_path)
    assert include == [f"-I{tmp_path / 'include'}"]
    assert libraries == [f"-L{tmp_path / 'lib'}", "-lSDL3-static", "-lwinmm"]
