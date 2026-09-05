"""GET /api/notifications, POST /api/notifications/test."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.notification_service import NotificationService


class TestNotificationBody(BaseModel):
    chat_id: str
    text: str = "test"


def router(service: NotificationService) -> APIRouter:
    r = APIRouter(tags=["notifications"])

    @r.get("/notifications")
    async def list_notifications(limit: int = 50):
        return {"notifications": await service.list_recent(limit=limit)}

    @r.post("/notifications/test")
    async def test_notification(body: TestNotificationBody):
        if not (os.environ.get("V4_DEV_MODE") or "").lower() in {"1", "true", "yes"}:
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True, "channel": "telegram", "recipient": body.chat_id}

    return r
