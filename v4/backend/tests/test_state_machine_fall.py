"""Fall state machine tests."""

from __future__ import annotations

from v4.backend.domain.enums import EventStatus
from v4.backend.domain.policy import FallPolicy
from v4.backend.domain.vision_observation import VisionObservation
from v4.backend.state_machines.fall import FallContext, fall_transition


def _obs(posture: str = "standing", confidence: float = 0.8) -> VisionObservation:
    return VisionObservation(
        observed_at_offset_ms=0,
        person_visible=True,
        posture=posture,
        vertical_transition="none",
        near_floor=posture == "lying",
        drink_container="none",
        container_near_mouth=False,
        drinking_motion=False,
        confidence=confidence,
        supporting_frame_indexes=[0],
    )


def test_fall_idle_to_suspect() -> None:
    ctx = FallContext(subject_id="r", history=(_obs("lying", 0.9),), policy=FallPolicy(), now_ms=0)
    new, attrs = fall_transition(ctx, EventStatus.idle)
    assert new == EventStatus.suspect
    assert attrs["alert_due"] is False


def test_fall_suspect_to_confirmed() -> None:
    ctx = FallContext(
        subject_id="r",
        history=(_obs("lying", 0.9), _obs("lying", 0.9)),
        policy=FallPolicy(),
        now_ms=0,
    )
    new, attrs = fall_transition(ctx, EventStatus.suspect)
    assert new == EventStatus.confirmed
    assert attrs["alert_due"] is True


def test_fall_confirmed_to_recovering() -> None:
    ctx = FallContext(
        subject_id="r",
        history=(_obs("lying", 0.9), _obs("sitting", 0.9)),
        policy=FallPolicy(),
        now_ms=0,
    )
    new, _ = fall_transition(ctx, EventStatus.confirmed)
    assert new == EventStatus.recovering


def test_fall_no_recovery_alert() -> None:
    policy = FallPolicy(no_recovery_alert_sec=60)
    ctx = FallContext(
        subject_id="r",
        history=(_obs("lying", 0.9), _obs("lying", 0.9)),
        policy=policy,
        now_ms=120_000,
        last_no_recovery_at_ms=0,
    )
    _, attrs = fall_transition(ctx, EventStatus.confirmed)
    assert attrs["alert_due"] is True


def test_fall_low_confidence_does_not_advance() -> None:
    ctx = FallContext(
        subject_id="r",
        history=(_obs("lying", 0.3),),
        policy=FallPolicy(min_confidence=0.7),
        now_ms=0,
    )
    new, _ = fall_transition(ctx, EventStatus.idle)
    assert new == EventStatus.idle
