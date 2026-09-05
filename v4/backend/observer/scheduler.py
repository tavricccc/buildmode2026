"""Observer scheduler (v4 10)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObserverTrigger:
    scheduled_for: datetime
    reason: str  # "scheduled" | "manual"


class ObserverScheduler:
    """Cooperative scheduler.

    Calls the user-supplied ``runner`` coroutine at the configured
    cadence. Manual triggers are issued via ``trigger_now``.
    """

    def __init__(
        self,
        runner: Callable[[ObserverTrigger], Awaitable[None]],
        *,
        interval_seconds: float = 24 * 3600,
        auto_run: bool = False,
    ) -> None:
        self._runner = runner
        self._interval = interval_seconds
        self._auto = auto_run
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._manual: asyncio.Event = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="observer-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def trigger_now(self) -> None:
        self._manual.set()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._auto:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                else:
                    return
            try:
                trigger = ObserverTrigger(scheduled_for=datetime.utcnow(), reason="scheduled")
                await self._runner(trigger)
            except Exception:  # noqa: BLE001
                logger.exception("observer run failed")
            try:
                await asyncio.wait_for(self._manual.wait(), timeout=self._interval)
                self._manual.clear()
            except asyncio.TimeoutError:
                continue
