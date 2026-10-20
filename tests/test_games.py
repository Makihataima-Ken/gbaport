"""What the games folder keeps for each game (no ROM bytes: addresses, key names and frame
numbers) reads as gbaport reads it."""

from pathlib import Path

import pytest

from gbaport.analysis.config import load_config
from gbaport.analysis.traces import load_trace
from gbaport.inputs import load_input

GAMES = Path(__file__).parent.parent / "games"


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/game.toml")), ids=lambda p: p.parent.name)
def test_the_games_configs_read(path):
    load_config(path)


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/*.input")), ids=lambda p: p.name)
def test_the_games_input_files_read(path):
    assert load_input(path)


@pytest.mark.parametrize("path", sorted(GAMES.glob("*/traces/*.trace")),
                         ids=lambda p: f"{p.parent.parent.name}-{p.name}")
def test_the_games_traces_read(path):
    assert load_trace(path).hits


def test_the_users_game_has_its_way_into_the_first_fight():
    """The README's commands play 4200 frames of it."""
    assert load_input(GAMES / "BT4E" / "first-fight.input")[-1].frame < 4200
    assert load_trace(GAMES / "BT4E" / "traces" / "mgba.trace").hits
