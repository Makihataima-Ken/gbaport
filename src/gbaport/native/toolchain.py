"""Finding clang: $GBAPORT_CLANG, then PATH, then the LLVM installer's Windows location."""

import os
import shutil
from pathlib import Path

WINDOWS_LLVM = Path(r"C:\Program Files\LLVM\bin\clang.exe")


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
