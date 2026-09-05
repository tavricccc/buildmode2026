"""End-to-end smoke: real backend + real stub server."""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient

from v4.backend.app import create_app
from v4.backend.stub import build_stub_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_status_via_backend_and_models_via_stub(app_settings) -> None:
    port = _free_port()
    config = uvicorn.Config(build_stub_app(), host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(80):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        app = create_app(settings=app_settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r1 = await c.get("/api/status")
            assert r1.status_code == 200
        async with httpx.AsyncClient() as c2:
            r2 = await c2.get(f"http://127.0.0.1:{port}/v1/models")
        assert r2.status_code == 200
        ids = {m["id"] for m in r2.json()["data"]}
        assert "vision-stub" in ids
    finally:
        server.should_exit = True
        await task
