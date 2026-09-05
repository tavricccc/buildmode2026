"""Event Understanding Agent (v3 02).

Inputs: a confirmed event, its observations, evidence refs.
Outputs: a typed summary with supporting / opposing evidence and
uncertainty notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventUnderstandingResult:
    event_id: str
    summary_zh: str
    supporting: tuple[str, ...]
    opposing: tuple[str, ...]
    uncertainty: tuple[str, ...]
    confidence: float


class EventUnderstandingAgent:
    name = "event_understanding"

    def __init__(self, gateway=None, repo=None) -> None:
        self._gateway = gateway
        self._repo = repo

    async def run(self, event_id: str, observations_summary: str, evidence_ids: tuple[str, ...]) -> EventUnderstandingResult:
        # In a fuller implementation the agent would call the analysis
        # model slot with a typed prompt. For this round we return a
        # deterministic stub.
        return EventUnderstandingResult(
            event_id=event_id,
            summary_zh=f"事件摘要：{observations_summary}",
            supporting=evidence_ids,
            opposing=(),
            uncertainty=("limited_evidence",),
            confidence=0.6,
        )
