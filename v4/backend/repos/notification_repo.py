"""Notification repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import NotificationDelivery


class NotificationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_recent(self, limit: int = 50) -> list[NotificationDelivery]:
        stmt = (
            select(NotificationDelivery)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
