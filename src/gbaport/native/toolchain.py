"""Finding the build tools.

clang: $GBAPORT_CLANG, then PATH, then the LLVM installer's Windows location. CMake and
Ninja (for SDL3): $GBAPORT_CMAKE / $GBAPORT_NINJA, then PATH, then the copies the Visual
Studio Build Tools bundle.
"""

import os
import shutil
from pathlib import Path

WINDOWS_LLVM = Path(r"C:\Program Files\LLVM\bin\clang.exe")
VISUAL_STUDIO_CMAKE = "Microsoft Visual Studio/*/*/Common7/IDE/CommonExtensions/Microsoft/CMake"
PROGRAM_FILES = (Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)"))


class ToolchainError(OSError):
    """A compiler or tool the build needs is missing or failed."""


def find_clang() -> str:
    found = os.environ.get("GBAPORT_CLANG") or shutil.which("clang")
    if found:
        return found
    if WINDOWS_LLVM.exists():
        return str(WINDOWS_LLVM)
    raise ToolchainError("clang not found: install LLVM (winget install LLVM.LLVM) or set GBAPORT_CLANG")


def llvm_tool(name: str) -> str:
    """Another LLVM tool (ld.lld, llvm-objcopy) from the directory clang is in."""
    folder = Path(find_clang()).parent
    for candidate in (folder / f"{name}.exe", folder / name):
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise ToolchainError(f"{name} not found next to clang ({folder})")


def _bundled(relative: str) -> str | None:
    """A tool inside a Visual Studio installation's CMake folder, if there is one."""
    for root in PROGRAM_FILES:
        for candidate in sorted(root.glob(f"{VISUAL_STUDIO_CMAKE}/{relative}"), reverse=True):
            return str(candidate)
    return None


def find_cmake() -> str:
    found = os.environ.get("GBAPORT_CMAKE") or shutil.which("cmake") or _bundled("CMake/bin/cmake.exe")
    if found:
        return found
    raise ToolchainError("CMake not found: winget install Kitware.CMake, or set GBAPORT_CMAKE")


def find_ninja() -> str:
    found = os.environ.get("GBAPORT_NINJA") or shutil.which("ninja") or _bundled("Ninja/ninja.exe")
    if found:
        return found
    raise ToolchainError("Ninja not found: winget install Ninja-build.Ninja, or set GBAPORT_NINJA")
