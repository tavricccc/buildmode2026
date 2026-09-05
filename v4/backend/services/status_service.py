"""Status service (commit 1: real).

Periodically emits a ``system.status`` WebSocket message summarising
backend, stub, and DB health. The Dashboard reads it directly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..realtime import RealtimeBroadcaster
from ..settings import AppSettings


logger = logging.getLogger(__name__)


class StatusService:
    def __init__(self, broadcaster: RealtimeBroadcaster, settings: AppSettings) -> None:
        self._broadcaster = broadcaster
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def snapshot(self) -> dict[str, Any]:
        """Return the current status as a dict."""
        from ..repos.session import engine  # local import to avoid cycle

        db_ok = False
        try:
            eng = engine()
            db_ok = eng is not None
        except Exception:  # noqa: BLE001
            db_ok = False

        return {
            "backend": {
                "status": "healthy" if db_ok else "starting",
                "version": "0.1.0",
                "bind": f"{self._settings.bind_host}:{self._settings.bind_port}",
            },
            "stub_openai": {
                "status": "healthy" if self._settings.stub_enabled else "disabled",
                "bind": f"{self._settings.stub_host}:{self._settings.stub_port}",
            },
            "db": {
                "status": "healthy" if db_ok else "starting",
                "path": str(self._settings.db_path),
            },
            "capabilities": {
                "vision": "configuration_required",
                "analysis": "configuration_required",
                "transcription": "configuration_required",
                "speech": "configuration_required",
                "embedding": "configuration_required",
            },
        }

    async def run_forever(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    await self._broadcaster.broadcast("system.status", self.snapshot())
                except Exception:  # noqa: BLE001
                    logger.exception("status broadcast failed")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    def stop(self) -> None:
        self._stop.set()
