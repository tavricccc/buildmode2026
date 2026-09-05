"""GET /api/setup/status, /api/setup/prerequisites (v4 06)."""

from fastapi import APIRouter

from ..services.setup_service import SetupService


def router(service: SetupService) -> APIRouter:
    r = APIRouter(tags=["setup"])

    @r.get("/setup/status")
    async def status():
        return service.status()

    @r.get("/setup/prerequisites")
    async def prerequisites():
        return {"items": service.prerequisites()}

    return r
