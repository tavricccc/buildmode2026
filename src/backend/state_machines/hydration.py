"""Hydration state machine: idle -> suspect -> confirmed -> active -> completed.

Only a ``completed`` session counts toward the daily total (docs/01_PIPELINE.md), and a
session may only complete once per cooldown window. That cooldown is what
makes a replay re-run idempotent: replaying the same footage produces the
same single session instead of one per pass (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import EventStatus
from ..domain.observation import GeminiObservation
from ..domain.policy import HydrationPolicy


@dataclass(frozen=True)
class HydrationContext:
    subject_id: str
    history: tuple[GeminiObservation, ...]
    policy: HydrationPolicy
    now_ms: int
    #: when the previous session completed, for the cooldown
    last_completed_at_ms: int | None = None
    #: when the current session started, for duration
    started_at_ms: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def tail_drinking(self) -> int:
        count = 0
        for observation in reversed(self.history):
            if observation.hydration.indicates_drinking(self.policy.min_confidence):
                count += 1
            else:
                break
        return count

    def drinking_now(self) -> bool:
        if not self.history:
            return False
        return self.history[-1].hydration.indicates_drinking(self.policy.min_confidence)

    def cooldown_elapsed(self) -> bool:
        if self.last_completed_at_ms is None:
            return True
        return (self.now_ms - self.last_completed_at_ms) / 1000.0 >= self.policy.session_cooldown_sec


def hydration_transition(
    ctx: HydrationContext, current: EventStatus
) -> tuple[EventStatus, dict[str, Any]]:
    attrs: dict[str, Any] = {
        "counted": False,
        "estimated_ml": 0.0,
        "duration_sec": 0.0,
        "corroborating_observations": ctx.tail_drinking(),
    }
    if not ctx.history:
        return current, attrs

    drinking = ctx.drinking_now()

    if current in {EventStatus.idle, EventStatus.dismissed, EventStatus.completed}:
        if drinking and ctx.cooldown_elapsed():
            return EventStatus.suspect, attrs
        return EventStatus.idle if current is EventStatus.completed else current, attrs

    if current is EventStatus.suspect:
        if not drinking:
            # A single frame of "cup near face" is not a drink.
            return EventStatus.dismissed, attrs
        if ctx.tail_drinking() >= ctx.policy.confirm_observations:
            return EventStatus.confirmed, attrs
        return EventStatus.suspect, attrs

    if current is EventStatus.confirmed:
        return EventStatus.active, attrs

    if current is EventStatus.active:
        if drinking:
            return EventStatus.active, attrs
        if not ctx.cooldown_elapsed():
            # Within cooldown this is the tail of the session we already
            # counted, not a new one. Drop it rather than double-count.
            return EventStatus.idle, attrs
        attrs["counted"] = True
        attrs["estimated_ml"] = float(ctx.policy.container_volume_ml)
        if ctx.started_at_ms is not None:
            attrs["duration_sec"] = round((ctx.now_ms - ctx.started_at_ms) / 1000.0, 1)
        return EventStatus.completed, attrs

    return current, attrs
