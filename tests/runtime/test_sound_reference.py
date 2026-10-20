"""mGBA as the sound's reference (tests/mgbaref.py, tests/soundtest.py), the hosts' --audio
WAV file, and the start-up the sound's timing counts from: line 126, as in mGBA."""

import pytest
import soundtest
from romtest import build_test_rom, run_rom
from soundtest import RATE, assert_script_matches, our_sound, sound_difference

QUIET = [(0, 0x088, 0x0200)]  # SOUNDBIAS as it already is


def test_silence_matches_mgba():
    assert_script_matches(QUIET)


def test_the_sound_file_holds_32768_samples_a_second_up_to_the_last_frame():
    sound = our_sound(build_test_rom("sound", soundtest.script(QUIET)), 60)
    # the first VBlank is 34 lines after the start (line 126, 117 cycles before its HBlank)
    last_vblank = (160 - 126) * 1232 - (1008 - 117) + 59 * 280896
    assert len(sound) == last_vblank // 512
    assert set(sound) == {(0, 0)}
    assert RATE == 32768


def test_the_audio_option_needs_a_writable_file(tmp_path):
    rom = build_test_rom("sound", soundtest.script(QUIET))
    run = run_rom(rom, frames=5, args=("--audio", str(tmp_path / "missing" / "x.wav")))
    assert run.status == 2
    assert "cannot write" in run.stderr


TONE = [((300 + i) % 600, (300 + i) % 600) for i in range(2000)]


@pytest.mark.parametrize("shift", [-16, -3, 0, 7, 16])
def test_a_sound_shifted_as_a_whole_is_the_same(shift):
    ours = TONE[100 + shift:1900 + shift]
    assert sound_difference(ours, TONE[100:1900]) is None


def test_a_change_may_move_by_two_samples():
    reference = [(0, 0)] * 500 + [(960, 960)] * 500
    ours = [(0, 0)] * 502 + [(960, 960)] * 498
    assert sound_difference(ours, reference) is None


def test_a_change_three_samples_late_is_a_difference():
    reference = [(0, 0)] * 500 + [(960, 960)] * 100 + [(0, 0)] * 400
    ours = [(0, 0)] * 500 + [(960, 960)] * 100 + [(0, 0)] * 400
    ours[600:603] = [(960, 960)] * 3  # the end of the burst three samples late
    difference = sound_difference(ours, reference)
    assert difference is not None and difference.startswith("2 of 964 samples differ")


def test_a_wrong_level_is_a_difference():
    reference = [(0, 0)] * 500 + [(960, 960)] * 500
    ours = [(0, 0)] * 500 + [(960, 480)] * 500
    assert sound_difference(ours, reference) == (
        "482 of 964 samples differ from mGBA's (shifted by 0), the first at 500 (0.0153 s): "
        "(960, 480) instead of (960, 960)")
