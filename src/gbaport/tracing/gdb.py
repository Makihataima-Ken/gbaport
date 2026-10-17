"""A small GDB remote serial protocol client, enough to drive mGBA's GDB server.

mGBA (Tools > Start GDB server, default port 2345) speaks a subset of the
protocol: ``g`` returns r0-r15 and the CPSR, ``Z0``/``z0`` set and clear
breakpoints, ``c`` and ``s`` continue and step, and a raw 0x03 byte stops a
running game. It acknowledges every packet with ``+`` (even in no-ack mode),
so the client skips stray ``+`` bytes, and it may answer a breakpoint with
``S05k``, so stop replies are read by their first three characters only.
"""

import socket
from dataclasses import dataclass
from typing import Protocol

REPLY_TIMEOUT = 5.0  # seconds to wait for the answer to a request


class GdbError(ConnectionError):
    """The GDB server went away, timed out or answered something unexpected."""


class Transport(Protocol):
    def send(self, data: bytes) -> None: ...

    def recv(self, timeout: float) -> bytes:
        """Bytes that arrived within ``timeout`` seconds (b"" if none); raises when closed."""
        ...

    def close(self) -> None: ...


class SocketTransport:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    @classmethod
    def connect(cls, host: str, port: int, timeout: float = REPLY_TIMEOUT) -> "SocketTransport":
        try:
            return cls(socket.create_connection((host, port), timeout=timeout))
        except OSError as exc:
            raise GdbError(
                f"cannot connect to a GDB server at {host}:{port} ({exc}); "
                "in mGBA use Tools > Start GDB server"
            ) from None

    def send(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise GdbError(f"connection lost: {exc}") from None

    def recv(self, timeout: float) -> bytes:
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except TimeoutError:
            return b""
        except OSError as exc:
            raise GdbError(f"connection lost: {exc}") from None
        if not data:
            raise GdbError("the GDB server closed the connection")
        return data

    def close(self) -> None:
        self.sock.close()


@dataclass(frozen=True)
class Stop:
    signal: int  # 5 = trap (breakpoint or step), 2 = interrupt
    exited: bool = False  # the game (or emulator core) ended


@dataclass(frozen=True)
class Registers:
    r: tuple[int, ...]  # r0-r15; r15 is the address of the next instruction to run
    cpsr: int

    @property
    def pc(self) -> int:
        return self.r[15]

    @property
    def lr(self) -> int:
        return self.r[14]

    @property
    def thumb(self) -> bool:
        return bool(self.cpsr & 0x20)


def packet(payload: str) -> bytes:
    data = payload.encode("ascii")
    return b"$" + data + b"#" + f"{sum(data) & 0xFF:02x}".encode("ascii")


class GdbClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self.buffer = bytearray()

    def handshake(self) -> None:
        self.request("qSupported:swbreak+;hwbreak+")

    def request(self, payload: str, timeout: float = REPLY_TIMEOUT) -> str:
        self.transport.send(packet(payload))
        reply = self._receive(timeout)
        if reply is None:
            raise GdbError(f"no reply to {payload!r} within {timeout:g}s")
        return reply

    def registers(self) -> Registers:
        reply = self.request("g")
        if len(reply) < 17 * 8:
            raise GdbError(f"unexpected register reply {reply[:20]!r}")
        words = [int.from_bytes(bytes.fromhex(reply[i : i + 8]), "little") for i in range(0, 136, 8)]
        return Registers(tuple(words[:16]), words[16])

    def set_breakpoint(self, addr: int, size: int) -> None:
        self._expect_ok(f"Z0,{addr:x},{size}")

    def clear_breakpoint(self, addr: int, size: int) -> None:
        self._expect_ok(f"z0,{addr:x},{size}")

    def cont(self) -> None:
        """Resume; the stop reply comes later through ``wait_stop``."""
        self.transport.send(packet("c"))

    def step(self, timeout: float = REPLY_TIMEOUT) -> Stop | None:
        self.transport.send(packet("s"))
        return self.wait_stop(timeout)

    def interrupt(self) -> None:
        self.transport.send(b"\x03")

    def wait_stop(self, timeout: float) -> Stop | None:
        """The next stop reply, or None if the game is still running after ``timeout``."""
        reply = self._receive(timeout)
        if reply is None:
            return None
        if reply[:1] in ("W", "X"):
            return Stop(int(reply[1:3] or "0", 16), exited=True)
        if reply[:1] in ("S", "T") and len(reply) >= 3:
            return Stop(int(reply[1:3], 16))
        raise GdbError(f"unexpected stop reply {reply!r}")

    def close(self) -> None:
        self.transport.close()

    def _expect_ok(self, payload: str) -> None:
        reply = self.request(payload)
        if reply != "OK":
            raise GdbError(f"{payload!r} failed: {reply!r}")

    def _receive(self, timeout: float) -> str | None:
        """The payload of the next packet (acknowledged), or None if none arrives in time."""
        while True:
            parsed = self._take_packet()
            if parsed is not None:
                return parsed
            data = self.transport.recv(timeout)
            if not data:
                return None
            self.buffer += data

    def _take_packet(self) -> str | None:
        start = self.buffer.find(b"$")
        if start < 0:
            self.buffer.clear()  # only acks (or noise) so far
            return None
        end = self.buffer.find(b"#", start)
        if end < 0 or len(self.buffer) < end + 3:
            del self.buffer[:start]
            return None
        body = bytes(self.buffer[start + 1 : end])
        checksum = bytes(self.buffer[end + 1 : end + 3])
        del self.buffer[: end + 3]
        if f"{sum(body) & 0xFF:02x}".encode("ascii") != checksum.lower():
            self.transport.send(b"-")
            raise GdbError(f"bad checksum on packet {body[:20]!r}")
        self.transport.send(b"+")
        return _unescape(body).decode("ascii", errors="replace")


def _unescape(body: bytes) -> bytes:
    out = bytearray()
    escaped = False
    for byte in body:
        if escaped:
            out.append(byte ^ 0x20)
            escaped = False
        elif byte == 0x7D:  # '}'
            escaped = True
        else:
            out.append(byte)
    return bytes(out)
