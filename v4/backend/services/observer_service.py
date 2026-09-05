"""Observer service stub (v4 10)."""

from __future__ import annotations

from ..observer import (
    BaselineComparison,
    DailySummaryInput,
    ObserverFinding,
    build_daily_summary,
    build_finding,
    compare_to_baseline,
)
from ..realtime import RealtimeBroadcaster


class ObserverService:
    def __init__(self, broadcaster: RealtimeBroadcaster) -> None:
        self._broadcaster = broadcaster

    async def run_once(
        self,
        *,
        subject_id: str,
        summary_date: str,
        event_counts: dict[str, int],
        hydration_ml: float,
        health_snapshot: dict,
        coverage: float,
        baseline: dict[str, float],
    ) -> ObserverFinding:
        summary = DailySummaryInput(
            subject_id=subject_id,
            summary_date=summary_date,
            event_counts=event_counts,
            hydration_ml=hydration_ml,
            health_snapshot=health_snapshot,
            coverage=coverage,
        )
        comp = compare_to_baseline(event_counts, baseline)
        finding = build_finding(summary, comp)
        await self._broadcaster.broadcast(
            "observer.finding",
            {
                "id": finding.id,
                "subject_id": finding.subject_id,
                "window_start": finding.window_start,
                "window_end": finding.window_end,
                "finding_type": finding.finding_type,
                "statement": finding.statement,
                "status": finding.status,
            },
        )
        return finding

    def daily_summary(self, inp: DailySummaryInput) -> dict:
        return build_daily_summary(inp)
