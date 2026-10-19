"""jsmolka's GBA test ROMs (tests/publicroms/jsmolka/README.md), recompiled and run.

They come from tests/jsmolka.py. Each ROM runs its tests, shows the result and then idles. When the run reaches
its frame limit, a register (r12, r7 in thumb.gba) holds the number of the first test that
failed, 0 when all of them passed; as it is 0 too while the tests have not finished, the
picture must also be the one that says "All tests passed".
"""

import hashlib
import re

import pytest
import romtest
from jsmolka import jsmolka_rom

from gbaport.analysis.config import ConfigError

REGISTERS = {"thumb": 7}  # the register with the result: r12, except in thumb.gba
ALL_PASSED = "ae000eb0c97cf8ac296246c6d9eee1d1d2e1d428"  # SHA-1 of that picture's screenshot


@pytest.mark.parametrize(
    "name", ["arm", "thumb", "memory", "bios", "sram", "flash64", "flash128", "none"]
)
def test_jsmolka_rom_passes(name, tmp_path):
    shot = tmp_path / "screen.bmp"
    args = ("--registers", "--screenshot", str(shot))
    run = romtest.run_rom(jsmolka_rom(name), frames=120, args=args)
    assert run.status == 4, run.stderr
    register = REGISTERS.get(name, 12)
    failed = int(re.search(rf" r{register}=([0-9a-f]{{8}})", run.stderr).group(1), 16)
    assert failed == 0, f"{name}.gba: test {failed} failed"
    picture = hashlib.sha1(shot.read_bytes()).hexdigest()
    assert picture == ALL_PASSED, f"{name}.gba does not show 'All tests passed'"


def test_a_rom_that_is_not_the_one_its_config_names_is_refused():
    rom = jsmolka_rom("none")
    changed = romtest.TestRom(rom.data[:-1] + bytes([rom.data[-1] ^ 1]), rom.config)
    with pytest.raises(ConfigError, match="game.toml is for ROM sha1"):
        romtest.native_program(changed)
