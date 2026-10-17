import io
import json
import sys

import pytest
from romkit import build_rom

from gbaport import __version__
from gbaport.cli import main


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"gbaport {__version__}"


def test_missing_command_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def write_rom(tmp_path, **kwargs):
    path = tmp_path / "game.gba"
    path.write_bytes(build_rom(**kwargs))
    return path


def test_info_json_reports_header_and_save(tmp_path, capsys):
    path = write_rom(
        tmp_path, title=b"POCKETDEMO", game_code=b"APDE", patches={0x300: b"FLASH1M_V103"}
    )
    assert main(["info", str(path), "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["title"] == "POCKETDEMO"
    assert info["game_code"] == "APDE"
    assert info["entry_point"] == "0x080000c0"
    assert info["checksum_ok"] is True
    assert info["size"] == 0x400
    assert info["save_type"] == "flash128k"
    assert info["save_markers"] == ["FLASH1M_V103"]
    assert len(info["sha1"]) == 40


def test_info_text_output(tmp_path, capsys):
    assert main(["info", str(write_rom(tmp_path))]) == 0
    out = capsys.readouterr().out
    assert "title" in out and "TESTGAME" in out


def test_info_missing_file_fails_cleanly(tmp_path, capsys):
    assert main(["info", str(tmp_path / "nope.gba")]) == 1
    assert capsys.readouterr().err.startswith("error:")


def test_info_rejects_non_rom(tmp_path, capsys):
    path = tmp_path / "junk.gba"
    path.write_bytes(bytes(0x400))
    assert main(["info", str(path)]) == 1
    assert "not a GBA ROM" in capsys.readouterr().err


def test_info_text_survives_non_ascii_title_on_legacy_console(tmp_path, monkeypatch):
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    assert main(["info", str(write_rom(tmp_path, title=b"POK\xe9MON"))]) == 0
    stream.flush()
    assert b"POK\\xe9MON" in stream.buffer.getvalue()
