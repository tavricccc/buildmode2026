"""Frame packets and the bounded ring buffer (docs/01_PIPELINE.md §Media ingest).

The buffer keeps only a short recent window — this is a care pipeline, not an
NVR. The ring buffer is fixed-capacity and overwrites the oldest frame,
so memory is bounded by ``capacity`` regardless of how long the process
runs or how far behind a consumer falls.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Generic, TypeVar


@dataclass(frozen=True)
class FramePacket:
    """One decoded frame, already JPEG-encoded for cheap handoff."""

    sequence: int
    captured_at_ms: int
    jpeg: bytes
    width: int
    height: int
    source_id: str
    #: ``rtsp`` or ``replay`` — both share this downstream contract (docs/01_PIPELINE.md).
    source_kind: str = "replay"
    #: Ground truth carried by *replay fixtures only*. A live RTSP frame
    #: never has one. Stub detectors and the stub model read it so a
    #: deterministic replay can exercise the cascade end to end; the real
    #: L1 and L2 adapters ignore it entirely.
    annotation: dict | None = None
    #: Optional PCM snapshot attached by the browser media bridge. Sources
    #: without audio leave it unset; the frame contract remains unchanged.
    audio_pcm: bytes | None = None
    #: Historical event time carried separately from wall-clock ingest time.
    #: Replay/upload processing still runs in real time, while persisted events
    #: can retain the time at which the recorded footage actually occurred.
    event_at_ms: int | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.jpeg)


T = TypeVar("T")


class RingBuffer(Generic[T]):
    """Thread-safe fixed-capacity buffer that drops the oldest item."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._items: list[T] = []
        self._lock = threading.Lock()
        self._dropped = 0

    def push(self, item: T) -> None:
        with self._lock:
            self._items.append(item)
            while len(self._items) > self._capacity:
                self._items.pop(0)
                self._dropped += 1

    def snapshot(self) -> list[T]:
        with self._lock:
            return list(self._items)

    def latest(self, n: int = 1) -> list[T]:
        with self._lock:
            return list(self._items[-n:])

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class FrameWindow:
    """The recent-frame view the cascade samples windows out of."""

    def __init__(self, capacity: int = 240) -> None:
        self.buffer: RingBuffer[FramePacket] = RingBuffer(capacity)
        self._sequence = 0
        self._lock = threading.Lock()

    def ingest(self, packet: FramePacket) -> None:
        self.buffer.push(packet)

    def reset(self) -> None:
        self.buffer.reset()
        with self._lock:
            self._sequence = 0

    def next_sequence(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def window(self, span_ms: int, now_ms: int, max_frames: int) -> list[FramePacket]:
        """Frames from the last ``span_ms``, evenly thinned to ``max_frames``.

        Thinning is stride-based rather than "take the last N" so a slow
        window still covers the whole time span instead of the tail only —
        a fall that happened at the start of the window must stay visible.
        """
        cutoff = now_ms - span_ms
        recent = [f for f in self.buffer.snapshot() if f.captured_at_ms >= cutoff]
        if len(recent) <= max_frames:
            return recent
        stride = len(recent) / float(max_frames)
        picked = [recent[min(int(i * stride), len(recent) - 1)] for i in range(max_frames)]
        # Always keep the final frame: it is the most recent state.
        if picked[-1] is not recent[-1]:
            picked[-1] = recent[-1]
        return picked

    def metrics(self) -> dict[str, int]:
        return {
            "frames": len(self.buffer),
            "capacity": self.buffer._capacity,
            "dropped": self.buffer.dropped,
        }
