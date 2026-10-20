"""Code takes as many cycles as in mGBA: the cycles test ROM times kinds of code with
timer 0 under four WAITCNT settings, natively and in mGBA, and draws the counts. An
interrupt takes about as long too."""

import pytest
from mgbaref import mgba_picture
from rendertest import our_picture
from romtest import build_test_rom

SETTINGS = ["0x0000", "0x4317", "0x0317", "0x4314"]  # default; fast, prefetch; no prefetch; BT4E's
SCENES = ["thumb alu", "thumb ldr iwram", "thumb ldr ewram", "thumb ldr rom", "thumb ldr vram",
          "thumb str iwram", "thumb str ewram", "thumb str vram", "thumb ldm/stm ewram",
          "thumb ldm/stm iwram", "thumb mul small", "thumb mul large", "thumb branches",
          "arm in rom", "arm in iwram"]


def drawn(picture: list[int], count: int) -> list[int]:
    """The counts a test ROM drew: two pixels each, bits 0-14 then 15-29."""
    return [picture[2 * k] | picture[2 * k + 1] << 15 for k in range(count)]


@pytest.fixture(scope="module")
def measured() -> tuple[list[int], list[int]]:
    rom, count = build_test_rom("cycles"), len(SETTINGS) * len(SCENES)
    return drawn(our_picture(rom, 10), count), drawn(mgba_picture(rom.data, 10), count)


@pytest.mark.parametrize("setting", range(len(SETTINGS)), ids=SETTINGS)
@pytest.mark.parametrize("scene", range(len(SCENES)), ids=SCENES)
def test_code_takes_as_many_cycles_as_in_mgba(measured, setting, scene):
    ours, mgba = measured
    k = setting * len(SCENES) + scene
    assert ours[k] == mgba[k]


def test_an_hblank_interrupt_slows_the_cpu_about_as_much_as_in_mgba():
    """Iterations of a busy loop over 40 lines, without and with an interrupt at every
    HBlank. Each interrupt costs here within 4 cycles of mGBA (README, Known limitations)."""
    rom = build_test_rom("hblank_irq")
    ours, mgba = drawn(our_picture(rom, 20), 3), drawn(mgba_picture(rom.data, 20), 3)
    assert ours[0] == mgba[0]  # no interrupts: the same loop
    assert ours[2] == mgba[2] == 41  # line 19's HBlank and the 40 after it
    cycles_a_loop = 40 * 1232 / mgba[0]
    assert abs(ours[1] - mgba[1]) * cycles_a_loop <= 4 * mgba[2]
