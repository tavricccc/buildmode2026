"""L2 structured observation contract (v5 01 §L2).

Two rules encoded here rather than in prose:

1. An observation is *evidence*, never a confirmed event. Only the
   deterministic state machines in ``state_machines/`` may promote it
   (v5 00: "不讓 Gemini 或 MiniMax 直接建立 confirmed event").
2. Every observation carries an ``escalation`` block. L3 is expensive and
   must be *asked for*; the absence of a request is a decision, not a gap.
"""

from __future__ import annotations

from .schema import Field, Schema

POSTURE = ("standing", "sitting", "lying", "crouching", "unknown")
TRANSITION = ("up", "down", "none", "unknown")
CONTAINER = ("cup", "bottle", "other", "none", "unknown")

#: Reason codes L2 may use to justify an escalation. Anything else is
#: dropped during validation so an operator can trust the audit trail.
ESCALATION_REASONS = (
    "possible_fall",
    "person_motionless_on_floor",
    "ambiguous_posture",
    "occluded_view",
    "distress_signal",
    "unusual_inactivity",
    "hydration_ambiguous",
    "low_confidence",
    "other",
)


class FallObservation(Schema):
    schema_version = "obs.fall.v1"
    fields = {
        "posture": Field(str, choices=POSTURE, default="unknown"),
        "vertical_transition": Field(str, choices=TRANSITION, default="unknown"),
        "near_floor": Field(bool, default=False),
        "motionless": Field(bool, default=False),
        "confidence": Field(float, minimum=0.0, maximum=1.0, default=0.0),
    }

    def indicates_fall(self, min_confidence: float) -> bool:
        return (
            self.posture == "lying"
            and self.near_floor
            and self.confidence >= min_confidence
        )


class HydrationObservation(Schema):
    schema_version = "obs.hydration.v1"
    fields = {
        "container": Field(str, choices=CONTAINER, default="none"),
        "container_near_mouth": Field(bool, default=False),
        "drinking_motion": Field(bool, default=False),
        "confidence": Field(float, minimum=0.0, maximum=1.0, default=0.0),
    }

    def indicates_drinking(self, min_confidence: float) -> bool:
        return (
            self.container not in {"none", "unknown"}
            and (self.container_near_mouth or self.drinking_motion)
            and self.confidence >= min_confidence
        )


class Escalation(Schema):
    """L2's request for a deeper L3 look (v5 01 §L2)."""

    schema_version = "obs.escalation.v1"
    fields = {
        "required": Field(bool, default=False),
        "reason_codes": Field(list, default=list, item=str, max_items=6),
        "requested_evidence_window_sec": Field(int, minimum=0, maximum=60, default=10),
    }

    def normalised_reasons(self) -> list[str]:
        """Drop invented reason codes; keep order, de-duplicate."""
        seen: list[str] = []
        for code in self.reason_codes:
            if code in ESCALATION_REASONS and code not in seen:
                seen.append(code)
        if self.required and not seen:
            seen.append("other")
        return seen


class GeminiObservation(Schema):
    """One complete L2 answer for one window."""

    schema_version = "obs.window.v1"
    fields = {
        "person_visible": Field(bool),
        "person_count": Field(int, minimum=0, maximum=10, default=0),
        "scene_summary": Field(str, default=""),
        "confidence": Field(float, minimum=0.0, maximum=1.0),
        "uncertainty_reasons": Field(list, default=list, item=str, max_items=6),
    }
    nested = {
        "fall": FallObservation,
        "hydration": HydrationObservation,
        "escalation": Escalation,
    }

    def needs_escalation(self) -> bool:
        return bool(self.escalation.required)
