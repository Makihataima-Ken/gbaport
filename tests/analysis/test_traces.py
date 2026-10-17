import pytest

from gbaport.analysis.traces import (
    Hit,
    Trace,
    TraceError,
    default_trace_paths,
    format_trace,
    load_trace,
    parse_trace,
    save_trace,
    targets_by_site,
)
from gbaport.isa.model import Mode

SHA1 = "8dd4b6e95dca4554a919bff55128481a9a95b611"


def test_round_trip_is_sorted_and_deduplicated():
    trace = Trace(SHA1)
    assert trace.add(Hit(0x08000200, 0x08001000, Mode.THUMB))
    assert trace.add(Hit(0x08000100, 0x03000000, Mode.ARM))
    assert not trace.add(Hit(0x08000200, 0x08001000, Mode.THUMB))
    text = format_trace(trace)
    assert text == (
        f"gbaport-trace/1 {SHA1}\n"
        "08000100 03000000 arm\n"
        "08000200 08001000 thumb\n"
    )
    assert parse_trace(text) == trace


def test_comments_blank_lines_and_upper_case_are_accepted():
    text = f"# recorded in mGBA\n\ngbaport-trace/1 {SHA1.upper()}\n  # boot\n0800ABCD 08001000 thumb\n"
    trace = parse_trace(text)
    assert trace.sha1 == SHA1
    assert trace.hits == {Hit(0x0800ABCD, 0x08001000, Mode.THUMB)}


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "empty file"),
        ("gbaport-trace/2 " + SHA1, "header"),
        ("gbaport-trace/1 1234", "header"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001000", "expected 'site target mode'"),
        (f"gbaport-trace/1 {SHA1}\n08000100 zz thumb", "not a hex address"),
        (f"gbaport-trace/1 {SHA1}\n08000100 -4 arm", "not a 32-bit address"),
        (f"gbaport-trace/1 {SHA1}\n108000100 08001000 arm", "not a 32-bit address"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001000 thumb2", 'mode must be "arm" or "thumb"'),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001002 arm", "misaligned"),
        (f"gbaport-trace/1 {SHA1}\n08000100 08001001 thumb", "misaligned"),
    ],
)
def test_rejects_bad_traces(text, message):
    with pytest.raises(TraceError, match=message):
        parse_trace(text, "run.trace")


def test_errors_name_the_file_and_line():
    with pytest.raises(TraceError, match=r"run\.trace:3:"):
        parse_trace(f"gbaport-trace/1 {SHA1}\n\n08000100 zz arm\n", "run.trace")


def test_merge_requires_the_same_rom():
    trace = Trace(SHA1, {Hit(1 << 27, 1 << 27, Mode.ARM)})
    trace.merge(Trace(SHA1, {Hit(2, 4, Mode.ARM)}))
    assert len(trace.hits) == 2
    with pytest.raises(TraceError, match="cannot merge"):
        trace.merge(Trace("0" * 40))


def test_targets_by_site_combines_traces():
    first = Trace(SHA1, {Hit(0x100, 0x400, Mode.ARM), Hit(0x100, 0x300, Mode.THUMB)})
    second = Trace(SHA1, {Hit(0x100, 0x300, Mode.THUMB), Hit(0x200, 0x500, Mode.ARM)})
    assert targets_by_site([first, second]) == {
        0x100: ((0x300, Mode.THUMB), (0x400, Mode.ARM)),
        0x200: ((0x500, Mode.ARM),),
    }


def test_save_and_load(tmp_path):
    path = tmp_path / "games" / "ATST" / "traces" / "mgba.trace"
    trace = Trace(SHA1, {Hit(0x08000100, 0x08000200, Mode.THUMB)})
    save_trace(trace, path)
    assert load_trace(path) == trace
    assert not path.with_name("mgba.trace.tmp").exists()
    assert default_trace_paths("ATST", tmp_path) == [path]
    assert default_trace_paths("NONE", tmp_path) == []


def test_non_utf8_file_names_the_file(tmp_path):
    path = tmp_path / "bad.trace"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(TraceError, match="bad.trace"):
        load_trace(path)


def test_load_trace_checks_the_rom(tmp_path):
    path = tmp_path / "run.trace"
    save_trace(Trace(SHA1), path)
    assert load_trace(path, SHA1).sha1 == SHA1
    with pytest.raises(TraceError, match=r"run\.trace: recorded on ROM sha1 8dd4"):
        load_trace(path, "0" * 40)
