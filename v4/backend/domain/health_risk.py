"""Health-risk contract (v4 07).

The ``analysis`` model slot returns a ``HealthRiskResult`` matching
``health-risk.v1``. The schema is intentionally narrow so the same
fixture works for any local/cloud OpenAI-compatible endpoint.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


RiskLevel = Literal["low", "moderate", "elevated", "high"]


class HealthRiskInput(BaseModel):
    """What the analysis model sees.

    Domain code never sends raw video, full audio, or secrets. Only
    pre-aggregated health snapshots, SQL aggregates, and the user-selected
    window are passed in.
    """

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    window_start: str
    window_end: str
    health_snapshot: dict[str, Any] = Field(default_factory=dict)
    sql_aggregates: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)


class HealthRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "health-risk.v1"
    summary_zh: str
    risk_level: RiskLevel
    reason_codes: list[str] = Field(default_factory=list)
    supporting_facts: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    analysis_window: dict[str, str]
    confidence: float = Field(ge=0.0, le=1.0)
