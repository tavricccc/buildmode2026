"""Daily summary builder (v4 10)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DailySummaryInput:
    subject_id: str
    summary_date: str
    event_counts: dict[str, int]
    hydration_ml: float
    health_snapshot: dict[str, Any]
    coverage: float


def build_daily_summary(inp: DailySummaryInput) -> dict[str, Any]:
    """Return a fixed-size summary suitable for sending to the analysis slot.

    The shape is bounded regardless of how many events occurred that
    day — token cost does not grow with event count.
    """
    return {
        "schema_version": "daily_summary.v1",
        "subject_id": inp.subject_id,
        "summary_date": inp.summary_date,
        "event_counts": dict(inp.event_counts),
        "hydration_ml": float(inp.hydration_ml),
        "health_snapshot": dict(inp.health_snapshot),
        "coverage": float(inp.coverage),
    }
