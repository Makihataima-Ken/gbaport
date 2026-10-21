"""Test ROMs as Android apps.

``rom_apk(name)`` builds a test ROM's app for gbaport's emulator (x86_64). Every test ROM
goes through one Gradle project, so SDL3 and the runtime compile once and each app after
the first takes seconds; the APKs are cached by the hash of everything that goes in. All
test ROMs have the game code ATST, so they install as the same app (``APP``), one
replacing another.
"""

import hashlib
from pathlib import Path

from romtest import CACHE, build_test_rom

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import parse_config
from gbaport.lift.program import lift_program
from gbaport.native import android
from gbaport.native import build as native
from gbaport.rom.image import RomImage

APP = android.application_id("ATST")
FOLDER = CACHE / "android"


def rom_apk(name: str) -> Path:
    rom = build_test_rom(name)
    analysis = analyze_rom(RomImage(rom.data), parse_config(rom.config))
    files = native.generated_sources(lift_program(analysis.program, analysis.exploration),
                                     rom.data, analysis.save)
    digest = hashlib.sha1(rom.data)
    for file_name, text in sorted(files.items()):
        digest.update(f"{file_name}\n{text}".encode())
    inputs = [*native.RUNTIME.glob("*.[ch]"), *android.TEMPLATE.rglob("*"), Path(android.__file__)]
    for path in sorted(p for p in inputs if p.is_file()):
        digest.update(path.read_bytes())
    apk = FOLDER / "apks" / f"{digest.hexdigest()[:16]}.apk"
    if not apk.exists():
        native.write_sources(files, FOLDER / "generated")
        project = android.android_project(
            FOLDER / "generated", rom.data, FOLDER / "project", "ATST", "gbaport test",
            ("x86_64",), android.sdl3_source(), android.android_sdk())
        android.build_apk(project, apk)
    return apk
