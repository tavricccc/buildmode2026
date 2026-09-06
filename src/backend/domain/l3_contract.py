"""L3 escalation contracts (docs/01_PIPELINE.md §L3).

The evidence bundle is the load-bearing part of the design: MiniMax must see the
*clip itself*, not a second-hand Gemini summary. ``EvidenceBundle`` makes
that explicit — if ``clip`` is ``None`` the caller is in the degraded
text-only path and must say so in SQLite and the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import EscalationTrigger
from .schema import Field, Schema

RISK_LEVELS = ("none", "low", "medium", "high", "critical")

#: What L3 is permitted to *suggest*. The Policy Gateway decides whether
#: anything actually happens (docs/02_DATA_AND_POLICY.md: "模型不能直接發通知").
RECOMMENDATIONS = (
    "no_action",
    "keep_observing",
    "request_longer_window",
    "raise_dashboard_alert",
    "suggest_caregiver_notification",
)


@dataclass
class VideoClip:
    """A short encoded clip handed to a multimodal model."""

    path: str
    mime_type: str
    duration_sec: float
    size_bytes: int
    started_at_ms: int
    frame_count: int
    #: Replay ground truth, mirroring ``FramePacket.annotation``. Present
    #: only for fixture-driven clips; the stub L2 backend reads it so that
    #: docs/04_SETUP_DEPLOY_VERIFY.md gate 1 is deterministic. Real adapters ignore it.
    annotation: dict[str, Any] | None = None

    def is_inline_eligible(self, limit_bytes: int) -> bool:
        """<=20MB goes inline; larger media needs the Files API (docs/01_PIPELINE.md)."""
        return self.size_bytes <= limit_bytes


@dataclass
class EvidenceBundle:
    """Everything L3 is given for one escalation.

    docs/01_PIPELINE.md lists the normal contents: clip, the L2 structured result, the
    escalation reason, current event state, plus optional transcript and
    health/event aggregates.
    """

    escalation_id: str
    trigger: EscalationTrigger
    reason_codes: list[str]
    l2_observation: dict[str, Any]
    event_state: dict[str, Any]
    clip: VideoClip | None = None
    transcript: str | None = None
    aggregates: dict[str, Any] = field(default_factory=dict)

    @property
    def degraded_text_only(self) -> bool:
        return self.clip is None

    def describe(self) -> str:
        """Short human-readable line for logs and the cascade trace UI."""
        media = "text_only" if self.degraded_text_only else f"clip {self.clip.duration_sec:.1f}s"
        return f"{self.trigger.value} [{', '.join(self.reason_codes) or 'unspecified'}] {media}"


class DeeperAnalysis(Schema):
    """L3's structured answer.

    Note what is *absent*: no recipient, no channel, no threshold. L3 may
    argue for an action; it may not perform one.
    """

    schema_version = "l3.analysis.v1"
    fields = {
        "interpretation": Field(str),
        "risk_level": Field(str, choices=RISK_LEVELS, default="none"),
        "confidence": Field(float, minimum=0.0, maximum=1.0, default=0.0),
        "supports_l2": Field(bool, default=True),
        "contradicts_l2_reason": Field(str, default=""),
        "uncertainty": Field(list, default=list, item=str, max_items=6),
        "recommendation": Field(str, choices=RECOMMENDATIONS, default="keep_observing"),
        "recommended_followup_sec": Field(int, minimum=0, maximum=600, default=0),
    }

    def escalates_risk(self) -> bool:
        return self.risk_level in {"high", "critical"}


class CareReview(Schema):
    """A caregiver-facing review of a bounded longitudinal data window."""

    schema_version = "l3.care_review.v1"
    fields = {
        "summary": Field(str),
        "risk_level": Field(str, choices=RISK_LEVELS, default="none"),
        "confidence": Field(float, minimum=0.0, maximum=1.0, default=0.0),
        "recommendations": Field(list, default=list, item=str, max_items=6),
        "positive_signals": Field(list, default=list, item=str, max_items=6),
        "attention_items": Field(list, default=list, item=str, max_items=6),
        "data_limitations": Field(list, default=list, item=str, max_items=6),
    }
