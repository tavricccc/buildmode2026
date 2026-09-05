"""POST /api/demo/reset (dev only)."""

import os

from fastapi import APIRouter, HTTPException


def router() -> APIRouter:
    r = APIRouter(tags=["demo"])

    @r.post("/demo/reset")
    async def reset():
        if not (os.environ.get("V4_DEV_MODE") or "").lower() in {"1", "true", "yes"}:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True, "mode": "dev"}

    return r
