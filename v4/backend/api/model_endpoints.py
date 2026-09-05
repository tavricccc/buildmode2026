"""Model endpoint API (v4 05)."""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..adapters.model_gateway import ModelEndpoint, ModelEndpointRegistry
from ..services.model_endpoint_service import ModelEndpointService


class EndpointBody(BaseModel):
    id: str
    display_name: str
    deployment_type: str  # "local" | "cloud"
    base_url: str
    adapter_mode: str = "openai_chat"


def router(service: ModelEndpointService, registry: ModelEndpointRegistry) -> APIRouter:
    r = APIRouter(tags=["model-endpoints"])

    @r.get("/model-endpoints")
    async def list_endpoints():
        endpoints = await service.list()
        return {
            "endpoints": [
                {
                    "id": e.id,
                    "display_name": e.display_name,
                    "deployment_type": (
                        e.deployment_type.value
                        if hasattr(e.deployment_type, "value")
                        else str(e.deployment_type)
                    ),
                    "base_url": e.base_url,
                    "adapter_mode": e.adapter_mode,
                    "enabled": e.enabled,
                }
                for e in endpoints
            ]
        }

    @r.post("/model-endpoints")
    async def upsert(body: EndpointBody):
        endpoint = await service.upsert(
            endpoint_id=body.id,
            display_name=body.display_name,
            deployment_type=body.deployment_type,
            base_url=body.base_url,
            adapter_mode=body.adapter_mode,
        )
        return {"id": endpoint.id, "ok": True}

    @r.patch("/model-endpoints/{endpoint_id}")
    async def update(endpoint_id: str, body: dict[str, Any]):
        return await service.upsert(
            endpoint_id=endpoint_id,
            display_name=body.get("display_name", endpoint_id),
            deployment_type=body.get("deployment_type", "local"),
            base_url=body.get("base_url", ""),
            adapter_mode=body.get("adapter_mode", "openai_chat"),
        )

    @r.delete("/model-endpoints/{endpoint_id}")
    async def delete(endpoint_id: str):
        await service.delete(endpoint_id)
        return {"ok": True}

    @r.post("/model-endpoints/{endpoint_id}/test")
    async def test(endpoint_id: str):
        return await service.test(endpoint_id)

    @r.get("/model-endpoints/{endpoint_id}/models")
    async def list_models(endpoint_id: str):
        endpoint = registry.get(endpoint_id)
        if endpoint is None:
            return {"models": []}
        try:
            models = await endpoint.client().list_models()
            return {"models": [m.id for m in models]}
        except Exception as exc:  # noqa: BLE001
            return {"models": [], "error": str(exc)}

    return r
