"""Minimal RFC 6455 server for Dashboard push (v5 03).

v5 03 asks for WebSocket push with REST resync, and the backend is
standard-library-only, so the protocol is implemented here rather than
pulled in. The scope is deliberately small — this is a one-way telemetry
channel, not a general WebSocket library:

* server -> client text frames only;
* client frames are read solely to honour close and ping;
* no extensions, no fragmentation on send, no permessage-deflate.

Broadcast order matters and is guaranteed by the caller, not here: v5 03
requires the SQLite commit to happen *before* the frame goes out, so a
client that reacts to an event and immediately refetches cannot observe
a row that does not exist yet.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Any

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes, opcode: int = OP_TEXT) -> bytes:
    """Server-to-client frame: FIN set, never masked (RFC 6455 §5.1)."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    return bytes(header) + payload


def read_frame(sock: socket.socket) -> tuple[int, bytes] | None:
    """Read one client frame. Returns ``(opcode, payload)`` or ``None``."""
    header = _recv_exact(sock, 2)
    if header is None:
        return None
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F

    if length == 126:
        extended = _recv_exact(sock, 2)
        if extended is None:
            return None
        length = struct.unpack(">H", extended)[0]
    elif length == 127:
        extended = _recv_exact(sock, 8)
        if extended is None:
            return None
        length = struct.unpack(">Q", extended)[0]

    # A client frame must be masked; anything else is a protocol error we
    # treat as a disconnect rather than trying to recover from.
    if not masked:
        return None
    mask = _recv_exact(sock, 4)
    if mask is None:
        return None
    payload = _recv_exact(sock, length) if length else b""
    if payload is None:
        return None
    return opcode, bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _recv_exact(sock: socket.socket, count: int) -> bytes | None:
    buffer = bytearray()
    while len(buffer) < count:
        try:
            chunk = sock.recv(count - len(buffer))
        except (OSError, TimeoutError):
            return None
        if not chunk:
            return None
        buffer.extend(chunk)
    return bytes(buffer)


class Broadcaster:
    """Fan-out to every connected Dashboard.

    A client that cannot keep up is dropped, not buffered. Backpressure
    from a stalled browser tab must never reach the pipeline — the
    Dashboard's own REST resync is the recovery path (v5 03).
    """

    def __init__(self, history: int = 100) -> None:
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []
        self._history_limit = history
        self._sequence = 0
        self.sent = 0
        self.dropped = 0

    def add(self, sock: socket.socket) -> None:
        with self._lock:
            self._clients.append(sock)

    def remove(self, sock: socket.socket) -> None:
        with self._lock:
            if sock in self._clients:
                self._clients.remove(sock)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._sequence += 1
            message = {"seq": self._sequence, "topic": topic, "payload": payload}
            self._history.append(message)
            del self._history[: -self._history_limit]
            clients = list(self._clients)

        try:
            frame = encode_frame(json.dumps(message, default=str).encode("utf-8"))
        except (TypeError, ValueError):
            return

        stale: list[socket.socket] = []
        for client in clients:
            try:
                client.sendall(frame)
                self.sent += 1
            except OSError:
                stale.append(client)
                self.dropped += 1
        for client in stale:
            self.remove(client)
            try:
                client.close()
            except OSError:
                pass

    def backlog(self, after_seq: int = 0) -> list[dict[str, Any]]:
        """Messages a reconnecting client missed, for its resync."""
        with self._lock:
            return [m for m in self._history if m["seq"] > after_seq]

    def metrics(self) -> dict[str, Any]:
        return {
            "clients": self.client_count(),
            "sequence": self._sequence,
            "sent": self.sent,
            "dropped": self.dropped,
        }
