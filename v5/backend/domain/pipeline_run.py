"""``pipeline_runs`` — the v5 audit record (v5 02).

One row per vision window. v5 00 item 10 is the requirement this exists
to satisfy: for *any* window you can reconstruct the L1 decision, whether
Gemini was skipped or called and why, whether it escalated, whether
MiniMax was skipped or called and why, plus latency, model ids, the
config version and the evidence reference.

Kept as a mutable dataclass rather than a Schema because it is assembled
incrementally as the window travels down the cascade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import L1Decision, L2Outcome, L3Outcome
from .ids import new_id
from .timeutil import iso, now_ms


@dataclass
class PipelineRun:
    run_id: str = field(default_factory=lambda: new_id("run"))
    subject_id: str = "subject-1"
    window_started_at_ms: int = 0
    window_ended_at_ms: int = 0
    config_version: str = "policy.v5.0"

    # -- L1 --------------------------------------------------------------
    l1_decision: str = L1Decision.unavailable.value
    l1_confidence: float = 0.0
    l1_detector_id: str = "none"
    l1_latency_ms: int = 0
    l1_health: str = "unknown"

    # -- L2 --------------------------------------------------------------
    l2_outcome: str = L2Outcome.skipped_l1.value
    l2_reason: str = ""
    l2_model: str | None = None
    l2_call_id: str | None = None
    l2_latency_ms: int | None = None
    l2_repaired: bool = False
    l2_escalation_required: bool = False
    l2_escalation_reasons: list[str] = field(default_factory=list)
    l2_error: str | None = None

    # -- L3 --------------------------------------------------------------
    l3_outcome: str = L3Outcome.not_required.value
    l3_reason: str = ""
    l3_model: str | None = None
    l3_call_id: str | None = None
    l3_latency_ms: int | None = None
    l3_risk_level: str | None = None
    l3_error: str | None = None

    # -- downstream -------------------------------------------------------
    evidence_id: str | None = None
    clip_path: str | None = None
    # Original Longcare L0 compatibility signal.  It is an accelerator only;
    # high-risk states and safety heartbeats can still force L2.
    change_detected: bool = True
    change_score: float | None = None
    change_reasons: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    action_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=iso)

    @property
    def total_latency_ms(self) -> int:
        return (self.l1_latency_ms or 0) + (self.l2_latency_ms or 0) + (self.l3_latency_ms or 0)

    def mark_l2_skipped(self, reason: str) -> None:
        self.l2_outcome = L2Outcome.skipped_l1.value
        self.l2_reason = reason

    def mark_l3_not_required(self, reason: str) -> None:
        self.l3_outcome = L3Outcome.not_required.value
        self.l3_reason = reason

    def close(self) -> "PipelineRun":
        if not self.window_ended_at_ms:
            self.window_ended_at_ms = now_ms()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__} | {
            "total_latency_ms": self.total_latency_ms
        }

    def trace(self) -> list[dict[str, str]]:
        """The cascade trace the Dashboard renders when an event is clicked."""
        steps = [
            {
                "layer": "L1",
                "outcome": self.l1_decision,
                "detail": f"{self.l1_detector_id} · conf {self.l1_confidence:.2f}",
                "latency_ms": str(self.l1_latency_ms),
            },
            {
                "layer": "L2",
                "outcome": self.l2_outcome,
                "detail": self.l2_reason or (self.l2_model or "—"),
                "latency_ms": str(self.l2_latency_ms or 0),
            },
            {
                "layer": "L3",
                "outcome": self.l3_outcome,
                "detail": self.l3_reason or (self.l3_model or "—"),
                "latency_ms": str(self.l3_latency_ms or 0),
            },
        ]
        return steps
