"""Agent orchestrator.

Runs agents in the canonical v3 order: Understanding → Health Context
→ Risk → Intervention. Each step is independent: the orchestrator
handles the wiring, never the agents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .event_understanding import EventUnderstandingAgent
from .health_context import HealthContextAgent
from .intervention import InterventionAgent
from .risk import RiskAgent


logger = logging.getLogger(__name__)


@dataclass
class AgentOutput:
    understanding: object | None = None
    health_context: object | None = None
    risk: object | None = None
    intervention: object | None = None


class AgentOrchestrator:
    def __init__(
        self,
        understanding: EventUnderstandingAgent,
        health_context: HealthContextAgent,
        risk: RiskAgent,
        intervention: InterventionAgent,
    ) -> None:
        self.understanding = understanding
        self.health_context = health_context
        self.risk = risk
        self.intervention = intervention

    async def run_for_event(self, event_id: str, observations_summary: str, evidence_ids: tuple[str, ...]) -> AgentOutput:
        out = AgentOutput()
        out.understanding = await self.understanding.run(event_id, observations_summary, evidence_ids)
        out.health_context = await self.health_context.run(subject_id="resident_demo", window_label="24h")
        out.risk = await self.risk.run(event_understanding=out.understanding, health_context=out.health_context)
        return out
