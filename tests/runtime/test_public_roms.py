"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md), recompiled and run.

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository. Each ROM runs its tests, shows the result and then idles. When the run reaches
its frame limit, a register (r12, r7 in thumb.gba) holds the number of the first test that
failed, 0 when all of them passed; as it is 0 too while the tests have not finished, the
picture must also be the one that says "All tests passed".
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
ROMS = {  # name: (path in jsmolka's repository, SHA-1, the register with the result)
    "arm": ("arm/arm.gba", "753d7f40f50735bf13faab215cf9268f76cf9065", 12),
    "thumb": ("thumb/thumb.gba", "bdcf58182e9a99b388acba5fbca87ac31e8f58eb", 7),
    "memory": ("memory/memory.gba", "5f989b9a4017f16a431f76fd78a95e9799aa8fca", 12),
    "bios": ("bios/bios.gba", "a65b88f609aa3488add7fe331792f1e3ba3372b2", 12),
    "sram": ("save/sram.gba", "4fc95dc85cb68fdbc04c6689c9d62329582a1856", 12),
    "flash64": ("save/flash64.gba", "354fe3dba476b54b869cb44aeb6968fdd72dabd3", 12),
    "flash128": ("save/flash128.gba", "9396b0525ae548e524d50cd6c48ea3e15b092504", 12),
    "none": ("save/none.gba", "6ea4c58075159aa51c1feecd04f17efe3050b70a", 12),
}
ALL_PASSED = "ae000eb0c97cf8ac296246c6d9eee1d1d2e1d428"  # SHA-1 of that picture's screenshot


def jsmolka_rom(name: str) -> romtest.TestRom:
    path, sha1, _ = ROMS[name]
    cached = romtest.CACHE / "jsmolka" / f"{name}.gba"
    if not cached.exists():
        with urllib.request.urlopen(SOURCE + path, timeout=60) as response:
            data = response.read()
        assert hashlib.sha1(data).hexdigest() == sha1, f"{SOURCE}{path} is not the expected file"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    config = (CONFIGS / f"{name}.toml").read_text(encoding="utf-8")
    return romtest.TestRom(cached.read_bytes(), config)


@pytest.mark.parametrize(
    "name", ["arm", "thumb", "memory", "bios", "sram", "flash64", "flash128", "none"]
)
def test_jsmolka_rom_passes(name, tmp_path):
    shot = tmp_path / "screen.bmp"
    args = ("--registers", "--screenshot", str(shot))
    run = romtest.run_rom(jsmolka_rom(name), frames=120, args=args)
    assert run.status == 4, run.stderr
    register = ROMS[name][2]
    failed = int(re.search(rf" r{register}=([0-9a-f]{{8}})", run.stderr).group(1), 16)
    assert failed == 0, f"{name}.gba: test {failed} failed"
    picture = hashlib.sha1(shot.read_bytes()).hexdigest()
    assert picture == ALL_PASSED, f"{name}.gba does not show 'All tests passed'"


def test_a_rom_that_is_not_the_one_its_config_names_is_refused():
    rom = jsmolka_rom("none")
    changed = romtest.TestRom(rom.data[:-1] + bytes([rom.data[-1] ^ 1]), rom.config)
    with pytest.raises(ConfigError, match="game.toml is for ROM sha1"):
        romtest.native_program(changed)
