"""A scripted stand-in for mGBA's GDB server, used as a transport in tests.

The fake "runs" a fixed list of CPU states, each the address of the next
instruction with its mode, flags and LR. ``c`` moves to the next state whose
address has a breakpoint, ``s`` moves one state, and running off the end exits
the game (or, with ``endless``, keeps it running until interrupted). Replies
imitate mGBA's ``src/debugger/gdb-stub.c``:

- every packet is acknowledged with ``+``;
- every 0x03 byte is answered with ``S02``, even when the game is already halted;
- a breakpoint stop is ``T05hwbreak:;`` once the client advertised ``hwbreak+``
  (``S05k`` otherwise), and a finished step is ``S05``;
- with ``step_skips_bios``, a step into the BIOS (below 0x02000000) silently
  runs on to the next breakpoint, as mGBA 0.11 does;
- ``m`` reads the ``rom`` bytes mapped at 0x08000000; unknown packets get ``E07``.

Two hooks raise ``KeyboardInterrupt`` the way Ctrl+C would: ``raise_after``
(a packet prefix, once, after the packet was handled and answered) and
``interrupt_in_flight`` (once, when a stop happens while the client waits for
it, leaving that stop reply queued as on a real socket).
"""

import socket
import threading
from dataclasses import dataclass

from gbaport.tracing.gdb import GdbError, packet

USER_MODE = 0x1F  # system mode, where games run


@dataclass(frozen=True)
class State:
    pc: int
    thumb: bool = True
    lr: int = 0
    mode: int = USER_MODE
    flags: int = 0  # NZCV in bits 31-28


class FakeGdbServer:
    def __init__(
        self,
        states: list[State],
        *,
        endless: bool = False,
        lose_at: int | None = None,
        rom: bytes | None = None,
        step_skips_bios: bool = False,
        raise_after: str | None = None,
        interrupt_in_flight: bool = False,
    ) -> None:
        self.states = states
        self.index = 0
        self.endless = endless
        self.lose_at = lose_at  # index whose arrival drops the connection
        self.rom = rom
        self.step_skips_bios = step_skips_bios
        self.raise_after = raise_after
        self.interrupt_in_flight = interrupt_in_flight
        self.breakpoints: dict[int, int] = {}
        self.hwbreak = False
        self.running = False
        self.lost = False
        self.pending = bytearray()
        self.out = bytearray()

    def send(self, data: bytes) -> None:
        if self.lost:
            raise GdbError("connection lost")
        self.pending += data
        while self.pending:
            first = self.pending[0]
            if first in b"+-":
                del self.pending[:1]
            elif first == 0x03:
                del self.pending[:1]
                self.running = False
                self._reply("S02")
            else:
                end = self.pending.index(b"#")
                payload = self.pending[1:end].decode()
                del self.pending[: end + 3]
                self.out += b"+"
                self._handle(payload)
                if self.raise_after is not None and payload.startswith(self.raise_after):
                    self.raise_after = None
                    raise KeyboardInterrupt

    def recv(self, timeout: float) -> bytes:
        if self.running:
            self._run()
            if self.interrupt_in_flight and not self.running:
                self.interrupt_in_flight = False
                raise KeyboardInterrupt
        if self.lost:
            raise GdbError("connection lost")
        data = bytes(self.out)
        self.out.clear()
        return data

    def close(self) -> None:
        pass

    def _reply(self, payload: str) -> None:
        self.out += packet(payload)

    def _handle(self, payload: str) -> None:
        if payload.startswith("qSupported"):
            self.hwbreak = "hwbreak+" in payload
            self._reply("PacketSize=1000;swbreak+;hwbreak+")
        elif payload == "g":
            state = self.states[min(self.index, len(self.states) - 1)]
            cpsr = state.flags | state.mode | (0x20 if state.thumb else 0)
            words = [0] * 14 + [state.lr, state.pc, cpsr]
            self._reply("".join(word.to_bytes(4, "little").hex() for word in words))
        elif payload.startswith("m"):
            addr, length = (int(text, 16) for text in payload[1:].split(","))
            offset = addr - 0x08000000
            if self.rom is None or offset < 0 or offset + length > len(self.rom):
                self._reply("E01")
            else:
                self._reply(self.rom[offset : offset + length].hex())
        elif payload[:3] in ("Z0,", "z0,"):
            _, addr, size = payload.split(",")
            if payload[0] == "Z":
                self.breakpoints[int(addr, 16)] = int(size)
            else:
                self.breakpoints.pop(int(addr, 16), None)
            self._reply("OK")
        elif payload == "c":
            self.running = True
        elif payload == "s":
            self.index += 1
            if self.index >= len(self.states):
                self._reply("W00")
            elif self.step_skips_bios and self.states[self.index].pc < 0x02000000:
                self.running = True  # no reply: it comes from the next breakpoint
            else:
                self._reply("S05")
        else:
            self._reply("E07")

    def _run(self) -> None:
        if self.index >= len(self.states):
            return  # endless: still running past the last scripted state
        self.index += 1
        while self.index < len(self.states) and self.states[self.index].pc not in self.breakpoints:
            if self.index == self.lose_at:
                self.lost = True
                return
            self.index += 1
        if self.index == self.lose_at:
            self.lost = True
        elif self.index < len(self.states):
            self.running = False
            self._reply("T05hwbreak:;" if self.hwbreak else "S05k")
        elif not self.endless:
            self.running = False
            self._reply("W00")


def serve(server: FakeGdbServer) -> int:
    """Put ``server`` behind a real TCP socket on a free local port and return the port."""
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def bridge() -> None:
        connection, _ = listener.accept()
        listener.close()
        connection.settimeout(0.02)
        with connection:
            while True:
                try:
                    data = connection.recv(4096)
                    if not data:
                        return
                    server.send(data)
                except TimeoutError:
                    pass
                except OSError:
                    return
                out = server.recv(0)
                if out:
                    connection.sendall(out)

    threading.Thread(target=bridge, daemon=True).start()
    return port


# What the game does: reach the veneer from the bl, run target, reach its bx r0, go to second.
SESSION_RUN = [
    State(0x080000C0, thumb=False),
    State(0x080000D4, thumb=False, lr=0x080000CC),
    State(0x080000D8, thumb=False, lr=0x080000CC),
    State(0x080000DC, thumb=False),
    State(0x080000E0, thumb=False),
    State(0x080000E4, thumb=False, lr=0x080000E8),
    State(0x080000F0, thumb=False, lr=0x080000E8),
    State(0x080000E8, thumb=False),
]
