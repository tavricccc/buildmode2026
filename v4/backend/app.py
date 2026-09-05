"""FastAPI application factory.

Wires the lifespan (database, migrations, broadcaster, stub server), CORS,
all API routers, and the ``/ws`` WebSocket endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import register_routers
from .api.errors import register_exception_handlers
from .realtime import RealtimeBroadcaster
from .realtime.ws import attach_websocket
from .repos.session import dispose_engine, init_engine, run_migrations
from .settings import AppSettings
from .stub import start_stub_server, stop_stub_server
from .services.status_service import StatusService


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: AppSettings = app.state.settings
    logger.info("starting v4 backend", extra={"bind": f"{settings.bind_host}:{settings.bind_port}"})

    # Database: init engine and run migrations.
    await init_engine(settings)
    await run_migrations(settings)
    logger.info("database ready", extra={"db": str(settings.db_path)})

    # Broadcaster (in-memory pub/sub used by the WS endpoint).
    broadcaster = getattr(app.state, "broadcaster", None) or RealtimeBroadcaster()
    app.state.broadcaster = broadcaster
    logger.info("broadcaster ready")

    # Local stub OpenAI-compatible server.
    if settings.stub_enabled:
        await start_stub_server(settings)
        logger.info("stub OpenAI server up", extra={"port": settings.stub_port})

    # Periodic status push.
    status_service = getattr(app.state, "status_service", None) or StatusService(broadcaster=broadcaster, settings=settings)
    app.state.status_service = status_service
    status_task = asyncio.create_task(status_service.run_forever(), name="status-heartbeat")
    app.state.status_task = status_task

    try:
        yield
    finally:
        logger.info("shutting down v4 backend")
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass
        if settings.stub_enabled:
            await stop_stub_server()
        await dispose_engine()


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_env()
    app = FastAPI(
        title="Care Agent v4 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    broadcaster = RealtimeBroadcaster()
    app.state.broadcaster = broadcaster
    app.state.status_service = StatusService(broadcaster=broadcaster, settings=settings)

    # CORS: in this round the frontend is served by Vite on a different port
    # during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    register_routers(app)
    attach_websocket(app)

    return app
