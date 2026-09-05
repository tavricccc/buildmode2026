"""Model install / probe / activate / delete API (v4 05)."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.model_endpoint_service import ModelEndpointService
from ..services.model_install_service import ModelInstallService


class InstallBody(BaseModel):
    endpoint_id: str
    capability: str
    remote_model_id: str
    display_name: str
    source_type: str  # "local_catalog" | "cloud_provider"
    catalog_id: str | None = None


def router(endpoint_service: ModelEndpointService) -> APIRouter:
    r = APIRouter(tags=["models"])
    install_service = ModelInstallService(endpoint_service.registry())

    @r.get("/models/installed")
    async def list_installed():
        return {"installed": []}

    @r.post("/models/install")
    async def install(body: InstallBody):
        return await install_service.start_install_job(
            endpoint_id=body.endpoint_id,
            capability=body.capability,
            remote_model_id=body.remote_model_id,
            display_name=body.display_name,
        )

    @r.post("/models/{model_id}/probe")
    async def probe(model_id: str, body: InstallBody):
        return await install_service.probe(
            endpoint_id=body.endpoint_id,
            capability=body.capability,
            remote_model_id=body.remote_model_id,
        )

    @r.post("/models/{model_id}/activate")
    async def activate(model_id: str):
        return {"ok": True, "model_id": model_id, "status": "active"}

    @r.delete("/models/{model_id}")
    async def delete(model_id: str):
        return {"ok": True, "model_id": model_id, "status": "removed"}

    return r
