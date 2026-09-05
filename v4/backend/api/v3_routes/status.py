"""GET /api/status."""

from fastapi import APIRouter, Depends

from ...services.status_service import StatusService
from ..deps import get_status_service


def router(service: StatusService) -> APIRouter:
    r = APIRouter(tags=["status"])

    @r.get("/status")
    async def status(s: StatusService = Depends(lambda: service)):
        return s.snapshot()

    return r
