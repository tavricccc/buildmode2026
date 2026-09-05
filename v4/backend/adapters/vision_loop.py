"""Continuous Vision Loop (v4 09 §2).

At most one running job and one latest pending job — the previous
pending is dropped, never accumulated. A new tick overrides the
pending window.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from ..domain.enums import Capability
from ..domain.ids import new_id
from ..domain.vision_observation import VisionObservation
from .frame_buffer import BoundedRingBuffer
from .model_gateway import ModelGateway, ModelRequest
from .source_protocol import FramePacket


logger = logging.getLogger(__name__)


@dataclass
class VisionJob:
    job_id: str
    started_at_ms: int
    frames: list[FramePacket]
    observation: VisionObservation | None = None
    error: str | None = None
    completed_at_ms: int | None = None


class ContinuousVisionLoop:
    def __init__(
        self,
        gateway: ModelGateway,
        endpoint_id: str,
        model_id: str,
        config_version: str | None,
        interval_ms: int = 5000,
        window_seconds: int = 8,
        max_frames: int = 8,
    ) -> None:
        self.gateway = gateway
        self.endpoint_id = endpoint_id
        self.model_id = model_id
        self.config_version = config_version
        self.interval_ms = interval_ms
        self.window_seconds = window_seconds
        self.max_frames = max_frames
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._running_job: VisionJob | None = None
        self._pending: VisionJob | None = None
        self._lock = asyncio.Lock()
        self.recent = BoundedRingBuffer[VisionJob](max_items=64)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._tick_loop(), name="vision-loop")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def metrics(self) -> dict[str, int]:
        return {
            "running": 1 if self._running_job is not None else 0,
            "pending": 1 if self._pending is not None else 0,
            "completed": len(self.recent),
        }

    async def submit_window(self, frames: list[FramePacket]) -> VisionJob:
        async with self._lock:
            if self._pending is not None:
                # Drop the previous pending; never accumulate a backlog.
                self._pending = None
            job = VisionJob(
                job_id=new_id("job"),
                started_at_ms=int(time.time() * 1000),
                frames=frames[: self.max_frames],
            )
            self._pending = job
        return job

    async def _tick_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.interval_ms / 1000.0)
            await self._pump()

    async def _pump(self) -> None:
        async with self._lock:
            job = self._pending
            self._pending = None
            if job is None:
                return
            self._running_job = job
        # Build request
        messages = [
            {"role": "system", "content": "You are a structured vision classifier. Reply with JSON only."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe the scene as a VisionObservation."},
                    *[
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + _b64(f.jpeg_bytes)},
                        }
                        for f in job.frames
                    ],
                ],
            },
        ]
        req = ModelRequest(
            capability=Capability.vision,
            inputs={"messages": messages, "output_schema": VisionObservation},
            prompt_version="vision-events.v1",
            schema_version="event.v1",
            config_version=self.config_version,
        )
        try:
            resp = await self.gateway.call(self.endpoint_id, self.model_id, req)
            if resp.parsed is not None and isinstance(resp.parsed, VisionObservation):
                job.observation = resp.parsed
            else:
                job.error = "invalid_schema"
        except Exception as exc:  # noqa: BLE001
            job.error = f"runtime_failed: {exc}"
        finally:
            job.completed_at_ms = int(time.time() * 1000)
            self.recent.push(job)
            self._running_job = None


def _b64(b: bytes) -> str:
    import base64

    return base64.b64encode(b).decode("ascii")
