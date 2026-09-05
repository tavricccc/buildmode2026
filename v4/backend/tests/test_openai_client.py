"""OpenAI client tests against the local stub."""

from __future__ import annotations

import asyncio
import socket

import pytest
import uvicorn

from v4.backend.adapters.openai_client import OpenAICompatibleClient
from v4.backend.adapters.openai_schemas import ChatRequest, ChatMessage
from v4.backend.stub import build_stub_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def stub_server():
    port = _free_port()
    config = uvicorn.Config(build_stub_app(), host="127.0.0.1", port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
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
async def test_list_models(stub_server: str) -> None:
    async with OpenAICompatibleClient(base_url=stub_server) as client:
        models = await client.list_models()
    ids = {m.id for m in models}
    assert {"vision-stub", "analysis-stub", "transcription-stub"}.issubset(ids)


@pytest.mark.asyncio
async def test_chat_completions(stub_server: str) -> None:
    async with OpenAICompatibleClient(base_url=stub_server) as client:
        req = ChatRequest(
            model="vision-stub",
            messages=[ChatMessage(role="user", content="hello")],
        )
        resp = await client.chat_completions(req)
    assert resp.choices
    assert resp.choices[0].message.content
