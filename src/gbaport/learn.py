"""gbaport learn: the code a recorded run of the game missed, found by playing it again.

The window and the phone record what they play (the hosts' ``--record``): the keys the game
was given, as an input file, and the save it started from next to it. Played again from
that save, the native game does exactly what it did, so a run that stopped at code the
recompiler did not find stops there again. ``learn`` builds the game (headless), replays
the recording and, each time the replay stops at missing code, adds the address to the
game's learned entries (``games/<game_code>/learned.toml``), builds again and replays
again, until the replay gets through. Rebuilds compile only the code files that changed.
"""

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from gbaport.analysis.analyze import analyze_rom
from gbaport.analysis.config import GameConfig, load_learned, write_learned
from gbaport.analysis.traces import Trace
from gbaport.isa.model import Mode
from gbaport.lift.program import lift_program
from gbaport.native.build import compile_native, generated_sources, write_sources
from gbaport.rom.image import RomImage
from gbaport.rom.info import inspect_rom

# runtime.c's gba_missing
MISS = re.compile(r"no recompiled code at 0x([0-9a-f]{8}) \((Thumb|ARM) state, lr = 0x[0-9a-f]{8}, "
                  r"frame (\d+)\)")
ENDED = re.compile(r"# ended at frame (\d+)(?:: (.*))?")  # host_finish's last line
MOST = 500  # addresses one run learns before it gives up
REPLAY_TIMEOUT = 3600  # seconds


class LearnError(ValueError):
    """The replay stopped for another reason than missing code, or learning did not help."""


@dataclass(frozen=True)
class Learned:
    addr: int
    mode: Mode
    frame: int  # where the replay stopped at it


def learn(rom_path: Path, rom: RomImage, config: GameConfig, traces: tuple[Trace, ...],
          learned: Path, recording: Path, start_save: Path | None, frames: int, work: Path,
          log: Callable[[str], None] = print) -> list[Learned]:
    """Replays ``recording`` (from ``start_save``, or a blank save) for at most ``frames``
    frames, learning into ``learned`` each address it stops at; returns what it learned.
    ``work`` holds the build (kept, so the next run compiles less)."""
    sha1 = inspect_rom(rom).sha1
    arm, thumb = (list(found) for found in (load_learned(learned, sha1) if learned.exists() else ((), ())))
    found: list[Learned] = []
    for _ in range(MOST):
        program = _build(rom, config.with_entries(tuple(arm), tuple(thumb)), traces, work)
        stopped = _replay(program, rom_path, recording, start_save, frames)
        miss = MISS.search(stopped)
        if miss is None:
            if stopped:
                raise LearnError(f"the replay stopped: {stopped}")
            return found
        item = Learned(int(miss.group(1), 16), Mode.THUMB if miss.group(2) == "Thumb" else Mode.ARM,
                       int(miss.group(3)))
        entries = thumb if item.mode is Mode.THUMB else arm
        if item.addr in entries:  # learning it did not help: it goes again
            entries.remove(item.addr)
            write_learned(learned, sha1, arm, thumb)
            raise LearnError(f"{learned} has 0x{item.addr:08x} already, but it is still missing: "
                             f"{_why_missing(item.addr, len(rom.data))} ({stopped})")
        entries.append(item.addr)
        write_learned(learned, sha1, arm, thumb)
        found.append(item)
        log(f"learned 0x{item.addr:08x} ({'Thumb' if item.mode is Mode.THUMB else 'ARM'}), "
            f"missing at frame {item.frame}")
    raise LearnError(f"gave up after learning {MOST} addresses in one run")


def _why_missing(addr: int, rom_size: int) -> str:
    """Why learning ``addr`` could not help, and what might."""
    region = addr >> 24
    if region in (0x02, 0x03):
        return ("the game runs it from RAM: add a [[ram_code]] entry to game.toml for the ROM "
                "bytes it copies there")
    if 0x08 <= region <= 0x0D and addr & 0x01FFFFFF >= rom_size:
        return ("it is past the end of the ROM, so there is no code there: the game went "
                "somewhere it should not have (a recording made with another build can do that)")
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
            frames: int) -> str:
    """The runtime error the replay ended with, or "" when it played to its end."""
    with tempfile.TemporaryDirectory() as folder:
        save = Path(folder) / "game.sav"  # a copy: the replay must not change the start save
        if start_save is not None:
            shutil.copyfile(start_save, save)
        try:
            result = subprocess.run(
                [str(program), str(rom_path), "--input", str(recording), "--save", str(save),
                 "--frames", str(frames)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=REPLAY_TIMEOUT, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise LearnError(f"the replay took more than {REPLAY_TIMEOUT} s") from error
    if result.returncode in (0, 4):  # stopped with nothing to wake it, or the frame limit
        return ""
    if result.returncode != 3:  # bad arguments, an unusable save file, a crash
        raise LearnError(f"the replay could not run (exit status {result.returncode}): "
                         f"{result.stderr.strip()[-2000:]}")
    errors = [line for line in result.stderr.splitlines() if line.startswith("error: ")]
    return errors[-1].removeprefix("error: ") if errors else result.stderr.strip()
