"""Input files (gbaport/inputs.py): the keys held, frame by frame."""

import pytest

from gbaport.inputs import (
    InputError,
    Press,
    format_input,
    keys_from_names,
    load_input,
    parse_input,
)

TEXT = """\
# the title screen, then the menu
900 A
906 none

3900 RIGHT+A   # walk and hit
"""


def test_an_input_file_holds_its_keys_from_each_frame_on():
    assert parse_input(TEXT) == [Press(900, 0x001), Press(906, 0), Press(3900, 0x011)]


def test_an_input_file_reads_back_as_written():
    presses = parse_input(TEXT)
    assert format_input(presses) == "900 A\n906 none\n3900 A+RIGHT\n"
    assert parse_input(format_input(presses)) == presses


def test_key_names_are_the_hosts():
    assert keys_from_names("A+B+SELECT+START+RIGHT+LEFT+UP+DOWN+R+L") == 0x3FF
    assert keys_from_names("none") == 0


@pytest.mark.parametrize(("text", "message"), [
    ("900 A\nhello\n", "game.input, line 2: expected 'FRAME KEYS', got 'hello'"),
    ("900 A\n10 B\n", "game.input, line 2: frame 10 comes before frame 900"),
    ("900 JUMP\n", "game.input, line 1: unknown key 'JUMP'"),
    ("-5 A\n", "game.input, line 1: expected 'FRAME KEYS', got '-5 A'"),
])
def test_a_bad_input_file_says_which_line(text, message):
    with pytest.raises(InputError, match="^" + message.replace("(", r"\(").replace(")", r"\)")):
        parse_input(text, "game.input")


def test_an_input_file_saved_by_a_windows_editor_reads_the_same(tmp_path):
    """A UTF-8 byte order mark and CRLF line ends, as Notepad may write them."""
    path = tmp_path / "game.input"
    path.write_bytes(b"\xef\xbb\xbf# the title\r\n900 A\r\n906 none\r\n")
    assert load_input(path) == [Press(900, 0x001), Press(906, 0)]
