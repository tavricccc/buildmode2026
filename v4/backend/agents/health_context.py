"""Health Context Agent (v3 02 / v4 07)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthContextResult:
    subject_id: str
    summary_zh: str
    noteworthy: tuple[str, ...]
    missing: tuple[str, ...]
    suggestions: tuple[str, ...]


class HealthContextAgent:
    name = "health_context"

    def __init__(self, gateway=None) -> None:
        self._gateway = gateway

    async def run(self, subject_id: str, window_label: str) -> HealthContextResult:
        return HealthContextResult(
            subject_id=subject_id,
            summary_zh=f"{window_label} 健康脈絡已彙整。",
            noteworthy=(),
            missing=("尚未整合 ASR 對話",),
            suggestions=(),
        )
