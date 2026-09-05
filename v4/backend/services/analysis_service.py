"""Analysis service stub (v4 07)."""

from __future__ import annotations

from typing import Any

from ..domain.health_risk import HealthRiskResult


class AnalysisService:
    async def analyse(
        self,
        *,
        subject_id: str,
        window_start: str,
        window_end: str,
    ) -> HealthRiskResult:
        return HealthRiskResult(
            summary_zh=f"{subject_id} 在指定視窗內無顯著變化。",
            risk_level="low",
            reason_codes=["no_significant_change"],
            analysis_window={"start": window_start, "end": window_end},
            confidence=0.5,
        )
