"""GET /api/observer/findings."""

from fastapi import APIRouter

from ...services.observer_service import ObserverService


def router(service: ObserverService) -> APIRouter:
    r = APIRouter(tags=["observer"])

    @r.get("/observer/findings")
    async def list_findings(limit: int = 50):
        return {"findings": []}

    @r.post("/observer/run")
    async def run_now():
        import datetime as _dt
        today = _dt.date.today().isoformat()
        finding = await service.run_once(
            subject_id="resident_demo",
            summary_date=today,
            event_counts={"fall": 0, "hydration": 0},
            hydration_ml=0.0,
            health_snapshot={},
            coverage=0.0,
            baseline={"fall": 0.0, "hydration": 0.0},
        )
        return {"finding_id": finding.id, "statement": finding.statement}

    return r
