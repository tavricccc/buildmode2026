"""Stub replay source.

In this round, ``ReplaySource`` produces synthetic frames so that the
vision loop, state machines, and event pipeline can be exercised
without a real camera. The synthetic frames are deterministic JPEG
bytes (a 1x1 image is enough — the gateway only validates the
multipart body).
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from ..domain.enums import SourceKind
from .frame_buffer import BoundedRingBuffer
from .source_protocol import FramePacket, SourceStatus


_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080607"
    "07070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b08000100010101000000ffc40015010100000000000000000000000000000000a0ffd9"
)


class ReplaySource:
    kind = SourceKind.replay

    def __init__(self, fps: float = 1.0, ring_seconds: float = 15.0) -> None:
        self._fps = fps
        self._ring = BoundedRingBuffer[FramePacket](max_items=int(fps * ring_seconds))
        self._running = False
        self._seq = 0
        self._last_at_ms = 0
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._produce(), name="replay-source")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def status(self) -> SourceStatus:
        return SourceStatus(
            kind=self.kind,
            healthy=self._running,
            last_frame_seq=self._seq,
            last_frame_at_ms=self._last_at_ms,
            detail=f"fps={self._fps} ring={self._ring.capacity()}",
        )

    async def frames(self) -> AsyncIterator[FramePacket]:
        while self._running:
            await asyncio.sleep(0)
            item = self._ring.peek_latest()
            if item is not None:
                yield item

    async def _produce(self) -> None:
        interval = 1.0 / max(self._fps, 0.1)
        while self._running:
            self._seq += 1
            now_ms = int(time.time() * 1000)
            packet = FramePacket(
                sequence=self._seq,
                captured_at_ms=now_ms,
                jpeg_bytes=_TINY_JPEG,
                width=1,
                height=1,
                source_kind=self.kind,
            )
            self._ring.push(packet)
            self._last_at_ms = now_ms
            await asyncio.sleep(interval)
