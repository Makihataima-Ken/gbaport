from gdbfake import SESSION_RUN, FakeGdbServer, serve
from progkit import SESSION_PROGRAM, program_rom

from gbaport.analysis.traces import Hit, load_trace
from gbaport.cli import main
from gbaport.isa.model import Mode

ROM = program_rom(SESSION_PROGRAM)


def test_trace_records_into_the_games_folder_and_feeds_analyze(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(ROM.data)
    port = serve(FakeGdbServer(SESSION_RUN, rom=ROM.data))
    args = ["trace", str(rom), "--port", str(port), "--seconds", "30", "--reanalyze-every", "0"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"connected to 127.0.0.1:{port}" in out
    assert "wrote games" in out and "(2 hits)" in out
    trace = load_trace(tmp_path / "games" / "ATST" / "traces" / "mgba.trace")
    assert trace.hits == {
        Hit(0x080000C8, 0x080000D8, Mode.ARM),
        Hit(0x080000E4, 0x080000F0, Mode.ARM),
    }
    assert main(["analyze", str(rom)]) == 0
    assert "seed 1, trace 2, veneer 1" in capsys.readouterr().out


def test_trace_resumes_an_existing_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(ROM.data)
    out = tmp_path / "run.trace"
    for _ in range(2):
        port = serve(FakeGdbServer(SESSION_RUN, rom=ROM.data))
        args = ["trace", str(rom), "--port", str(port), "--out", str(out), "--reanalyze-every", "0"]
        assert main(args) == 0
    assert len(load_trace(out).hits) == 2
    assert "(2 hits)" in capsys.readouterr().out


def test_trace_refuses_a_different_rom_in_mgba(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(ROM.data)
    port = serve(FakeGdbServer(SESSION_RUN, rom=program_rom("bx lr").data))
    assert main(["trace", str(rom), "--port", str(port)]) == 1
    assert "different ROM" in capsys.readouterr().err
    assert not (tmp_path / "games").exists()


def test_trace_checks_its_output_file_before_connecting(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rom = tmp_path / "game.gba"
    rom.write_bytes(ROM.data)
    (tmp_path / "run.trace").write_text("gbaport-trace/1 " + "0" * 40 + "\n")
    assert main(["trace", str(rom), "--out", "run.trace", "--port", "9"]) == 1
    err = capsys.readouterr().err
    assert "run.trace" in err and "cannot connect" not in err
