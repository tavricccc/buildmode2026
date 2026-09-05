"""Periodic Long-term Observer runner.

The scheduler is deliberately small: one daemon thread, one non-overlapping run,
and a bounded interval. The Observer reads aggregate/repository views rather than
giving a model arbitrary SQL access.
"""

from __future__ import annotations

import threading
from typing import Any

from ..domain.timeutil import now_ms
from .daily import run_observer


class ObserverScheduler:
    def __init__(self, ctx: Any, interval_sec: int = 900) -> None:
        self.ctx = ctx
        self.interval_sec = max(60, int(interval_sec))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self.last_started_at_ms: int | None = None
        self.last_completed_at_ms: int | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def loop() -> None:
            # Record a baseline immediately, then continue at a fixed cadence.
            try:
                while not self._stop.is_set():
                    self.run_now()
                    self._stop.wait(self.interval_sec)
            finally:
                self.ctx.db.close()

        self._thread = threading.Thread(target=loop, name="observer-scheduler", daemon=True)
        self._thread.start()

    def run_now(self) -> dict[str, Any] | None:
        if not self._run_lock.acquire(blocking=False):
            return None
        self.last_started_at_ms = now_ms()
        try:
            result = run_observer(self.ctx)
            self.last_completed_at_ms = now_ms()
            self.last_error = None
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_error = self.ctx.secrets.redact(f"{type(exc).__name__}: {exc}")[:300]
            self.ctx.repos.log("error", "observer", "scheduled observer failed",
                               {"error": self.last_error})
            return None
        finally:
            self._run_lock.release()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def status(self) -> dict[str, Any]:
        running = self._thread is not None and self._thread.is_alive()
        next_at = ((self.last_started_at_ms or now_ms()) + self.interval_sec * 1000
                   if running else None)
        return {
            "running": running,
            "interval_sec": self.interval_sec,
            "last_started_at_ms": self.last_started_at_ms,
            "last_completed_at_ms": self.last_completed_at_ms,
            "next_run_at_ms": next_at,
            "last_error": self.last_error,
        }
