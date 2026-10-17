# gbaport

Personal-use pipeline that turns a Game Boy Advance ROM dumped from your own cartridge
into native C, and from there into Android and iOS apps — with no emulator in the app.

Design: `docs/superpowers/specs/2026-10-17-gba-native-port-design.md`

**Never commit ROMs, saves, or anything extracted from them.** Put dumps in `roms/`
(gitignored).

## Setup

    uv sync

## Tests

    uv run pytest
    uv run ruff check src tests

## Commands

    uv run gbaport info roms/mygame.gba [--json]
    uv run gbaport disasm roms/mygame.gba --start 0x080000c0 --count 40 [--thumb]
    uv run gbaport analyze roms/mygame.gba [--config games/XXXX/game.toml] [--out build/analysis.json]
