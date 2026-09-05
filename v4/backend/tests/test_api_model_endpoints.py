"""/api/model-endpoints endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from v4.backend.app import create_app


@pytest.mark.asyncio
async def test_create_endpoint_then_list(app_settings) -> None:
    app = create_app(settings=app_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/model-endpoints",
            json={
                "id": "local-stub",
                "display_name": "Local Stub",
                "deployment_type": "local",
                "base_url": "http://127.0.0.1:18181",
                "adapter_mode": "openai_chat",
            },
        )
        assert r.status_code == 200
        r2 = await c.get("/api/model-endpoints")
        assert r2.status_code == 200
        assert any(e["id"] == "local-stub" for e in r2.json()["endpoints"])
