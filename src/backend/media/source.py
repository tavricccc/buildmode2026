"""Frame-source protocol (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md: replay and RTSP share one contract)."""

from __future__ import annotations

from typing import Callable, Protocol

from .frames import FramePacket

FrameSink = Callable[[FramePacket], None]


class FrameSource(Protocol):
    """Anything that can push frames into the ring buffer.

    ReplaySource and RtspSource both satisfy this, which is what lets the
    whole cascade be exercised on a fixture on a laptop and then switched
    to a live camera without a downstream change (docs/04_SETUP_DEPLOY_VERIFY.md gate 1 vs 5).
    """

    source_id: str
    source_kind: str

    def start(self, sink: FrameSink) -> None: ...

    def stop(self) -> None: ...

    def health(self) -> dict[str, object]: ...
