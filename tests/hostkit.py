"""Small C test programs built from runtime sources, once per version of those sources."""

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.toolchain import find_clang

TESTS = Path(__file__).parent


def host_program(name: str, sources: list[Path], headers: list[Path] = ()) -> Path:
    """``name`` compiled from ``sources`` with the runtime's headers, rebuilt with a salt when
    Windows' Smart App Control refuses to start it, as gbaport build does."""
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in (*sources, *headers))).hexdigest()[:16]
    folder = Path(tempfile.gettempdir()) / f"gbaport-{name}" / digest
    program = folder / (f"{name}.exe" if os.name == "nt" else name)
    if program.exists():
        return program
    folder.mkdir(parents=True, exist_ok=True)
    salt = folder / "salt.c"
    for _ in range(native.SALTED_REBUILDS):
        salt.write_text(f'const char {name}_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        subprocess.run(
            [find_clang(), "-std=c11", "-O2", "-Wall", "-Werror", f"-I{native.RUNTIME}",
             f"-I{native.PACKAGE / 'lift'}", *map(str, sources), str(salt), "-o", str(program)],
            check=True, capture_output=True,
        )
        if native._starts(program):
            return program
    raise AssertionError(f"Windows refused to start {name}")
