"""The window host plays the sound through SDL: on the default device, at the device's
rate. SDL's "disk" sound driver stands in for a sound card here: it plays in real time
into a file, at SDL's default rate, 44100 samples a second."""

import array
import statistics
from itertools import pairwise

from romtest import build_test_rom, run_rom
from soundtest import our_sound, read_wav, script

TONE_HZ = 131072 / (2048 - 1750)  # channel 2 at frequency 1750: about 440 Hz
TONE = [(0, 0x084, 0x0080), (0, 0x080, 0x2277), (0, 0x082, 0x0002),
        (0, 0x068, 0xF080), (0, 0x06C, 0x8000 | 1750)]


DEVICE_RATE = 44100


def disk(path) -> dict[str, str]:
    return {"SDL_AUDIO_DRIVER": "disk", "SDL_AUDIO_DISK_OUTPUT_FILE": str(path)}


def test_the_window_plays_the_tone_at_its_pitch_on_a_44_khz_device(tmp_path):
    output = tmp_path / "device.raw"
    run = run_rom(build_test_rom("sound", script(TONE)), frames=150, host="sdl", env=disk(output))
    assert run.status == 4, run.stderr
    left = array.array("h", output.read_bytes())[0::2]
    seconds = len(left) / DEVICE_RATE
    assert 1.5 < seconds < 3.5  # 150 frames (2.5 s) went to the device as they came
    middle = left[len(left) // 4: 3 * len(left) // 4]  # past the start and the end
    mean = sum(middle) / len(middle)
    rises = [i for i, (a, b) in enumerate(pairwise(middle)) if a < mean <= b]
    periods = [b - a for a, b in pairwise(rises)]
    # A busy machine can leave the device without samples for a moment, and SDL fills the
    # gap with silence: the periods a gap stretches are left out.
    steady = [n for n in periods if n < 1.5 * statistics.median(periods)]
    assert sum(steady) > 0.75 * len(middle)
    # the stream plays up to 1% faster or slower to keep its queue (host_sound_speed)
    assert abs(DEVICE_RATE / statistics.fmean(steady) - TONE_HZ) < 0.015 * TONE_HZ


def test_the_window_runs_silent_without_a_sound_device():
    run = run_rom(build_test_rom("sound", script(TONE)), frames=20, host="sdl",
                  env={"SDL_AUDIO_DRIVER": "no-such-driver"})
    assert run.status == 4, run.stderr
    assert "warning: no sound:" in run.stderr


def test_the_window_plays_nothing_when_fast(tmp_path):
    output = tmp_path / "device.raw"
    run = run_rom(build_test_rom("sound", script(TONE)), frames=60, host="sdl",
                  args=("--fast",), env=disk(output))
    assert run.status == 4, run.stderr
    assert not output.exists() or not any(output.read_bytes())


def test_the_window_writes_the_sound_file_the_headless_host_writes(tmp_path):
    rom = build_test_rom("sound", script(TONE))
    window = tmp_path / "window.wav"
    run = run_rom(rom, frames=30, host="sdl", args=("--audio", str(window)))
    assert run.status == 4, run.stderr
    assert read_wav(window) == our_sound(rom, 30)
