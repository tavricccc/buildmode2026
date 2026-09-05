"""Stub server contract tests."""

from __future__ import annotations

import socket

import httpx
import pytest
import uvicorn

from v4.backend.stub import build_stub_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def stub_url():
    port = _free_port()
    config = uvicorn.Config(build_stub_app(), host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    import asyncio
    task = asyncio.create_task(server.serve())
    for _ in range(80):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


@pytest.mark.asyncio
async def test_models_endpoint(stub_url: str) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{stub_url}/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert "data" in data
    assert any(m["id"] == "vision-stub" for m in data["data"])


@pytest.mark.asyncio
async def test_chat_completions_endpoint(stub_url: str) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{stub_url}/v1/chat/completions",
            json={"model": "vision-stub", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"].startswith("{")


@pytest.mark.asyncio
async def test_audio_transcriptions_endpoint(stub_url: str) -> None:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{stub_url}/v1/audio/transcriptions",
            files={"file": ("probe.wav", b"RIFF", "audio/wav")},
            data={"model": "transcription-stub"},
        )
    assert r.status_code == 200
    assert r.json()["text"] == "probe"
