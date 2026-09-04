"""Versioned metadata contracts for local capture output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import uuid


SCHEMA_VERSION = "multimodal_event_bundle.v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass(frozen=True)
class CaptureConfig:
    subject_id: str = "resident_001"
    source_id: str = "local-mac"
    camera_index: int = 0
    audio_device: int | str | None = None
    sample_rate: int = 16_000
    channels: int = 1
    frame_rate: float = 10.0
    keyframe_interval_seconds: float = 1.0
    duration_seconds: float = 10.0
    output_dir: Path = Path("data/captures")
    enable_video: bool = True
    enable_audio: bool = True


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    ref: str
    content_type: str
    sha256: str | None = None
    created_at: str = field(default_factory=lambda: isoformat(utc_now()))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "ref": self.ref,
            "content_type": self.content_type,
            "created_at": self.created_at,
        }
        if self.sha256:
            result["sha256"] = self.sha256
        return result


@dataclass
class EventCandidate:
    event_id: str
    subject_id: str
    source_id: str
    correlation_id: str
    occurred_at: str
    recorded_at: str
    window_start: str
    window_end: str | None = None
    trigger_labels: list[str] = field(default_factory=list)
    status: str = "capturing"

    @classmethod
    def start(cls, subject_id: str, source_id: str) -> "EventCandidate":
        now = utc_now()
        timestamp = isoformat(now)
        return cls(
            event_id=new_id("evt"),
            subject_id=subject_id,
            source_id=source_id,
            correlation_id=new_id("corr"),
            occurred_at=timestamp,
            recorded_at=timestamp,
            window_start=timestamp,
            trigger_labels=["local_capture_started"],
        )

    def finish(self, status: str = "completed") -> None:
        self.window_end = isoformat(utc_now())
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "subject_id": self.subject_id,
            "source_id": self.source_id,
            "correlation_id": self.correlation_id,
            "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at,
            "window": {"start": self.window_start, "end": self.window_end},
            "trigger": {"labels": self.trigger_labels},
            "status": self.status,
        }


@dataclass
class MultimodalEventBundle:
    candidate: EventCandidate
    evidence: list[EvidenceRef] = field(default_factory=list)
    modalities: dict[str, dict[str, Any]] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event": self.candidate.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "modalities": self.modalities,
            "quality": self.quality,
            "provenance": [
                {
                    "source": self.candidate.source_id,
                    "component": "local_capture",
                    "version": "0.1.0",
                }
            ],
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

