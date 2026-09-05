"""Fall state machine (v4 03).

States: idle → suspect → confirmed → recovering → resolved
         (and an alert_due flag emitted alongside ``confirmed``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.enums import EventStatus
from ..domain.policy import FallPolicy
from ..domain.vision_observation import VisionObservation


@dataclass(frozen=True)
class FallContext:
    subject_id: str
    history: tuple[VisionObservation, ...]
    policy: FallPolicy
    now_ms: int
    last_no_recovery_at_ms: int | None = None


def fall_transition(ctx: FallContext, current: EventStatus) -> tuple[EventStatus, dict[str, Any]]:
    """Return ``(new_status, attributes_to_merge)``.

    Pure function: no I/O, no clock reads, no model calls. The caller
    (the orchestration service) is responsible for persisting.
    """
    attrs: dict[str, Any] = {"alert_due": False}
    if not ctx.history:
        return current, attrs

    last = ctx.history[-1]
    confident_lying = (
        last.person_visible
        and last.posture == "lying"
        and last.confidence >= ctx.policy.min_confidence
    )

    if current == EventStatus.idle or current == EventStatus.dismissed:
        if confident_lying:
            return EventStatus.suspect, attrs
        return current, attrs

    if current == EventStatus.suspect:
        # Promote to confirmed only if a follow-up observation is also lying.
        if confident_lying and len(ctx.history) >= 2:
            return EventStatus.confirmed, {**attrs, "alert_due": True}
        # If person recovered before the confirm window elapsed, dismiss.
        return EventStatus.suspect, attrs

    if current == EventStatus.confirmed:
        # Recovery: person no longer lying.
        if last.person_visible and last.posture in {"standing", "sitting"} and last.confidence >= ctx.policy.min_confidence:
            return EventStatus.recovering, attrs
        # No-recovery alert timer.
        if ctx.last_no_recovery_at_ms is not None:
            elapsed = (ctx.now_ms - ctx.last_no_recovery_at_ms) / 1000.0
            if elapsed >= ctx.policy.no_recovery_alert_sec:
                attrs["alert_due"] = True
        return EventStatus.confirmed, attrs

    if current == EventStatus.recovering:
        # Stand up cleanly → resolved.
        if last.person_visible and last.posture in {"standing", "sitting"}:
            return EventStatus.resolved, attrs
        # Relapse back into confirmed.
        if confident_lying:
            return EventStatus.confirmed, attrs
        return EventStatus.recovering, attrs

    return current, attrs
