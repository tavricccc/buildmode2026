"""L1 person-gate contract (docs/01_PIPELINE.md §L1 Person Gate).

The gate answers exactly one question: *is a person in frame?* It may not
report posture, identity, falls, hydration, emotion or health risk — that
is L2's job (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md "不做").  Keeping the contract this narrow is what lets
the detector be swapped (YOLO11n person class, a stub, a remote service)
without any downstream change.
"""

from __future__ import annotations

from ..domain.enums import Health, L1Decision
from .schema import Field, Schema


class PersonGateReading(Schema):
    """One raw detector answer, before hysteresis is applied."""

    schema_version = "l1.reading.v1"
    fields = {
        "person_present": Field(bool),
        "confidence": Field(float, minimum=0.0, maximum=1.0),
        "observed_at_ms": Field(int, minimum=0),
        "detector_id": Field(str),
        "inference_ms": Field(int, minimum=0, default=0),
        "health": Field(str, choices=[h.value for h in Health], default=Health.ok.value),
    }


class PersonGateDecision(Schema):
    """The debounced gate decision the scheduler actually acts on.

    ``decision`` is the four-valued :class:`L1Decision`, not a bare bool,
    precisely so that "detector is stale" can never be mistaken for
    "the room is empty" (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 5).
    """

    schema_version = "l1.decision.v1"
    fields = {
        "decision": Field(str, choices=[d.value for d in L1Decision]),
        "confidence": Field(float, minimum=0.0, maximum=1.0, default=0.0),
        "decided_at_ms": Field(int, minimum=0),
        "detector_id": Field(str, default="none"),
        "health": Field(str, choices=[h.value for h in Health], default=Health.unknown.value),
        "consecutive_frames": Field(int, minimum=0, default=0),
        "age_ms": Field(int, minimum=0, default=0),
        "reason": Field(str, default=""),
    }

    @property
    def kind(self) -> L1Decision:
        return L1Decision(self.decision)

    def permits_skip(self) -> bool:
        return self.kind.permits_skip()
