"""GET /api/transcripts/recent."""

from fastapi import APIRouter


def router() -> APIRouter:
    r = APIRouter(tags=["transcripts"])

    @r.get("/transcripts/recent")
    async def recent(limit: int = 50):
        return {"transcripts": []}

    return r
