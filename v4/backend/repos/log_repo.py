"""Log repository (writes go through ``app_log_sink``; reads via this class)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AppLog


class LogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        ts: str,
        level: str,
        component: str,
        message: str,
        event_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AppLog:
        record = AppLog(
            ts=ts,
            level=level,
            component=component,
            event_id=event_id,
            message=message,
            context_json=json.dumps(context or {}, default=str),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_recent(self, limit: int = 200) -> list[AppLog]:
        stmt = select(AppLog).order_by(AppLog.ts.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
