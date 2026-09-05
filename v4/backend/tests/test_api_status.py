"""/api/status endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from v4.backend.app import create_app


@pytest.mark.asyncio
async def test_status_endpoint_returns_healthy(app_settings) -> None:
    app = create_app(settings=app_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"]["status"] in {"healthy", "starting"}
    assert "stub_openai" in body
    assert "db" in body
