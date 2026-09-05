"""POST /api/health/analyze, /api/events/{id}/analyze (v3 05)."""

from fastapi import APIRouter

from ...domain.ids import new_id
from ...domain.time import isoformat, utc_now
from ...services.analysis_service import AnalysisService
from fastapi import Request


def router() -> APIRouter:
    r = APIRouter(tags=["analysis"])
    service = AnalysisService()

    @r.post("/health/analyze")
    async def analyze_health(request: Request, subject_id: str = "resident_demo", window: str = "24h"):
        broadcaster = request.app.state.broadcaster
        result = await service.analyse(
            subject_id=subject_id,
            window_start=isoformat(utc_now()),
            window_end=isoformat(utc_now()),
        )
        await broadcaster.broadcast(
            "local_analysis.completed",
            {
                "subject_id": subject_id,
                "window": window,
                "analysis_id": new_id("ana"),
            },
        )
        return {"analysis": result.model_dump(mode="json")}

    @r.post("/events/{event_id}/analyze")
    async def analyze_event(event_id: str, request: Request):
        broadcaster = request.app.state.broadcaster
        await broadcaster.broadcast(
            "local_analysis.completed",
            {"event_id": event_id, "analysis_id": new_id("ana")},
        )
        return {"analysis_id": new_id("ana"), "event_id": event_id}

    return r
