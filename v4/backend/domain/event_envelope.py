"""Event envelope used across the v4 backend.

A superset of the v3 event envelope: v3 readers can still parse v4 events
because every v3 field is still present (it just becomes ``None`` when not
applicable). The four new fields (``model_endpoint_id``,
``deployment_type``, ``model_id`` renamed to ``configured-after-deploy``,
``config_version``) are documented in ``docs-implementation-v4/02_…``.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from .enums import DeploymentType, EventStatus
from .time import isoformat, utc_now


class EventEnvelope(BaseModel):
    """Canonical v4 event record (see v4 02)."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    event_id: str
    event_type: str = Field(pattern=r"^(fall|hydration)$")
    status: EventStatus
    occurred_at: str
    recorded_at: str = Field(default_factory=lambda: isoformat(utc_now()))
    subject_id: str
    source_offset_ms: Optional[int] = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # v3 fields kept for back-compat with v3 audit readers.
    model_id: str = "configured-after-deploy"
    model_version: str = "configured-at-runtime"
    prompt_version: str = "vision-events.v1"
    schema_version: str = "event.v1"
    dedup_key: str = ""

    # v4 new fields.
    model_endpoint_id: Optional[str] = None
    deployment_type: Optional[DeploymentType] = None
    config_version: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)
