"""Catalog API (v4 05)."""

from fastapi import APIRouter

from ..services.catalog_service import CatalogService
from ..services.model_endpoint_service import ModelEndpointService


def router(catalog: CatalogService, endpoint_service: ModelEndpointService) -> APIRouter:
    r = APIRouter(tags=["models"])

    @r.get("/models/catalog")
    async def list_catalog():
        return {"models": catalog.list()}

    @r.get("/models/catalog/{catalog_id}")
    async def get_catalog_entry(catalog_id: str):
        entry = catalog.get(catalog_id)
        if entry is None:
            return {"error": "not_found"}
        return entry

    return r
