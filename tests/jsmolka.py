"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md) for the tests.

The ROMs are downloaded from the pinned commit the first time, checked against their
SHA-1 and cached with the other test ROMs; only their game.toml files are in the
repository.
"""

import hashlib
import urllib.request
from pathlib import Path

import romtest

CONFIGS = Path(__file__).parent / "publicroms" / "jsmolka"
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
    "hello": ("ppu/hello.gba", "813b7910a32be21a7baa08b1afcb7eaaf58a8b58"),
    "shades": ("ppu/shades.gba", "f4f81d3439c79362f416ccc1e94bac47429015f4"),
    "stripes": ("ppu/stripes.gba", "2c4682c47e19ffa7894399fb84e03b083261e7e7"),
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
