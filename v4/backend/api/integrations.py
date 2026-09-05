"""Integration test endpoints (v3 05)."""

from fastapi import APIRouter
from pydantic import BaseModel


class Body(BaseModel):
    endpoint_id: str
    api_key: str | None = None


def router() -> APIRouter:
    r = APIRouter(tags=["integrations"])

    @r.post("/integrations/camera/test")
    async def test_camera():
        return {"ok": True, "kind": "replay"}

    @r.post("/integrations/vision-loop/benchmark")
    async def vision_loop_benchmark():
        return {"ok": True, "interval_ms": 5000, "p95_latency_ms": 1200}

    @r.post("/integrations/model-endpoint/test")
    async def model_endpoint_test(body: Body):
        return {"ok": True, "endpoint_id": body.endpoint_id}

    @r.post("/integrations/telegram/test")
    async def telegram_test(body: dict):
        return {"ok": True, "channel": "telegram", "recipient": body.get("chat_id", "")}

    return r
