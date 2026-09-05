"""Vision pipeline service stub (v4 03).

The full pipeline (sample → model call → state machine) lands in a
later commit. This round exposes a typed surface that the API can
already use.
"""

from __future__ import annotations

import json
from typing import Any

from ..adapters.frame_buffer import BoundedRingBuffer
from ..adapters.source_protocol import FramePacket


class VisionPipelineService:
    def __init__(self) -> None:
        self._ring = BoundedRingBuffer[FramePacket](max_items=128)

    def ingest(self, packet: FramePacket) -> None:
        self._ring.push(packet)

    def recent(self, n: int = 8) -> list[FramePacket]:
        snap = self._ring.snapshot()
        return snap[-n:]

    def metrics(self) -> dict[str, int]:
        return {"frames": len(self._ring), "capacity": self._ring.capacity()}

    def to_dict(self, packets: list[FramePacket]) -> list[dict[str, Any]]:
        return [
            {
                "sequence": p.sequence,
                "captured_at_ms": p.captured_at_ms,
                "width": p.width,
                "height": p.height,
                "source_kind": p.source_kind.value,
            }
            for p in packets
        ]
