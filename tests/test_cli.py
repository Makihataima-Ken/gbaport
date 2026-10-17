import pytest

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
