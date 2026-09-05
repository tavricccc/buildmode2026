"""Evidence repository."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Evidence


class EvidenceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        evidence_id: str,
        subject_id: str,
        source_type: str,
        captured_at: str,
        created_at: str,
        source_uri: str | None = None,
        source_offset_start_ms: int | None = None,
        source_offset_end_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        record = Evidence(
            id=evidence_id,
            subject_id=subject_id,
            source_type=source_type,
            source_uri=source_uri,
            source_offset_start_ms=source_offset_start_ms,
            source_offset_end_ms=source_offset_end_ms,
            captured_at=captured_at,
            metadata_json=json.dumps(metadata or {}, default=str),
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_for_event(self, event_id: str) -> list[Evidence]:
        from .models import EventEvidence

        stmt = (
            select(Evidence)
            .join(EventEvidence, EventEvidence.evidence_id == Evidence.id)
            .where(EventEvidence.event_id == event_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
