"""Domain enums.

These are intentionally string-valued so they can be serialised straight
into JSON without bespoke encoders.
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """A model slot."""

    vision = "vision"
    transcription = "transcription"
    analysis = "analysis"
    speech = "speech"
    embedding = "embedding"


class DeploymentType(str, Enum):
    """Where the model lives."""

    local = "local"
    cloud = "cloud"


class EventStatus(str, Enum):
    """Lifecycle states for fall / hydration events.

    Status values are stable across v3 and v4: v3 audit readers can
    consume v4 events without code changes. ``idle`` and the in-progress
    fall states (``suspect`` / ``active`` for hydration) are part of
    the state machine vocabulary — v3 used the same names.
    """

    idle = "idle"
    candidate = "candidate"
    suspect = "suspect"
    confirmed = "confirmed"
    active = "active"
    recovering = "recovering"
    resolved = "resolved"
    completed = "completed"
    dismissed = "dismissed"
    invalid = "invalid"


class ModelCallStatus(str, Enum):
    success = "success"
    invalid_schema = "invalid_schema"
    timeout = "timeout"
    rate_limited = "rate_limited"
    auth_failed = "auth_failed"
    runtime_failed = "runtime_failed"
    capability_mismatch = "capability_mismatch"
    cancelled = "cancelled"


class ModelProbeStatus(str, Enum):
    pending = "pending"
    running = "running"
    ok = "ok"
    failed = "failed"
    skipped = "skipped"


class NotificationStatus(str, Enum):
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    acknowledged = "acknowledged"
    false_alarm = "false_alarm"
    failed = "failed"


class SettingsCategory(str, Enum):
    """Settings classification (v4 01 §"設定分類")."""

    ui_editable = "ui_editable"
    secret_write_only = "secret_write_only"
    host_managed = "host_managed"


class SourceKind(str, Enum):
    live_rtsp = "live_rtsp"
    replay = "replay"
    mock = "mock"
