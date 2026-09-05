"""Hydration state machine tests."""

from __future__ import annotations

from v4.backend.domain.enums import EventStatus
from v4.backend.domain.policy import HydrationPolicy
from v4.backend.domain.vision_observation import VisionObservation
from v4.backend.state_machines.hydration import HydrationContext, hydration_transition


def _drinking_obs() -> VisionObservation:
    return VisionObservation(
        observed_at_offset_ms=0,
        person_visible=True,
        posture="sitting",
        vertical_transition="none",
        near_floor=False,
        drink_container="cup",
        container_near_mouth=True,
        drinking_motion=True,
        confidence=0.9,
        supporting_frame_indexes=[0],
    )


def _idle_obs() -> VisionObservation:
    return VisionObservation(
        observed_at_offset_ms=0,
        person_visible=True,
        posture="sitting",
        vertical_transition="none",
        near_floor=False,
        drink_container="none",
        container_near_mouth=False,
        drinking_motion=False,
        confidence=0.9,
        supporting_frame_indexes=[0],
    )


def test_idle_to_suspect_then_confirmed() -> None:
    ctx = HydrationContext(
        subject_id="r", history=(_drinking_obs(),), policy=HydrationPolicy(), now_ms=0
    )
    new, _ = hydration_transition(ctx, EventStatus.idle)
    assert new == EventStatus.suspect
    new, _ = hydration_transition(ctx, EventStatus.suspect)
    assert new == EventStatus.confirmed


def test_completed_counts_once() -> None:
    policy = HydrationPolicy(container_volume_ml=300)
    history = (_drinking_obs(), _idle_obs())
    ctx = HydrationContext(subject_id="r", history=history, policy=policy, now_ms=10_000, last_completed_at_ms=None)
    new, attrs = hydration_transition(ctx, EventStatus.active)
    assert new == EventStatus.completed
    assert attrs["counted"] is True
    assert attrs["estimated_ml"] == 300
