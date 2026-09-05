"""Model endpoint service stub (v4 13).

Full implementation lands in commit 2. This round returns a typed
surface that the API can wire up immediately.
"""

from __future__ import annotations

from ..adapters.model_gateway import ModelEndpoint, ModelEndpointRegistry
from ..repos.model_endpoint_repo import ModelEndpointRepo
from ..repos.session import session_scope


class ModelEndpointService:
    def __init__(self, registry: ModelEndpointRegistry) -> None:
        self._registry = registry

    def registry(self) -> ModelEndpointRegistry:
        return self._registry

    async def refresh_registry(self) -> None:
        async with session_scope() as session:
            repo = ModelEndpointRepo(session)
            for endpoint in await repo.list_endpoints():
                self._registry.upsert(endpoint)

    async def list(self) -> list[ModelEndpoint]:
        return self._registry.all()

    async def upsert(
        self,
        *,
        endpoint_id: str,
        display_name: str,
        deployment_type: str,
        base_url: str,
        adapter_mode: str,
    ) -> ModelEndpoint:
        from ..domain.time import isoformat, utc_now

        async with session_scope() as session:
            repo = ModelEndpointRepo(session)
            record = await repo.upsert(
                endpoint_id=endpoint_id,
                display_name=display_name,
                deployment_type=deployment_type,
                base_url=base_url,
                adapter_mode=adapter_mode,
                created_at=isoformat(utc_now()),
                updated_at=isoformat(utc_now()),
            )
            endpoint = ModelEndpoint(
                id=record.id,
                display_name=record.display_name,
                deployment_type=record.deployment_type,  # type: ignore[arg-type]
                base_url=record.base_url,
                adapter_mode=record.adapter_mode,
                enabled=bool(record.enabled),
            )
        self._registry.upsert(endpoint)
        return endpoint

    async def delete(self, endpoint_id: str) -> None:
        async with session_scope() as session:
            repo = ModelEndpointRepo(session)
            await repo.delete(endpoint_id)
        self._registry.remove(endpoint_id)

    async def test(self, endpoint_id: str) -> dict:
        endpoint = self._registry.get(endpoint_id)
        if endpoint is None:
            return {"ok": False, "code": "ENDPOINT_AUTH_FAILED", "detail": "unknown endpoint"}
        try:
            models = await endpoint.client().list_models()
            return {"ok": True, "models": [m.id for m in models]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "code": "RUNTIME_FAILED", "detail": str(exc)}
