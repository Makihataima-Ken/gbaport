"""SDL3 for the window host: built once from source with CMake and Ninja, then reused.

CMake's FetchContent downloads the pinned source release and checks its SHA-256
(``sdl3_superbuild/CMakeLists.txt``); clang builds it as a static library, installed into
the cache folder, so every game links the same build. The cache folder is ``$GBAPORT_CACHE`` or the user's
cache folder (``%LOCALAPPDATA%\\gbaport`` on Windows).
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

SDL3_VERSION = "3.4.18"
SDL3_URL = (
    f"https://github.com/libsdl-org/SDL/releases/download/release-{SDL3_VERSION}/"
    f"SDL3-{SDL3_VERSION}.tar.gz"
)
SDL3_SHA256 = "9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3"
SUPERBUILD = Path(__file__).parent / "sdl3_superbuild"


def cache_folder() -> Path:
    if os.environ.get("GBAPORT_CACHE"):
        return Path(os.environ["GBAPORT_CACHE"])
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "gbaport"


def sdl3_prefix(log: Callable[[str], None] = print) -> Path:
    """The folder SDL3 is installed in, building it first if it is not there yet."""
    prefix = cache_folder() / f"sdl3-{SDL3_VERSION}"
    if (prefix / "lib" / "pkgconfig" / "sdl3.pc").exists():
        return prefix
    log(f"building SDL3 {SDL3_VERSION} into {prefix} (once; it takes a minute or two)")
    work = cache_folder() / f"sdl3-{SDL3_VERSION}-build"
    shutil.rmtree(work, ignore_errors=True)
    cmake = find_cmake()
    configure = [
        cmake, "-S", str(SUPERBUILD), "-B", str(work), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={_forward(find_ninja())}", f"-DCMAKE_C_COMPILER={_forward(find_clang())}",
        "-DCMAKE_BUILD_TYPE=Release", f"-DCMAKE_INSTALL_PREFIX={_forward(prefix)}",
        f"-DGBAPORT_SDL3_URL={SDL3_URL}", f"-DGBAPORT_SDL3_SHA256={SDL3_SHA256}",
    ]
    if os.name == "nt":  # clang's GNU-style driver needs LLVM's resource compiler
        configure.append(f"-DCMAKE_RC_COMPILER={_forward(llvm_tool('llvm-rc'))}")
    for command in (configure, [cmake, "--build", str(work)], [cmake, "--install", str(work)]):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output = (result.stdout + result.stderr)[-4000:]
            raise ToolchainError(f"building SDL3 failed ({command[1]} {command[2]}):\n{output}")
    shutil.rmtree(work, ignore_errors=True)
    return prefix


def sdl3_flags(prefix: Path) -> tuple[list[str], list[str]]:
    """The compile and link flags for the SDL3 in ``prefix`` (from its sdl3.pc)."""
    libs = []
    for line in (prefix / "lib" / "pkgconfig" / "sdl3.pc").read_text(encoding="utf-8").splitlines():
        if line.startswith("Libs:"):
            libs = [flag for flag in line.split()[1:] if not flag.startswith("-L")]
    return [f"-I{prefix / 'include'}"], [f"-L{prefix / 'lib'}", *libs]


def _forward(path: str | Path) -> str:
    """A path for a CMake -D value: CMake reads backslashes as escapes."""
    return Path(path).as_posix()
