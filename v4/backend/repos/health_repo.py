"""Health repository (Fake Health scenarios)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import HealthSample


class HealthRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        sample_id: str,
        subject_id: str,
        metric: str,
        measured_at: str,
        created_at: str,
        value_num: float | None = None,
        value_text: str | None = None,
        unit: str | None = None,
        source: str = "fake",
        quality: str = "valid",
    ) -> HealthSample:
        record = HealthSample(
            id=sample_id,
            subject_id=subject_id,
            metric=metric,
            value_num=value_num,
            value_text=value_text,
            unit=unit,
            measured_at=measured_at,
            source=source,
            quality=quality,
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def latest(self, subject_id: str, metric: str) -> HealthSample | None:
        stmt = (
            select(HealthSample)
            .where(HealthSample.subject_id == subject_id, HealthSample.metric == metric)
            .order_by(HealthSample.measured_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()
