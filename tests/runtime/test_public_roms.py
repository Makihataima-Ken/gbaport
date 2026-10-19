"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md), recompiled and run.

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository. Each ROM runs its tests and then idles; when the run reaches its frame limit,
r12 holds the number of the first test that failed, 0 when all of them passed.
"""

import hashlib
import re
import urllib.request
from pathlib import Path

import pytest
import romtest

from gbaport.analysis.config import ConfigError

CONFIGS = Path(__file__).parent.parent / "publicroms" / "jsmolka"
COMMIT = "a7113b67e63f83a9b321696ddd7042ccfad6c881"
SOURCE = f"https://raw.githubusercontent.com/jsmolka/gba-tests/{COMMIT}/"
ROMS = {  # name: (path in jsmolka's repository, SHA-1)
    "arm": ("arm/arm.gba", "753d7f40f50735bf13faab215cf9268f76cf9065"),
    "thumb": ("thumb/thumb.gba", "bdcf58182e9a99b388acba5fbca87ac31e8f58eb"),
    "memory": ("memory/memory.gba", "5f989b9a4017f16a431f76fd78a95e9799aa8fca"),
    "bios": ("bios/bios.gba", "a65b88f609aa3488add7fe331792f1e3ba3372b2"),
    "sram": ("save/sram.gba", "4fc95dc85cb68fdbc04c6689c9d62329582a1856"),
    "flash64": ("save/flash64.gba", "354fe3dba476b54b869cb44aeb6968fdd72dabd3"),
    "flash128": ("save/flash128.gba", "9396b0525ae548e524d50cd6c48ea3e15b092504"),
    "none": ("save/none.gba", "6ea4c58075159aa51c1feecd04f17efe3050b70a"),
}


def jsmolka_rom(name: str) -> romtest.TestRom:
    path, sha1 = ROMS[name]
    cached = romtest.CACHE / "jsmolka" / f"{name}.gba"
    if not cached.exists():
        with urllib.request.urlopen(SOURCE + path, timeout=60) as response:
            data = response.read()
        assert hashlib.sha1(data).hexdigest() == sha1, f"{SOURCE}{path} is not the expected file"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    config = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    return romtest.TestRom(cached.read_bytes(), config)


def failed_test(name: str) -> int:
    run = romtest.run_rom(jsmolka_rom(name), frames=120, args=("--registers",))
    assert run.status == 4, run.stderr
    return int(re.search(r" r12=([0-9a-f]{8})", run.stderr).group(1), 16)


@pytest.mark.parametrize(
    "name", ["memory", "bios", "none"]
)
def test_jsmolka_rom_passes(name):
    failed = failed_test(name)
    assert failed == 0, f"{name}.gba: test {failed} failed"


def test_a_rom_that_is_not_the_one_its_config_names_is_refused():
    rom = jsmolka_rom("none")
    changed = romtest.TestRom(rom.data[:-1] + bytes([rom.data[-1] ^ 1]), rom.config)
    with pytest.raises(ConfigError, match="game.toml is for ROM sha1"):
        romtest.native_program(changed)
