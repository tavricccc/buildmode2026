"""Vision observation contract (v4 03).

A vision model returns one ``VisionObservation`` per fixed-rate job. The
observation is *not* a confirmed event: only the fall / hydration state
machines can promote it.
"""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


Posture = Literal["standing", "sitting", "lying", "unknown"]
VerticalTransition = Literal["up", "down", "none", "unknown"]
DrinkContainer = Literal["cup", "bottle", "other", "none", "unknown"]


class VisionObservation(BaseModel):
    """Structured output of one vision model call."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    observed_at_offset_ms: int = Field(ge=0)
    person_visible: bool
    posture: Posture
    vertical_transition: VerticalTransition
    near_floor: bool
    drink_container: DrinkContainer
    container_near_mouth: bool
    drinking_motion: bool
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_frame_indexes: list[int] = Field(
        default_factory=list, min_length=0, max_length=8
    )
    uncertainty_reasons: list[str] = Field(default_factory=list)

    def is_lying(self) -> bool:
        return self.person_visible and self.posture == "lying"

    def is_drinking(self) -> bool:
        return (
            self.person_visible
            and self.drink_container != "none"
            and (self.container_near_mouth or self.drinking_motion)
        )
