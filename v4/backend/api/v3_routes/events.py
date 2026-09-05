"""GET /api/events, GET /api/events/{id}."""

from fastapi import APIRouter, HTTPException


def router() -> APIRouter:
    r = APIRouter(tags=["events"])

    @r.get("/events")
    async def list_events(
        type: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ):
        # Stub — full implementation lands in a later commit.
        return {"events": [], "limit": limit, "filters": {"type": type, "status": status, "start": start, "end": end}}

    @r.get("/events/{event_id}")
    async def get_event(event_id: str):
        raise HTTPException(status_code=404, detail=f"event {event_id} not found")

    return r
