"""Model endpoint repository (v4 new)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.model_gateway import ModelEndpoint
from .models import ModelEndpointRecord


def _record_to_endpoint(record: ModelEndpointRecord) -> ModelEndpoint:
    return ModelEndpoint(
        id=record.id,
        display_name=record.display_name,
        deployment_type=record.deployment_type,  # type: ignore[arg-type]
        base_url=record.base_url,
        adapter_mode=record.adapter_mode,
        enabled=bool(record.enabled),
    )


class ModelEndpointRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        endpoint_id: str,
        display_name: str,
        deployment_type: str,
        base_url: str,
        adapter_mode: str,
        created_at: str,
        updated_at: str,
        secret_ref: str | None = None,
        runtime_id: str | None = None,
        enabled: bool = True,
    ) -> ModelEndpointRecord:
        record = await self._session.get(ModelEndpointRecord, endpoint_id)
        if record is None:
            record = ModelEndpointRecord(
                id=endpoint_id,
                display_name=display_name,
                deployment_type=deployment_type,
                base_url=base_url,
                adapter_mode=adapter_mode,
                secret_ref=secret_ref,
                runtime_id=runtime_id,
                enabled=int(enabled),
                created_at=created_at,
                updated_at=updated_at,
            )
            self._session.add(record)
        else:
            record.display_name = display_name
            record.deployment_type = deployment_type
            record.base_url = base_url
            record.adapter_mode = adapter_mode
            record.secret_ref = secret_ref
            record.runtime_id = runtime_id
            record.enabled = int(enabled)
            record.updated_at = updated_at
        await self._session.flush()
        return record

    async def list(self) -> list[ModelEndpointRecord]:
        result = await self._session.execute(select(ModelEndpointRecord).order_by(ModelEndpointRecord.created_at))
        return list(result.scalars().all())

    async def get(self, endpoint_id: str) -> ModelEndpointRecord | None:
        return await self._session.get(ModelEndpointRecord, endpoint_id)

    async def delete(self, endpoint_id: str) -> None:
        record = await self._session.get(ModelEndpointRecord, endpoint_id)
        if record is not None:
            await self._session.delete(record)
            await self._session.flush()

    async def list_endpoints(self) -> list[ModelEndpoint]:
        records = await self.list()
        return [_record_to_endpoint(r) for r in records]
