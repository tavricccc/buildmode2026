"""WebSocket message envelope (v3 05 + v4 05)."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# v3 22 + v4 6 = 28 message types.
WSMessageType = Literal[
    # v3 preserved
    "system.status",
    "video.progress",
    "health.updated",
    "audio.vad",
    "audio.transcript",
    "camera.status",
    "vision.loop.tick",
    "vision.loop.dropped",
    "event.created",
    "event.updated",
    "local_analysis.started",
    "local_analysis.completed",
    "cloud_analysis.started",
    "cloud_analysis.completed",
    "action.triggered",
    "tool.called",
    "observer.finding",
    "notification.updated",
    "setup.updated",
    "model.download.progress",
    "model.activated",
    "log.appended",
    # v4 added
    "model.install.progress",
    "model.probe.completed",
    "endpoint.updated",
    "settings.applied",
    "settings.rollback.completed",
]


class WSMessage(BaseModel):
    message_id: str
    type: WSMessageType
    occurred_at: str
    correlation_id: str | None = None
    schema_version: str = "realtime.v1"
    payload: dict[str, Any] = Field(default_factory=dict)


def all_message_types() -> list[str]:
    return list(WSMessageType.__args__)  # type: ignore[attr-defined]
