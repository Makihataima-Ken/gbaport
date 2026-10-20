"""mGBA as the reference picture and sound for the renderer and sound tests.

mGBA's GBA core is the spec's development-time oracle (MPL-2.0; nothing ships it). The
pinned source release is downloaded once (its SHA-256 checked) and built with CMake, Ninja
and clang, together with ``mgbaref/mgbaref.c``, which runs a ROM for some frames and
writes its picture and the samples it mixed. Both live in gbaport's cache folder (``$GBAPORT_CACHE``, by default the
user's), next to SDL3; a change to ``mgbaref/`` builds it again. A harness Windows refuses
to start is linked again with a new ``salt.c``, like every program the tests build.
"""

import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import gbaport.native.build as native
from gbaport.native.sdl3 import cache_folder
from gbaport.native.toolchain import ToolchainError, find_clang, find_cmake, find_ninja, llvm_tool

MGBA_VERSION = "0.10.5"
MGBA_URL = f"https://github.com/mgba-emu/mgba/archive/refs/tags/{MGBA_VERSION}.tar.gz"
MGBA_SHA256 = "91d6fbd32abcbdf030d58d3f562de25ebbc9d56040d513ff8e5c19bee9dacf14"
SOURCE = Path(__file__).parent / "mgbaref"


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
        raise ToolchainError(f"building mGBA's reference failed ({what}):\n{output}")


def mgbaref_program() -> Path:
    """The reference program, building it first if it is not there yet (again when its
    sources change)."""
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in sorted(SOURCE.iterdir()))).hexdigest()
    folder = cache_folder() / f"mgbaref-{MGBA_VERSION}-{digest[:8]}"
    program = folder / ("mgbaref.exe" if os.name == "nt" else "mgbaref")
    if (folder / "started").exists():  # written once Windows let it start
        return program
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
    salt.write_text('const char mgbaref_salt[] = "";\n', encoding="utf-8")
    _run(configure, "configure")
    for _ in range(native.SALTED_REBUILDS + 1):
        salt.write_text(f'const char mgbaref_salt[] = "{os.urandom(8).hex()}";\n', encoding="utf-8")
        _run([cmake, "--build", str(folder)], "build")
        if native._starts(program):
            (folder / "started").write_text("", encoding="utf-8")
            return program
    raise ToolchainError(f"Windows refused to start {program} after {native.SALTED_REBUILDS} rebuilds")


def _reference(rom: bytes, frames: int, sound: bool) -> tuple[bytes, bytes]:
    """mgbaref's picture and (with ``sound``) sound files after ``frames`` frames."""
    program = mgbaref_program()
    with tempfile.TemporaryDirectory() as scratch:
        rom_path, out = Path(scratch) / "game.gba", Path(scratch) / "picture.raw"
        sound_path = Path(scratch) / "sound.raw"
        rom_path.write_bytes(rom)
        command = [str(program), str(rom_path), str(frames), str(out)]
        result = subprocess.run(command + ([str(sound_path)] if sound else []),
                                capture_output=True, text=True, timeout=120, check=False)
        assert result.returncode == 0, f"mgbaref: {result.stderr}"
        return out.read_bytes(), sound_path.read_bytes() if sound else b""


def mgba_picture(rom: bytes, frames: int) -> list[int]:
    """mGBA's picture after ``frames`` frames: 240x160 GBA colours (0BBBBBGGGGGRRRRR),
    top row first."""
    return list(struct.unpack("<38400H", _reference(rom, frames, sound=False)[0]))


def mgba_sound(rom: bytes, frames: int) -> list[tuple[int, int]]:
    """The samples mGBA mixes in ``frames`` frames, 32768 a second: (left, right) pairs of
    signed 16-bit values, before mGBA resamples them for playback."""
    data = _reference(rom, frames, sound=True)[1][8:]  # mGBA's first 2 come before any
    values = struct.unpack(f"<{len(data) // 2}h", data)      # sound: its mixer starts late
    return list(zip(values[0::2], values[1::2], strict=True))
