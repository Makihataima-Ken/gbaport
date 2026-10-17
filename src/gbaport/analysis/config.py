"""Per-game overrides read from ``games/<game_code>/game.toml``.

The file holds addresses and counts only, never ROM bytes. Unknown keys are
errors so a typo cannot silently change the analysis.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from gbaport.isa.model import Mode
from gbaport.rom.savetype import SaveType


class ConfigError(ValueError):
    """game.toml is malformed or does not fit the ROM."""


@dataclass(frozen=True)
class RamCode:
    rom: int  # where the blob sits in the cartridge
    ram: int  # where the game copies it and runs it
    size: int
    mode: Mode


@dataclass(frozen=True)
class JumpTableOverride:
    at: int  # the instruction that jumps through the table
    table: int  # address of the first table entry
    count: int


@dataclass(frozen=True)
class GameConfig:
    rom_sha1: str | None = None
    save: SaveType | None = None
    entries: tuple[int, ...] = ()
    thumb_entries: tuple[int, ...] = ()
    data: tuple[tuple[int, int], ...] = ()  # [start, end) ranges that are never code
    jump_tables: tuple[JumpTableOverride, ...] = ()
    ram_code: tuple[RamCode, ...] = ()
    timing_model: str = "block"


_SECTIONS = {
    "rom": {"sha1", "save"},
    "code": {"entries", "thumb_entries", "data", "jump_tables"},
    "timing": {"model"},
}
_RAM_CODE_KEYS = {"rom", "ram", "size", "mode"}
_JUMP_TABLE_KEYS = {"at", "table", "count"}
_TIMING_MODELS = ("block", "frame")


def default_config_path(game_code: str, root: Path = Path(".")) -> Path | None:
    """``games/<game_code>/game.toml`` under ``root``, if it exists."""
    path = root / "games" / game_code / "game.toml"
    return path if path.is_file() else None


def load_config(path: str | Path) -> GameConfig:
    path = Path(path)
    return parse_config(path.read_text(encoding="utf-8"), str(path))


def parse_config(text: str, source: str = "game.toml") -> GameConfig:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: {exc}") from None
    _check_keys(doc, set(_SECTIONS) | {"ram_code"}, source)
    rom, code, timing = (_section(doc, name, source) for name in ("rom", "code", "timing"))
    return GameConfig(
        rom_sha1=_sha1(rom, source),
        save=_save(rom, source),
        entries=_addresses(code, "entries", source),
        thumb_entries=_addresses(code, "thumb_entries", source),
        data=_ranges(code, source),
        jump_tables=tuple(
            _jump_table(item, source) for item in _tables(code, "jump_tables", source)
        ),
        ram_code=tuple(_ram_code(item, source) for item in _tables(doc, "ram_code", source)),
        timing_model=_timing(timing, source),
    )


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")


def _section(doc: dict, name: str, source: str) -> dict:
    value = doc.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: [{name}] must be a table")
    _check_keys(value, _SECTIONS[name], f"{source} [{name}]")
    return value


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"{where}: expected a non-negative integer, got {value!r}")
    return value


def _addresses(table: dict, key: str, source: str) -> tuple[int, ...]:
    values = table.get(key, [])
    if not isinstance(values, list):
        raise ConfigError(f"{source}: {key} must be a list of addresses")
    return tuple(_int(value, f"{source}: {key}") for value in values)


def _ranges(table: dict, source: str) -> tuple[tuple[int, int], ...]:
    values = table.get("data", [])
    if not isinstance(values, list):
        raise ConfigError(f"{source}: data must be a list of [start, end] pairs")
    ranges = []
    for item in values:
        if not isinstance(item, list) or len(item) != 2:
            raise ConfigError(f"{source}: data entries must be [start, end] pairs, got {item!r}")
        start, end = (_int(value, f"{source}: data") for value in item)
        if start >= end:
            raise ConfigError(f"{source}: data range [{start:#x}, {end:#x}] is empty")
        ranges.append((start, end))
    return tuple(ranges)


def _tables(table: dict, key: str, source: str) -> list[dict]:
    items = table.get(key, [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ConfigError(f"{source}: {key} must be an array of tables")
    return items


def _required(item: dict, keys: set[str], where: str) -> None:
    _check_keys(item, keys, where)
    missing = sorted(keys - set(item))
    if missing:
        raise ConfigError(f"{where}: missing key(s): {', '.join(missing)}")


def _jump_table(item: dict, source: str) -> JumpTableOverride:
    where = f"{source} jump_tables"
    _required(item, _JUMP_TABLE_KEYS, where)
    count = _int(item["count"], where)
    if count == 0:
        raise ConfigError(f"{where}: count must be at least 1")
    return JumpTableOverride(
        at=_int(item["at"], where), table=_int(item["table"], where), count=count
    )


def _ram_code(item: dict, source: str) -> RamCode:
    where = f"{source} [[ram_code]]"
    _required(item, _RAM_CODE_KEYS, where)
    size = _int(item["size"], where)
    if size == 0:
        raise ConfigError(f"{where}: size must be at least 1")
    return RamCode(
        rom=_int(item["rom"], where),
        ram=_int(item["ram"], where),
        size=size,
        mode=_mode(item["mode"], where),
    )


def _mode(value: object, where: str) -> Mode:
    if value not in ("arm", "thumb"):
        raise ConfigError(f'{where}: mode must be "arm" or "thumb", got {value!r}')
    return Mode(value)


def _sha1(rom: dict, source: str) -> str | None:
    value = rom.get("sha1")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 40:
        raise ConfigError(f"{source}: [rom] sha1 must be a 40-character hex string")
    return value.lower()


def _save(rom: dict, source: str) -> SaveType | None:
    value = rom.get("save")
    if value is None:
        return None
    try:
        return SaveType(value)
    except ValueError:
        names = ", ".join(save.value for save in SaveType)
        raise ConfigError(f"{source}: [rom] save must be one of {names}, got {value!r}") from None


def _timing(timing: dict, source: str) -> str:
    model = timing.get("model", "block")
    if model not in _TIMING_MODELS:
        raise ConfigError(f'{source}: [timing] model must be "block" or "frame", got {model!r}')
    return model
