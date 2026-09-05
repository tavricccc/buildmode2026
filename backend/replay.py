from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Awaitable, Callable

from .schemas import VisionObservation
from .store import Store


class ReplayManager:
    def __init__(self, store: Store, broadcast: Callable[[dict[str, Any]], Awaitable[None]]):
        self.store = store
        self.broadcast = broadcast
        self.video_id: str | None = None
        self.status = "idle"
        self.position_ms = 0
        self.run_id = f"run_{uuid.uuid4().hex[:16]}"
        self.task: asyncio.Task | None = None

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        return [
            {"id": "fall-positive", "display_name": "跌倒正例：站立後倒地未恢復", "event_type": "fall", "duration_ms": 22000, "negative": False},
            {"id": "fall-negative", "display_name": "跌倒負例：坐沙發／躺下", "event_type": "fall", "duration_ms": 12000, "negative": True},
            {"id": "hydration-positive", "display_name": "喝水正例：杯子靠嘴並飲用", "event_type": "hydration", "duration_ms": 14000, "negative": False},
            {"id": "hydration-negative", "display_name": "喝水負例：拿杯但未飲用", "event_type": "hydration", "duration_ms": 10000, "negative": True},
        ]

    @staticmethod
    def sequence(video_id: str) -> list[VisionObservation]:
        def o(offset: int, *, posture="standing", transition="none", near=False, container="none", mouth=False, drink=False, confidence=.86, person=True, uncertainty=None):
            return VisionObservation(observed_at_offset_ms=offset, person_visible=person, posture=posture,
                                     vertical_transition=transition, near_floor=near, drink_container=container,
                                     container_near_mouth=mouth, drinking_motion=drink, confidence=confidence,
                                     supporting_frame_indexes=[0], uncertainty_reasons=uncertainty or [])
        if video_id == "fall-positive":
            return [o(0), o(2000), o(4000, posture="standing", transition="down", near=True, confidence=.86),
                    o(6000, posture="lying", near=True, confidence=.91), o(8000, posture="lying", near=True, confidence=.94),
                    o(12000, posture="lying", near=True, confidence=.95), o(18000, posture="lying", near=True, confidence=.95),
                    o(22000, posture="lying", near=True, confidence=.95)]
        if video_id == "fall-negative":
            return [o(0), o(2000), o(4000, posture="sitting", near=False), o(6000, posture="lying", near=False, confidence=.8), o(8000, posture="sitting", near=False), o(10000)]
        if video_id == "hydration-positive":
            return [o(0), o(2000, container="cup", mouth=True, drink=False), o(4000, container="cup", mouth=True, drink=True),
                    o(6000, container="cup", mouth=True, drink=True), o(8000, container="cup", mouth=True, drink=True), o(14000)]
        if video_id == "hydration-negative":
            return [o(0), o(2000, container="cup", mouth=False, drink=False), o(4000, container="cup", mouth=True, drink=False), o(8000), o(10000)]
        raise KeyError(video_id)

    async def load(self, video_id: str) -> dict[str, Any]:
        if video_id not in {x["id"] for x in self.catalog()}:
            raise ValueError("video_id is not allowlisted")
        await self.pause()
        meta = next(x for x in self.catalog() if x["id"] == video_id)
        self.video_id = video_id
        self.position_ms = 0
        self.status = "loaded"
        await self.broadcast({"type": "video.progress", "payload": self.snapshot()})
        return self.snapshot() | {"metadata": meta}

    async def start(self) -> dict[str, Any]:
        if not self.video_id:
            raise ValueError("load a replay source first")
        if self.task and not self.task.done():
            return self.snapshot()
        self.status = "playing"
        self.task = asyncio.create_task(self._run(), name="replay-source")
        return self.snapshot()

    async def pause(self) -> dict[str, Any]:
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        if self.video_id:
            self.status = "paused"
        return self.snapshot()

    async def reset(self) -> dict[str, Any]:
        await self.pause()
        self.position_ms = 0
        self.run_id = f"run_{uuid.uuid4().hex[:16]}"
        self.store.clear_runtime()
        await self.broadcast({"type": "system.status", "payload": {"run_id": self.run_id, "message": "Replay runtime reset"}})
        await self.broadcast({"type": "video.progress", "payload": self.snapshot()})
        return self.snapshot()

    async def _run(self) -> None:
        try:
            items = self.sequence(self.video_id or "")
            speed = max(0.1, float(os.getenv("REPLAY_SPEED", "4")))
            previous = self.position_ms
            for observation in items:
                if observation.observed_at_offset_ms < self.position_ms:
                    continue
                delay = max(0.03, min(1.5, (observation.observed_at_offset_ms - previous) / 1000 / speed))
                await asyncio.sleep(delay)
                previous = observation.observed_at_offset_ms
                self.position_ms = observation.observed_at_offset_ms
                await self.broadcast({"type": "local_analysis.started", "payload": {"offset_ms": self.position_ms, "model": self.store.settings.local_vlm_model, "mode": self.store.settings.local_vlm_mode}})
                result = self.store.process_observation(observation, self.run_id, "replay")
                await self.broadcast({"type": "local_analysis.completed", "payload": {"offset_ms": self.position_ms, "observation": observation.model_dump(), "events": result["events"], "model": self.store.settings.local_vlm_model, "mode": self.store.settings.local_vlm_mode}})
                for event in result["events"]:
                    await self.broadcast({"type": "event.updated" if event.get("updated_at") != event.get("created_at") else "event.created", "correlation_id": event["id"], "payload": event})
                    await self._maybe_alert(event)
                await self.broadcast({"type": "video.progress", "payload": self.snapshot()})
            self.status = "paused"
            await self.broadcast({"type": "video.progress", "payload": self.snapshot() | {"completed": True}})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status = "error"
            await self.broadcast({"type": "log.appended", "payload": {"level": "error", "component": "replay", "message": "Replay stopped", "error": type(exc).__name__}})

    async def _maybe_alert(self, event: dict[str, Any]) -> None:
        if event.get("event_type") != "fall" or event.get("status") not in {"confirmed", "recovering"}:
            return
        occurred = event.get("occurred_at", "")
        attrs = event.get("attributes_json") or event.get("attributes") or {}
        if isinstance(attrs, str):
            import json
            attrs = json.loads(attrs)
        due = attrs.get("alert_due_at")
        if not due:
            return
        from .store import parse_dt
        if self.position_ms - int(event.get("source_offset_ms") or 0) < (self.store.settings.demo_no_recovery_alert_sec * 1000):
            return
        action = self.store.create_action(event["id"], "dashboard_alert", {"severity": "acute", "title": "跌倒事件尚未觀察到恢復", "event_id": event["id"], "degraded": False})
        if action.get("status") == "triggered":
            await self.broadcast({"type": "action.triggered", "correlation_id": event["id"], "payload": action})

    def snapshot(self) -> dict[str, Any]:
        meta = next((x for x in self.catalog() if x["id"] == self.video_id), None)
        return {"source": "replay", "run_id": self.run_id, "video_id": self.video_id, "status": self.status,
                "position_ms": self.position_ms, "duration_ms": meta["duration_ms"] if meta else 0, "metadata": meta}
