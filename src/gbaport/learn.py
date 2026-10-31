"""gbaport learn: the code a recorded run of the game ran in the interpreter, recompiled.

The window and the phone record what they play (the hosts' ``--record``): the keys the game
was given, as an input file, and the save it started from next to it. Code the build had not
recompiled ran in the interpreter (runtime/interp.c), and the hosts list where it did
(``--places``). Played again from that save, the native game does exactly what it did.
``learn`` builds the game (headless), replays the recording with a places file of its own,
adds every place it lists to the game's learned entries (``games/<game_code>/learned.toml``),
builds again and replays again, until nothing runs interpreted. A place that still runs
interpreted after it was learned (the analysis cannot recompile code there) leaves the
entries again and is reported. Rebuilds compile only the code files that changed.
"""

import re
import shutil
import subprocess
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import GameConfig, load_learned, write_learned
from gbaport.analysis.traces import Trace
from gbaport.isa.model import Mode
from gbaport.lift.program import lift_program
from gbaport.native.build import compile_native, generated_sources, write_sources
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom

PLACES_FORMAT = "gbaport-places/1"  # host_common.c's places file
PLACE = re.compile(r"(arm|thumb) ([0-9a-f]{8}) (\d+)")
ENDED = re.compile(r"# ended at frame (\d+)(?:: (.*))?")  # host_finish's last line
ROUNDS = 20  # builds and replays one run makes before it gives up
REPLAY_TIMEOUT = 3600  # seconds


class LearnError(ValueError):
    """The replay stopped with an error, or learning did not end."""


@dataclass(frozen=True)
class Place:
    addr: int
    mode: Mode
    frame: int  # where it first ran interpreted


@dataclass
class Learning:
    learned: list[Place] = field(default_factory=list)
    interpreted: list[tuple[Place, str]] = field(default_factory=list)  # and why it stays


def read_places(path: Path, crc32: int) -> list[Place]:
    """The places a host's places file lists, oldest first ([] for another ROM's)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split() != [PLACES_FORMAT, f"{crc32:08x}"]:
        return []
    places = []
    for line in lines[1:]:
        if found := PLACE.fullmatch(line.strip()):
            mode = Mode.THUMB if found.group(1) == "thumb" else Mode.ARM
            places.append(Place(int(found.group(2), 16), mode, int(found.group(3))))
    return places


def learn_places(places_file: Path, rom: RomImage, learned: Path) -> list[Place]:
    """Adds the places in the ROM that ``places_file`` lists to ``learned``; returns those it
    added. Places in RAM are left to ``learn``, which checks that learning them helps."""
    sha1 = inspect_rom(rom).sha1
    arm, thumb = (list(found) for found in (load_learned(learned, sha1) if learned.exists() else ((), ())))
    added = []
    for place in read_places(places_file, zlib.crc32(rom.data)):
        entries = thumb if place.mode is Mode.THUMB else arm
        if 0x08 <= place.addr >> 24 <= 0x0D and place.addr not in entries:
            entries.append(place.addr)
            added.append(place)
    if added:
        write_learned(learned, sha1, arm, thumb)
    return added


def learn(rom_path: Path, rom: RomImage, config: GameConfig, traces: tuple[Trace, ...],
          learned: Path, recording: Path, start_save: Path | None, frames: int, work: Path,
          log: Callable[[str], None] = print) -> Learning:
    """Replays ``recording`` (from ``start_save``, or a blank save) for at most ``frames``
    frames, learning into ``learned`` each place it ran interpreted, until none does.
    ``work`` holds the build (kept, so the next run compiles less)."""
    sha1 = inspect_rom(rom).sha1
    arm, thumb = (list(found) for found in (load_learned(learned, sha1) if learned.exists() else ((), ())))
    outcome, kept_interpreted = Learning(), set()
    for _ in range(ROUNDS):
        program = _build(rom, config.with_entries(tuple(arm), tuple(thumb)), traces, work)
        places = [p for p in _replay(program, rom_path, recording, start_save, frames)
                  if (p.addr, p.mode) not in kept_interpreted]
        new = []
        for place in places:
            entries = thumb if place.mode is Mode.THUMB else arm
            if place.addr in entries:  # learned, but still interpreted: it does not help
                entries.remove(place.addr)
                kept_interpreted.add((place.addr, place.mode))
                outcome.interpreted.append((place, _why_interpreted(place.addr)))
            else:
                entries.append(place.addr)
                new.append(place)
        if places:
            write_learned(learned, sha1, arm, thumb)
        if not new:
            return outcome
        for place in new:
            log(f"learned 0x{place.addr:08x} ({'Thumb' if place.mode is Mode.THUMB else 'ARM'}), "
                f"which first ran interpreted at frame {place.frame}")
        outcome.learned += new
    raise LearnError(f"gave up after {ROUNDS} rounds of learning")


def _why_interpreted(addr: int) -> str:
    """Why learning ``addr`` did not recompile it."""
    if addr >> 24 in (0x02, 0x03, 0x06):
        return ("the game runs it from RAM, from bytes the analysis does not know: add a "
                "[[ram_code]] entry to game.toml for the ROM bytes it copies there")
    return "the analysis cannot decode code there"


def recorded_end(recording: Path) -> tuple[int, str] | None:
    """(frame, why) from the recording's last ``# ended at frame N[: why]`` line, which the
    hosts write when a run ends ("" when it ended without an error); None when there is
    none (an app killed in the background)."""
    for line in reversed(recording.read_text(encoding="utf-8").splitlines()):
        if found := ENDED.fullmatch(line.strip()):
            return int(found.group(1)), found.group(2) or ""
    return None


def _build(rom: RomImage, config: GameConfig, traces: tuple[Trace, ...], work: Path) -> Path:
    analysis = analyze_rom(rom, config, traces)
    lifted = lift_program(analysis.program, analysis.exploration)
    write_sources(generated_sources(lifted, rom.data, analysis.save), work / "generated")
    return compile_native(work / "generated", work / "build", "learn", log=lambda _: None)


def _replay(program: Path, rom_path: Path, recording: Path, start_save: Path | None,
            frames: int) -> list[Place]:
    """The places the replay ran interpreted; a LearnError when it ended with an error."""
    with tempfile.TemporaryDirectory() as folder:
        save, places = Path(folder) / "game.sav", Path(folder) / "game.places"
        if start_save is not None:  # a copy: the replay must not change the start save
            shutil.copyfile(start_save, save)
        try:
            result = subprocess.run(
                [str(program), str(rom_path), "--input", str(recording), "--save", str(save),
                 "--frames", str(frames), "--places", str(places)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=REPLAY_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise LearnError(f"the replay took more than {REPLAY_TIMEOUT} s") from error
        if result.returncode == 3:  # a runtime error
            errors = [line for line in result.stderr.splitlines() if line.startswith("error: ")]
            raise LearnError(f"the replay stopped: "
                             f"{errors[-1].removeprefix('error: ') if errors else result.stderr.strip()}")
        if result.returncode not in (0, 4):  # bad arguments, an unusable save file, a crash
            raise LearnError(f"the replay could not run (exit status {result.returncode}): "
                             f"{result.stderr.strip()[-2000:]}")
        crc32 = zlib.crc32(rom_path.read_bytes())  # the CRC32 the runtime names the ROM by
        return read_places(places, crc32) if places.exists() else []
