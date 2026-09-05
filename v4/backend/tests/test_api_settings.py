"""/api/settings/* endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from v4.backend.app import create_app


@pytest.mark.asyncio
async def test_settings_round_trip(app_settings) -> None:
    app = create_app(settings=app_settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # GET active (none)
        r0 = await c.get("/api/settings")
        assert r0.status_code == 200
        # Draft
        r1 = await c.post(
            "/api/settings/draft",
            json={"patch": {"fall": {"min_confidence": 0.65}}, "base_version": r0.json()["version_id"]},
        )
        assert r1.status_code == 200
        draft_id = r1.json()["draft_id"]
        # Apply
        r2 = await c.post(
            "/api/settings/apply",
            json={"draft_id": draft_id, "base_version": "", "confirm": True},
        )
        assert r2.status_code == 200
        assert r2.json()["status"].startswith("applied")
        # Conflict on stale base_version
        r3 = await c.post(
            "/api/settings/apply",
            json={"draft_id": draft_id, "base_version": "bogus", "confirm": True},
        )
        assert r3.status_code == 409
        body = r3.json()
        assert body["error"]["code"] == "CONFIG_VERSION_CONFLICT"
