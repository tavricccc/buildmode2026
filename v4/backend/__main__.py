"""Entry point: ``python -m v4.backend``.

Boots the FastAPI app on the configured bind address and starts the local
stub OpenAI-compatible server in the same process (see
``backend/stub/server.py``).
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn

from .app import create_app
from .settings import AppSettings
from .logging import configure_logging


logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = AppSettings.from_env()
    configure_logging(settings)
    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        log_level=settings.log_level.lower(),
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("interrupted, shutting down")


if __name__ == "__main__":
    main()
