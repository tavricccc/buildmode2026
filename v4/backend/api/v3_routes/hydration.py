"""GET /api/hydration/summary."""

from fastapi import APIRouter

from ...domain.policy import HydrationPolicy
from ...services.hydration_service import HydrationService


def router() -> APIRouter:
    r = APIRouter(tags=["hydration"])
    service = HydrationService()

    @r.get("/hydration/summary")
    async def summary(subject_id: str = "resident_demo", lookback_hours: int = 24):
        return service.summary(subject_id, HydrationPolicy(), lookback_hours=lookback_hours)

    return r
