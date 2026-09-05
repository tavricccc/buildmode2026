"""Settings API (v4 05 §"Settings API")."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.secret_service import SecretService
from ..services.settings_service import SettingsService


class DraftBody(BaseModel):
    patch: dict[str, Any]
    base_version: str | None = None


class ApplyBody(BaseModel):
    draft_id: str
    base_version: str
    confirm: bool = False


class SecretBody(BaseModel):
    name: str
    value: str = Field(min_length=1)


def router(settings_service: SettingsService, secret_service: SecretService) -> APIRouter:
    r = APIRouter(tags=["settings"])

    @r.get("/settings/schema")
    async def schema():
        return settings_service.schema()

    @r.get("/settings")
    async def get_active():
        bundle = await settings_service.active_bundle()
        version = await settings_service.active_version()
        return {"version_id": version, "settings": bundle.model_dump(mode="json")}

    @r.post("/settings/draft")
    async def draft(body: DraftBody):
        return await settings_service.draft(body.patch, body.base_version)

    @r.post("/settings/test")
    async def test(draft_id: str):
        return await settings_service.test(draft_id)

    @r.post("/settings/apply")
    async def apply(body: ApplyBody):
        return await settings_service.apply(body.draft_id, body.base_version, confirm=body.confirm)

    @r.get("/settings/versions")
    async def list_versions():
        return {"versions": await settings_service.list_versions()}

    @r.post("/settings/rollback/{version_id}")
    async def rollback(version_id: str):
        return await settings_service.rollback(version_id)

    # Secret endpoints (write-only).
    @r.put("/secrets/{name}")
    async def set_secret(name: str, body: SecretBody):
        if body.name != name:
            raise HTTPException(status_code=422, detail="path/name mismatch")
        meta = secret_service.set(name, body.value)
        return {
            "configured": meta.configured,
            "updated_at": meta.updated_at,
            "fingerprint_suffix": meta.fingerprint_suffix,
        }

    @r.delete("/secrets/{name}")
    async def clear_secret(name: str):
        meta = secret_service.clear(name)
        return {
            "configured": meta.configured,
            "updated_at": meta.updated_at,
            "fingerprint_suffix": meta.fingerprint_suffix,
        }

    @r.get("/secrets/{name}")
    async def get_secret(name: str):
        meta = secret_service.metadata(name)
        return {
            "configured": meta.configured,
            "updated_at": meta.updated_at,
            "fingerprint_suffix": meta.fingerprint_suffix,
        }

    return r
