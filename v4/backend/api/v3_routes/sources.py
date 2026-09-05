"""POST /api/sources/activate."""

from fastapi import APIRouter
from pydantic import BaseModel


def router() -> APIRouter:
    r = APIRouter(tags=["sources"])

    class ActivateBody(BaseModel):
        source: str  # "live_rtsp" | "replay"

    @r.post("/sources/activate")
    async def activate(body: ActivateBody):
        return {"ok": True, "active": body.source}

    return r
