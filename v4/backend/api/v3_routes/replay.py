"""Replay control endpoints (v3 05)."""

from fastapi import APIRouter
from pydantic import BaseModel

from ...services.replay_service import ReplayService


class ReplayLoadBody(BaseModel):
    video_id: str


def router(service: ReplayService) -> APIRouter:
    r = APIRouter(tags=["replay"])

    @r.get("/replay/list")
    async def list_replays():
        return {"replays": service.list()}

    @r.post("/replay/load")
    async def load(body: ReplayLoadBody):
        return service.load(body.video_id)

    @r.post("/replay/start")
    async def start():
        return service.start()

    @r.post("/replay/pause")
    async def pause():
        return service.pause()

    @r.post("/replay/reset")
    async def reset():
        return service.reset()

    @r.get("/replay/status")
    async def status():
        return service.status()

    return r
