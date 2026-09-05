"""Stub entry point (``python -m v4.backend.stub``)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal

import uvicorn

from ..logging import configure_logging
from ..settings import AppSettings
from .server import build_stub_app


async def _run(host: str, port: int) -> None:
    config = uvicorn.Config(build_stub_app(), host=host, port=port, log_level="warning", loop="asyncio")
    server = uvicorn.Server(config)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _stop(*_):
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    serve_task = asyncio.create_task(server.serve())
    await stop.wait()
    server.should_exit = True
    await serve_task


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18181)
    args = parser.parse_args()
    configure_logging(AppSettings.from_env())
    logging.getLogger(__name__).info("starting stub", extra={"host": args.host, "port": args.port})
    asyncio.run(_run(args.host, args.port))


if __name__ == "__main__":
    main()
