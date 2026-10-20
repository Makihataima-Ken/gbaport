"""gbaport-mgba --trace: the indirect transfers a game took in mGBA
(gbaport/tracing/transfers.py reads them)."""

import pytest
from romtest import build_test_rom

from gbaport.isa.model import Mode
from gbaport.native.mgba import run_mgba
from gbaport.tracing.transfers import Transfer, TransferError, load_transfers, parse_transfers


def transfers_of(name: str, tmp_path, frames: int = 30, input: str | None = None):
    rom = build_test_rom(name)
    (tmp_path / "game.gba").write_bytes(rom.data)
    input_file = None
    if input is not None:
        input_file = tmp_path / "game.input"
        input_file.write_text(input, encoding="utf-8")
    run_mgba(tmp_path / "game.gba", frames, input=input_file, trace=tmp_path / "game.transfers")
    return rom.symbols, load_transfers(tmp_path / "game.transfers")


def test_transfers_read_as_written():
    text = "080001f0 08000300 thumb 080001e5\n\n03000010 08000400 arm 08000123\n"
    assert parse_transfers(text) == {
        Transfer(0x080001F0, 0x08000300, Mode.THUMB, 0x080001E5),
        Transfer(0x03000010, 0x08000400, Mode.ARM, 0x08000123),
    }


@pytest.mark.parametrize("line", ["080001f0 08000300 thumb", "080001f0 08000300 jazz 0", "x y z w"])
def test_a_bad_transfer_line_says_which(line):
    with pytest.raises(TransferError, match="^game.transfers, line 2: expected 'SITE TARGET MODE LR'"):
        parse_transfers("080001f0 08000300 thumb 080001e5\n" + line + "\n", "game.transfers")


def test_mgba_records_calls_through_pointers(tmp_path):
    symbols, transfers = transfers_of("calls", tmp_path)
    went = {(t.target, t.mode) for t in transfers}
    assert (symbols["hidden_thumb"], Mode.THUMB) in went
    assert (symbols["hidden_arm"], Mode.ARM) in went
    assert symbols["hidden_pressed"] not in {t.target for t in transfers}  # A was not pressed


def test_mgba_records_what_the_keys_lead_to(tmp_path):
    symbols, transfers = transfers_of("calls", tmp_path, input="5 A\n")
    assert (symbols["hidden_pressed"], Mode.THUMB) in {(t.target, t.mode) for t in transfers}


def test_mgba_leaves_out_returns_to_calls_in_progress(tmp_path):
    """A return to the latest call is ordinary; one to an outer call skips the calls in
    between, which the runtime unwinds. Neither is recorded; returns elsewhere are."""
    symbols, transfers = transfers_of("tasks", tmp_path)
    targets = {t.target for t in transfers}
    assert {symbols["task_b"] & ~1, symbols["yield_b_resumes"], symbols["task_b_resumes"]} <= targets
    assert symbols["a_resumes"] not in targets  # back past the second task's calls
    assert not targets & {t.lr & ~1 for t in transfers}  # no return to where LR pointed


def test_mgba_traces_calls_that_never_return(tmp_path):
    """A bl used as a jump: the calls in progress pile up, and the oldest are forgotten."""
    symbols, transfers = transfers_of("bl_loop", tmp_path, frames=10)
    assert (symbols["main"] & ~1, Mode.THUMB) in {(t.target, t.mode) for t in transfers}


def test_mgba_writes_the_transfers_to_any_file_name(tmp_path):
    """Windows hands mGBA's program its arguments in UTF-16."""
    folder = tmp_path / "あ-ゲーム"
    folder.mkdir()
    symbols, transfers = transfers_of("calls", folder)
    assert symbols["hidden_thumb"] in {t.target for t in transfers}
