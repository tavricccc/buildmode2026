"""Analysis repository."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Analysis


class AnalysisRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        analysis_id: str,
        subject_id: str,
        analysis_type: str,
        window_start: str,
        window_end: str,
        input_summary: dict[str, Any],
        result: dict[str, Any],
        risk_level: str,
        config_version: str,
        created_at: str,
        model_call_id: str | None = None,
    ) -> Analysis:
        record = Analysis(
            id=analysis_id,
            subject_id=subject_id,
            analysis_type=analysis_type,
            window_start=window_start,
            window_end=window_end,
            input_summary_json=json.dumps(input_summary, default=str),
            result_json=json.dumps(result, default=str),
            risk_level=risk_level,
            model_call_id=model_call_id,
            config_version=config_version,
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_for_subject(self, subject_id: str, limit: int = 50) -> list[Analysis]:
        stmt = (
            select(Analysis)
            .where(Analysis.subject_id == subject_id)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
