"""VisionObservation schema tests (v4 03)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from v4.backend.domain.vision_observation import VisionObservation


def test_vision_observation_accepts_valid_payload() -> None:
    obs = VisionObservation(
        observed_at_offset_ms=0,
        person_visible=True,
        posture="standing",
        vertical_transition="none",
        near_floor=False,
        drink_container="none",
        container_near_mouth=False,
        drinking_motion=False,
        confidence=0.7,
        supporting_frame_indexes=[0, 1, 2],
    )
    assert obs.is_lying() is False
    assert obs.is_drinking() is False


def test_vision_observation_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        VisionObservation(
            observed_at_offset_ms=0,
            person_visible=True,
            posture="standing",
            vertical_transition="none",
            near_floor=False,
            drink_container="none",
            container_near_mouth=False,
            drinking_motion=False,
            confidence=1.5,
            supporting_frame_indexes=[],
        )


def test_vision_observation_caps_supporting_frame_indexes() -> None:
    with pytest.raises(ValidationError):
        VisionObservation(
            observed_at_offset_ms=0,
            person_visible=True,
            posture="standing",
            vertical_transition="none",
            near_floor=False,
            drink_container="none",
            container_near_mouth=False,
            drinking_motion=False,
            confidence=0.5,
            supporting_frame_indexes=list(range(9)),
        )


def test_vision_observation_helpers() -> None:
    lying = VisionObservation(
        observed_at_offset_ms=0,
        person_visible=True,
        posture="lying",
        vertical_transition="down",
        near_floor=True,
        drink_container="none",
        container_near_mouth=False,
        drinking_motion=False,
        confidence=0.9,
        supporting_frame_indexes=[0],
    )
    assert lying.is_lying() is True

    drinking = VisionObservation(
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
    assert drinking.is_drinking() is True
