"""Model call repository (audit)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ModelCall


class ModelCallRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        call_id: str,
        endpoint_id: str,
        deployment_type: str,
        model_id: str,
        capability: str,
        input_hash: str,
        prompt_version: str,
        schema_version: str,
        status: str,
        latency_ms: int,
        tokens_in: int | None,
        tokens_out: int | None,
        error_code: str | None,
        response_json: str,
        created_at: str,
        config_version: str | None,
    ) -> ModelCall:
        record = ModelCall(
            id=call_id,
            provider=endpoint_id,
            model=model_id,
            purpose=capability,
            input_hash=input_hash,
            prompt_version=prompt_version,
            schema_version=schema_version,
            status=status,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error_code=error_code,
            response_json=response_json,
            created_at=created_at,
            model_endpoint_id=endpoint_id,
            config_version=config_version,
            capability=capability,
        )
        # ``deployment_type`` is encoded in the ``provider`` column for v3
        # compat; v4 stores it via ``model_endpoint_id`` lookup elsewhere.
        self._session.add(record)
        return record

    async def flush(self) -> None:
        await self._session.flush()

    async def list_recent(self, limit: int = 50) -> list[ModelCall]:
        stmt = select(ModelCall).order_by(ModelCall.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
