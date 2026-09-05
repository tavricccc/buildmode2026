"""Event repository."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Event


class EventRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        event_id: str,
        subject_id: str,
        event_type: str,
        status: str,
        occurred_at: str,
        confidence: float,
        dedup_key: str,
        schema_version: str,
        created_at: str,
        updated_at: str,
        attributes: dict[str, Any] | None = None,
        model_call_id: str | None = None,
        source_offset_ms: int | None = None,
        ended_at: str | None = None,
    ) -> Event:
        existing = await self._session.get(Event, event_id)
        if existing is None:
            record = Event(
                id=event_id,
                subject_id=subject_id,
                event_type=event_type,
                status=status,
                occurred_at=occurred_at,
                ended_at=ended_at,
                source_offset_ms=source_offset_ms,
                confidence=confidence,
                attributes_json=json.dumps(attributes or {}, default=str),
                model_call_id=model_call_id,
                dedup_key=dedup_key,
                schema_version=schema_version,
                created_at=created_at,
                updated_at=updated_at,
            )
            self._session.add(record)
        else:
            existing.status = status
            existing.ended_at = ended_at or existing.ended_at
            existing.confidence = confidence
            existing.attributes_json = json.dumps(attributes or {}, default=str)
            existing.updated_at = updated_at
            record = existing
        await self._session.flush()
        return record

    async def find_by_dedup(self, dedup_key: str) -> Event | None:
        stmt = select(Event).where(Event.dedup_key == dedup_key)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_filtered(
        self,
        event_type: str | None = None,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        stmt = select(Event).order_by(Event.occurred_at.desc()).limit(limit)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)
        if status:
            stmt = stmt.where(Event.status == status)
        if start:
            stmt = stmt.where(Event.occurred_at >= start)
        if end:
            stmt = stmt.where(Event.occurred_at <= end)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, event_id: str) -> Event | None:
        return await self._session.get(Event, event_id)
