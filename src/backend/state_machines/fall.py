"""Fall state machine: idle -> suspect -> confirmed -> recovering -> resolved.

The v4 implementation had a structural bug worth naming, because the fix
is architectural rather than local: confirmation required a second
corroborating observation, but a motionless person on the floor produced
no *new* observation, because the change detector treated "nothing moved"
as "nothing to look at". A genuine fall was therefore the one case that
could never be confirmed.

The design removes the possibility rather than patching the symptom. L1 is a
presence filter and nothing else, and ``EventStatus.is_high_risk()``
makes suspect and confirmed bypass it entirely (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 8), so
follow-up observations keep arriving for exactly as long as someone is
still on the floor. This module can therefore count corroboration without
worrying about where the next observation comes from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import EventStatus
from ..domain.observation import GeminiObservation
from ..domain.policy import FallPolicy


@dataclass(frozen=True)
class FallContext:
    subject_id: str
    #: newest last; only the tail matters, but the whole window is passed
    #: so a caller can widen the corroboration rule without a signature change
    history: tuple[GeminiObservation, ...]
    policy: FallPolicy
    now_ms: int
    #: when the event entered ``confirmed`` — drives the no-recovery timer
    confirmed_at_ms: int | None = None
    #: alert already emitted for this confirmation, so we do not repeat it
    alert_sent: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def tail_indicating_fall(self) -> int:
        """How many of the most recent observations indicate a fall."""
        count = 0
        for observation in reversed(self.history):
            if observation.fall.indicates_fall(self.policy.min_confidence):
                count += 1
            else:
                break
        return count

    def recovered(self) -> bool:
        if not self.history:
            return False
        last = self.history[-1].fall
        return (
            last.posture in {"standing", "sitting"}
            and last.confidence >= self.policy.recovery_confidence
        )


def fall_transition(ctx: FallContext, current: EventStatus) -> tuple[EventStatus, dict[str, Any]]:
    """Return ``(next_status, attributes)``. Pure; the caller persists."""
    attrs: dict[str, Any] = {
        "alert_due": False,
        "alert_reason": "",
        "corroborating_observations": ctx.tail_indicating_fall(),
    }
    if not ctx.history:
        return current, attrs

    indicating = attrs["corroborating_observations"]

    if current in {EventStatus.idle, EventStatus.dismissed, EventStatus.resolved}:
        if indicating >= 1:
            return EventStatus.suspect, attrs
        return EventStatus.idle if current is EventStatus.resolved else current, attrs

    if current is EventStatus.suspect:
        if indicating >= ctx.policy.confirm_observations:
            attrs["alert_due"] = True
            attrs["alert_reason"] = "fall_confirmed"
            return EventStatus.confirmed, attrs
        if ctx.recovered():
            # Stood back up before we could corroborate: not a fall.
            return EventStatus.dismissed, attrs
        return EventStatus.suspect, attrs

    if current is EventStatus.confirmed:
        if ctx.recovered():
            return EventStatus.recovering, attrs
        # Still down. Escalate again once the no-recovery window elapses,
        # but only once per confirmation.
        if ctx.confirmed_at_ms is not None and not ctx.alert_sent:
            elapsed_sec = (ctx.now_ms - ctx.confirmed_at_ms) / 1000.0
            if elapsed_sec >= ctx.policy.no_recovery_alert_sec:
                attrs["alert_due"] = True
                attrs["alert_reason"] = "no_recovery"
        return EventStatus.confirmed, attrs

    if current is EventStatus.recovering:
        if indicating >= 1:
            # Went back down: treat as the same ongoing incident.
            return EventStatus.confirmed, attrs
        if ctx.recovered():
            return EventStatus.resolved, attrs
        return EventStatus.recovering, attrs

    return current, attrs
