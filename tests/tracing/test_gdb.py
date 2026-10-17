import socket

import pytest

from gbaport.tracing.gdb import (
    GdbClient,
    GdbError,
    Registers,
    SocketTransport,
    Stop,
    packet,
)


class Wire:
    """A transport that hands out canned chunks and records what the client sent."""

    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)
        self.sent = bytearray()

    def send(self, data: bytes) -> None:
        self.sent += data

    def recv(self, timeout: float) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        pass


def reply(payload: str) -> bytes:
    return b"+" + packet(payload)


def test_packet_checksum():
    assert packet("g") == b"$g#67"
    assert packet("OK") == b"$OK#9a"


def test_reply_split_across_reads_with_stray_acks():
    whole = reply("OK")
    wire = Wire(b"++" + whole[:3], whole[3:])
    GdbClient(wire).set_breakpoint(0x08000100, 2)
    assert wire.sent == packet("Z0,8000100,2") + b"+"


def test_error_reply_raises():
    with pytest.raises(GdbError, match="failed: 'E07'"):
        GdbClient(Wire(reply("E07"))).clear_breakpoint(0x08000100, 4)


def test_bad_checksum_is_refused():
    wire = Wire(b"$OK#00")
    with pytest.raises(GdbError, match="bad checksum"):
        GdbClient(wire).request("g")
    assert wire.sent.endswith(b"-")


def test_no_reply_times_out():
    with pytest.raises(GdbError, match="no reply"):
        GdbClient(Wire()).request("g", timeout=0.01)


def test_registers_are_little_endian_words():
    words = list(range(15)) + [0x08000123, 0x6000003F]
    text = "".join(word.to_bytes(4, "little").hex() for word in words)
    regs = GdbClient(Wire(reply(text))).registers()
    assert regs == Registers(tuple(words[:16]), 0x6000003F)
    assert (regs.pc, regs.lr, regs.thumb) == (0x08000123, 14, True)


def test_short_register_reply_is_an_error():
    with pytest.raises(GdbError, match="unexpected register reply"):
        GdbClient(Wire(reply("E01"))).registers()


@pytest.mark.parametrize(
    "payload,stop",
    [
        ("S05", Stop(5)),  # a finished step
        ("S05k", Stop(5, breakpoint=True)),  # mGBA's breakpoint stop without hwbreak+
        ("T05hwbreak:;", Stop(5, breakpoint=True)),
        ("T05swbreak:;", Stop(5, breakpoint=True)),
        ("S02", Stop(2)),
        ("W00", Stop(0, exited=True)),
        ("X09", Stop(9, exited=True)),
    ],
)
def test_stop_replies(payload, stop):
    assert GdbClient(Wire(reply(payload))).wait_stop(0.01) == stop


def test_running_game_gives_no_stop():
    assert GdbClient(Wire()).wait_stop(0.01) is None


def test_unexpected_stop_reply_is_an_error():
    with pytest.raises(GdbError, match="unexpected stop reply"):
        GdbClient(Wire(reply("OK"))).wait_stop(0.01)


def test_escaped_bytes_are_decoded():
    escaped = b"a}" + bytes([ord("}") ^ 0x20]) + b"b"
    raw = b"$" + escaped + b"#" + f"{sum(escaped) & 0xFF:02x}".encode()
    assert GdbClient(Wire(raw)).request("qX") == "a}b"


def test_cont_step_and_interrupt_bytes():
    wire = Wire(reply("S05"))
    client = GdbClient(wire)
    client.cont()
    client.interrupt()
    assert client.step(0.01) == Stop(5)
    assert wire.sent == packet("c") + b"\x03" + packet("s") + b"+"


def test_socket_transport():
    near, far = socket.socketpair()
    transport = SocketTransport(near)
    far.sendall(reply("OK"))
    assert transport.recv(1.0) == reply("OK")
    assert transport.recv(0.01) == b""
    far.close()
    with pytest.raises(GdbError, match="closed the connection"):
        transport.recv(1.0)
    transport.close()


def test_connect_failure_says_how_to_start_the_server():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(GdbError, match="Start GDB server"):
        SocketTransport.connect("127.0.0.1", port, timeout=0.5)


def test_only_a_plain_s05_is_a_finished_step():
    assert Stop(5).step
    assert not Stop(5, breakpoint=True).step
    assert not Stop(2).step
    assert not Stop(0, exited=True).step


def test_halt_drops_stale_replies_up_to_the_s02():
    wire = Wire(reply("T05hwbreak:;") + reply("0102") + reply("S02"), reply("OK"))
    client = GdbClient(wire)
    client.halt()
    assert wire.sent.startswith(bytes([0x03]))
    assert client.request("qX") == "OK"


def test_halt_gives_up_quietly_when_nothing_answers():
    GdbClient(Wire()).halt(timeout=0.01)


def test_read_memory():
    wire = Wire(reply("0102ff"))
    assert GdbClient(wire).read_memory(0x08000000, 3) == bytes([1, 2, 0xFF])
    assert wire.sent.startswith(packet("m8000000,3"))
    with pytest.raises(GdbError, match="cannot read 3 bytes at 0x08000000"):
        GdbClient(Wire(reply("E01"))).read_memory(0x08000000, 3)
