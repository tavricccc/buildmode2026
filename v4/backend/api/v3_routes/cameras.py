"""GET /api/cameras."""

from fastapi import APIRouter


def router() -> APIRouter:
    r = APIRouter(tags=["cameras"])

    @r.get("/cameras")
    async def list_cameras():
        return {
            "cameras": [
                {
                    "id": "replay-default",
                    "kind": "replay",
                    "healthy": True,
                    "last_frame_seq": 0,
                    "last_frame_at_ms": 0,
                }
            ]
        }

    return r
