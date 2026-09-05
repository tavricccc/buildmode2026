"""Hydration state machine (v4 03).

States: idle → suspect → confirmed → active → completed

Only ``completed`` sessions count toward the daily total. Retries
within the cooldown window do not produce a second event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.enums import EventStatus
from ..domain.policy import HydrationPolicy
from ..domain.vision_observation import VisionObservation


@dataclass(frozen=True)
class HydrationContext:
    subject_id: str
    history: tuple[VisionObservation, ...]
    policy: HydrationPolicy
    now_ms: int
    last_completed_at_ms: int | None = None


def hydration_transition(ctx: HydrationContext, current: EventStatus) -> tuple[EventStatus, dict[str, Any]]:
    attrs: dict[str, Any] = {"counted": False, "estimated_ml": 0.0}
    if not ctx.history:
        return current, attrs

    last = ctx.history[-1]
    drinking = last.is_drinking() and last.confidence >= 0.5  # baseline confidence threshold

    if current == EventStatus.idle or current == EventStatus.dismissed:
        if drinking:
            return EventStatus.suspect, attrs
        return current, attrs

    if current == EventStatus.suspect:
        if drinking:
            return EventStatus.confirmed, attrs
        return EventStatus.suspect, attrs

    if current == EventStatus.confirmed:
        return EventStatus.active, attrs

    if current == EventStatus.active:
        if not drinking:
            # End of drink motion → completed.
            if ctx.last_completed_at_ms is None or (ctx.now_ms - ctx.last_completed_at_ms) / 1000.0 >= 30:
                attrs["counted"] = True
                attrs["estimated_ml"] = float(ctx.policy.container_volume_ml)
                return EventStatus.completed, attrs
        return EventStatus.active, attrs

    if current == EventStatus.completed:
        # Re-arm after a quiet gap.
        if not drinking:
            return EventStatus.idle, attrs
        return EventStatus.suspect, attrs

    return current, attrs
