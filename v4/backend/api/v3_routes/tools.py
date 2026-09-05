"""GET /api/tools/calls (v3 05)."""

from fastapi import APIRouter


def router() -> APIRouter:
    r = APIRouter(tags=["tools"])

    @r.get("/tools/calls")
    async def list_tool_calls(limit: int = 100):
        return {"tool_calls": []}

    return r
