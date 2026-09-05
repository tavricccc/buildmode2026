"""Settings schema definitions.

The Settings API (``backend/api/settings.py``) returns JSON-Schema
documents generated from these Pydantic models. The v4 split between
``ui_editable``, ``secret_write_only`` and ``host_managed`` is encoded by
the ``SettingsCategory`` enum and applied to each sub-model below.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Sub-policies. Each is ``ui_editable`` unless its docstring says otherwise.
# ---------------------------------------------------------------------------


class FallPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_window_sec: int = Field(default=8, ge=1, le=600)
    no_recovery_alert_sec: int = Field(default=120, ge=1, le=3600)
    demo_no_recovery_alert_sec: int = Field(default=10, ge=1, le=120)
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    cooldown_sec: int = Field(default=60, ge=0, le=3600)


class HydrationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ml_per_day: int = Field(default=1600, ge=0, le=10_000)
    reminder_window_hours: int = Field(default=4, ge=1, le=24)
    min_confirmed_sessions: int = Field(default=1, ge=1, le=10)
    container_volume_ml: int = Field(default=240, ge=10, le=2000)


class AnalysisPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_window: Literal["1h", "6h", "24h", "7d", "30d"] = "24h"
    allowed_windows: list[Literal["1h", "6h", "24h", "7d", "30d"]] = Field(
        default_factory=lambda: ["1h", "6h", "24h", "7d", "30d"]
    )
    timeout_sec: int = Field(default=30, ge=5, le=180)
    max_retries: int = Field(default=2, ge=0, le=5)
    cache_ttl_sec: int = Field(default=300, ge=0, le=3600)
    manual_refresh_cooldown_sec: int = Field(default=60, ge=0, le=3600)


class ObserverPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_time: str = Field(default="02:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = "Asia/Taipei"
    short_window_days: int = Field(default=7, ge=1, le=30)
    baseline_window_days: int = Field(default=30, ge=7, le=180)
    min_coverage: float = Field(default=0.7, ge=0.0, le=1.0)
    change_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    auto_run: bool = False


class NotificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: Literal["__secret__"] = "__secret__"
    allowed_chat_ids: list[str] = Field(default_factory=list)
    poll_timeout_sec: int = Field(default=25, ge=5, le=60)
    retry_max: int = Field(default=3, ge=0, le=10)
    ack_timeout_sec: int = Field(default=600, ge=30, le=3600)
    attach_evidence: bool = False
    template_fields: list[str] = Field(
        default_factory=lambda: ["subject", "event_type", "occurred_at", "summary"]
    )


class VisionLoopPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_ms: int = Field(default=5000, ge=250, le=60_000)
    window_seconds: int = Field(default=8, ge=1, le=60)
    max_frames: int = Field(default=8, ge=1, le=16)
    jpeg_quality: int = Field(default=70, ge=10, le=100)
    jpeg_edge: int = Field(default=512, ge=64, le=2048)
    fps: int = Field(default=1, ge=1, le=10)
    timeout_ms: int = Field(default=8000, ge=500, le=60_000)
    max_retries: int = Field(default=2, ge=0, le=5)
    rate_budget_per_hour: int = Field(default=720, ge=0, le=7200)


class AudioPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_rate: int = Field(default=16_000, ge=8000, le=48_000)
    channels: int = Field(default=1, ge=1, le=2)
    vad: Literal["silero_local", "energy_local", "model_slot"] = "energy_local"
    segment_min_ms: int = Field(default=500, ge=100, le=5000)
    segment_max_ms: int = Field(default=8000, ge=1000, le=30_000)
    silence_ms: int = Field(default=400, ge=100, le=5000)
    language: str = "zh"
    retention_sec: int = Field(default=3600, ge=0, le=86_400)


# ---------------------------------------------------------------------------
# Bundle — the complete settings tree stored in config_versions.settings_json.
# ---------------------------------------------------------------------------


class PolicyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fall: FallPolicy = Field(default_factory=FallPolicy)
    hydration: HydrationPolicy = Field(default_factory=HydrationPolicy)
    analysis: AnalysisPolicy = Field(default_factory=AnalysisPolicy)
    observer: ObserverPolicy = Field(default_factory=ObserverPolicy)
    notification: NotificationPolicy = Field(default_factory=NotificationPolicy)
    vision_loop: VisionLoopPolicy = Field(default_factory=VisionLoopPolicy)
    audio: AudioPolicy = Field(default_factory=AudioPolicy)
    locale: str = "zh-TW"
    timezone: str = "Asia/Taipei"
    extra: dict[str, Any] = Field(default_factory=dict)
