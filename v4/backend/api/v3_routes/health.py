"""Health scenario endpoints (v3 05)."""

from fastapi import APIRouter
from pydantic import BaseModel

from ...services.health_scenario_service import HealthScenarioService


class ScenarioBody(BaseModel):
    scenario: str


def router() -> APIRouter:
    r = APIRouter(tags=["health"])
    service = HealthScenarioService(subject_id="resident_demo")

    @r.get("/health/current")
    async def current():
        return {"subject_id": "resident_demo", "snapshot": {}}

    @r.get("/health/scenarios")
    async def list_scenarios():
        return {"scenarios": service.list_scenarios()}

    @r.post("/health/scenario")
    async def apply_scenario(body: ScenarioBody):
        return service.apply(body.scenario)

    return r
