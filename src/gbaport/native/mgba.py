"""mGBA as gbaport's reference: the tests and ``gbaport verify`` compare with it.

mGBA's GBA core is the spec's development-time oracle (MPL-2.0; no game ships it). The
pinned source release is downloaded once (its SHA-256 checked) and built with CMake, Ninja
and clang, together with ``mgba_oracle/mgba.c``, into the cache folder next to SDL3 (see
``sdl3.cache_folder``); a change to ``mgba_oracle`` builds it again. A program Windows
refuses to start is linked again with a new ``salt.c``, like every program gbaport builds.
"""

import hashlib
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.sdl3 import cache_folder
from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

MGBA_VERSION = "0.10.5"
MGBA_URL = f"https://github.com/mgba-emu/mgba/archive/refs/tags/{MGBA_VERSION}.tar.gz"
MGBA_SHA256 = "91d6fbd32abcbdf030d58d3f562de25ebbc9d56040d513ff8e5c19bee9dacf14"
SOURCE = Path(__file__).parent / "mgba_oracle"
SOURCE_FILES = ("CMakeLists.txt", "mgba.c")
MGBA_TIMEOUT = 600  # seconds a run may take


class MgbaError(OSError):
    """mGBA could not run the ROM as asked (the command line reports it as an error)."""


def _source_release() -> Path:
    """The source tarball, downloaded once (CMake's own download is far slower)."""
    tarball = cache_folder() / f"mgba-{MGBA_VERSION}.tar.gz"
    if not tarball.exists():
        with urllib.request.urlopen(MGBA_URL, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != MGBA_SHA256:
            raise ToolchainError(f"{MGBA_URL} is not the expected mGBA {MGBA_VERSION} source")
        tarball.parent.mkdir(parents=True, exist_ok=True)
        partial = tarball.with_suffix(".partial")
        partial.write_bytes(data)
        partial.replace(tarball)
    return tarball


def _run(command: list[str], what: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output = (result.stdout + result.stderr)[-4000:]
        raise ToolchainError(f"building mGBA failed ({what}):\n{output}")


def mgba_program(log: Callable[[str], None] = print) -> Path:
    """The reference program, building it first if it is not there yet (again when its
    sources change)."""
    digest = hashlib.sha1(b"".join((SOURCE / name).read_bytes() for name in SOURCE_FILES))
    folder = cache_folder() / f"mgba-{MGBA_VERSION}-{digest.hexdigest()[:8]}"
    program = folder / ("gbaport-mgba.exe" if os.name == "nt" else "gbaport-mgba")
    if (folder / "started").exists():  # written once Windows let it start
        return program
    log(f"building mGBA {MGBA_VERSION} into {folder} (once; it takes a few minutes)")
    tarball = _source_release()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    cmake = find_cmake()
    configure = [
        cmake, "-S", str(SOURCE), "-B", str(folder), "-G", "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={Path(find_ninja()).as_posix()}",
        f"-DCMAKE_C_COMPILER={Path(find_clang()).as_posix()}", "-DCMAKE_BUILD_TYPE=Release",
        f"-DGBAPORT_MGBA_URL={tarball.as_posix()}", f"-DGBAPORT_MGBA_SHA256={MGBA_SHA256}",
    ]
    if os.name == "nt":  # clang's GNU-style driver needs LLVM's resource compiler
        configure.append(f"-DCMAKE_RC_COMPILER={Path(llvm_tool('llvm-rc')).as_posix()}")
    salt = folder / "salt.c"
    salt.write_text('const char mgba_salt[] = "";\n', encoding="utf-8")
    _run(configure, "configure")
    for _ in range(native.SALTED_REBUILDS + 1):
        salt.write_text(f'const char mgba_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _run([cmake, "--build", str(folder)], "build")
        if native._starts(program):
            (folder / "started").write_text("", encoding="utf-8")
            return program
    raise ToolchainError(f"Windows refused to start {program} after {native.SALTED_REBUILDS} rebuilds")


def run_mgba(rom: Path, frames: int, *, input: Path | None = None, picture: Path | None = None,
             sound: Path | None = None, hashes: Path | None = None,
             log: Callable[[str], None] = print) -> None:
    """Runs ``rom`` in mGBA for ``frames`` frames and writes what was asked for (see
    ``mgba_oracle/mgba.c``)."""
    command = [str(mgba_program(log)), str(rom), "--frames", str(frames)]
    for option, path in (("--input", input), ("--picture", picture), ("--sound", sound),
                         ("--hashes", hashes)):
        if path is not None:
            command += [option, str(path)]
    try:
        # the program writes UTF-8 (paths outside the ANSI code page)
        result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                                timeout=MGBA_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise MgbaError(f"mGBA did not finish {frames} frames in {MGBA_TIMEOUT} s") from None
    if result.returncode != 0:
        raise MgbaError(f"mGBA failed (exit status {result.returncode}): {result.stderr.strip()}")
