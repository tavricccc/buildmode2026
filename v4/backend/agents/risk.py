"""Risk Agent (v3 02)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskResult:
    risk_level: str  # low | moderate | elevated | high
    reason_codes: tuple[str, ...]
    window_label: str
    uncertainty: tuple[str, ...]
    proposed_actions: tuple[dict, ...]


class RiskAgent:
    name = "risk"

    def __init__(self, gateway=None) -> None:
        self._gateway = gateway

    async def run(self, event_understanding=None, health_context=None) -> RiskResult:
        return RiskResult(
            risk_level="moderate",
            reason_codes=("synthetic_stub",),
            window_label="24h",
            uncertainty=("model_not_called",),
            proposed_actions=(),
        )
