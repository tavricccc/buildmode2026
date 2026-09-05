"""Hydration service stub."""

from __future__ import annotations

from typing import Any

from ..domain.policy import HydrationPolicy


class HydrationService:
    def summary(self, subject_id: str, policy: HydrationPolicy, *, lookback_hours: int = 24) -> dict[str, Any]:
        return {
            "subject_id": subject_id,
            "window_hours": lookback_hours,
            "confirmed_sessions": 0,
            "estimated_total_ml": 0.0,
            "target_ml": policy.target_ml_per_day,
            "completion_ratio": 0.0,
            "last_drink_at": None,
            "coverage": 0.0,
        }
