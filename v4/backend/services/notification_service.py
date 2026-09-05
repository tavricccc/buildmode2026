"""Notification service stub (v4 12)."""

from __future__ import annotations

from typing import Any

from ..domain.enums import NotificationStatus
from ..state_machines import NotificationContext, notification_transition


class NotificationService:
    def transition(self, ctx: NotificationContext) -> NotificationStatus:
        return notification_transition(ctx)

    async def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        from ..repos.notification_repo import NotificationRepo
        from ..repos.session import session_scope

        async with session_scope() as session:
            repo = NotificationRepo(session)
            records = await repo.list_recent(limit)
        return [
            {
                "id": r.id,
                "action_id": r.action_id,
                "channel": r.channel,
                "status": r.status,
                "created_at": r.created_at,
            }
            for r in records
        ]
