"""Observer finding builder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..domain.ids import new_id
from ..domain.time import isoformat, utc_now
from .baseline import BaselineComparison
from .daily_summary import DailySummaryInput


@dataclass(frozen=True)
class ObserverFinding:
    id: str
    subject_id: str
    window_start: str
    window_end: str
    finding_type: str
    statement: str
    evidence: dict[str, Any]
    confidence: float
    status: str
    created_at: str


def build_finding(
    summary: DailySummaryInput,
    comparison: BaselineComparison,
    *,
    model_id: str = "configured",
    config_version: str = "configured",
) -> ObserverFinding:
    statement = "、".join(
        f"{k} 變化 {comparison.deltas.get(k, 0):+.0%}" for k in comparison.exceeds_threshold
    ) or "本週觀察未超出設定門檻"
    return ObserverFinding(
        id=new_id("find"),
        subject_id=summary.subject_id,
        window_start=summary.summary_date,
        window_end=summary.summary_date,
        finding_type="trend_change" if comparison.exceeds_threshold else "stable",
        statement=statement,
        evidence={
            "summary": {
                "event_counts": summary.event_counts,
                "hydration_ml": summary.hydration_ml,
                "coverage": summary.coverage,
            },
            "comparison": comparison.to_dict(),
            "model_id": model_id,
            "config_version": config_version,
        },
        confidence=0.55,
        status="open",
        created_at=isoformat(utc_now()),
    )
