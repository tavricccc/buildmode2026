"""Source protocol (v4 09).

Both ``RtspSource`` and ``ReplaySource`` implement ``SourceProtocol``
and produce the same ``FramePacket`` shape. Domain code never branches
on source kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

from ..domain.enums import SourceKind


@dataclass(frozen=True)
class FramePacket:
    sequence: int
    captured_at_ms: int
    jpeg_bytes: bytes
    width: int
    height: int
    source_kind: SourceKind


@dataclass(frozen=True)
class AudioPacket:
    sequence: int
    captured_at_ms: int
    pcm_bytes: bytes
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class SourceStatus:
    kind: SourceKind
    healthy: bool
    last_frame_seq: int
    last_frame_at_ms: int
    detail: str = ""


@runtime_checkable
class SourceProtocol(Protocol):
    kind: SourceKind

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> SourceStatus: ...
    def frames(self) -> AsyncIterator[FramePacket]: ...
