"""Stub OpenAI-compatible FastAPI app.

Endpoints:
- GET  /v1/models
- POST /v1/chat/completions
- POST /v1/audio/transcriptions
- POST /v1/audio/speech

The server runs in the same process as the main backend
(``app.state.stub_task``) when ``V4_STUB_ENABLED`` is true.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from ..settings import AppSettings
from .fixtures import analysis_fixture, speech_fixture, transcription_fixture, vision_fixture


logger = logging.getLogger(__name__)


_MODELS: list[dict[str, Any]] = [
    {"id": "vision-stub", "object": "model", "owned_by": "care-agent-v4"},
    {"id": "analysis-stub", "object": "model", "owned_by": "care-agent-v4"},
    {"id": "transcription-stub", "object": "model", "owned_by": "care-agent-v4"},
    {"id": "speech-stub", "object": "model", "owned_by": "care-agent-v4"},
]


def build_stub_app() -> FastAPI:
    app = FastAPI(title="care-agent-v4 stub", version="0.1.0")

    @app.get("/v1/models")
    async def list_models():
        return {"object": "list", "data": _MODELS}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        body = await request.json()
        model = body.get("model", "vision-stub")
        if "vision" in model:
            return vision_fixture(model)
        if "analysis" in model:
            return analysis_fixture(model)
        return speech_fixture(model)

    @app.post("/v1/audio/transcriptions")
    async def audio_transcriptions(
        file: UploadFile = File(...),
        model: str = Form("transcription-stub"),
    ):
        return transcription_fixture()

    @app.post("/v1/audio/speech")
    async def audio_speech(request: Request):
        body = await request.json()
        # We do not actually generate audio in the stub. Return a
        # minimal JSON message so the contract test still passes.
        return JSONResponse({"audio_bytes": "", "content_type": "audio/mpeg", "model": body.get("model", "speech-stub")})

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    return app


_stub_task: asyncio.Task[None] | None = None
_stub_server: uvicorn.Server | None = None


async def start_stub_server(settings: AppSettings) -> None:
    global _stub_task, _stub_server
    if not settings.stub_enabled:
        return
    if _stub_task is not None:
        return
    config = uvicorn.Config(
        build_stub_app(),
        host=settings.stub_host,
        port=settings.stub_port,
        log_level="warning",
        loop="asyncio",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    _stub_server = server
    _stub_task = asyncio.create_task(server.serve(), name="stub-openai")
    # Wait until the server is actually serving.
    for _ in range(100):
        if server.started:
            return
        await asyncio.sleep(0.05)


async def stop_stub_server() -> None:
    global _stub_task, _stub_server
    if _stub_server is not None:
        _stub_server.should_exit = True
    if _stub_task is not None:
        try:
            await _stub_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _stub_task = None
        _stub_server = None
