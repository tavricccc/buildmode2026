"""Bounded per-layer work queue (v5 01 §Failure behavior).

"L2/L3 queue 預設各 1 running + 1 pending；高風險 pending 受保護."

Depth one is the whole idea. A camera produces windows faster than a
cloud model can answer them, so an unbounded queue does not buy
throughput — it buys latency, and stale answers about a scene that has
already changed. Keeping the newest pending window and dropping the one
it replaced means the model always answers about *now*.

The one exception is the protection rule: a high-risk pending job (a
fall being tracked) is never displaced by a routine one. Dropping a
routine window costs nothing; dropping the follow-up on someone who is
on the floor costs the thing this system exists to catch.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class QueuedJob:
    payload: Any
    high_risk: bool = False
    enqueued_at_ms: int = 0
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class LayerQueue:
    """One running slot, one pending slot, with high-risk protection."""

    def __init__(self, name: str, on_drop: Callable[[QueuedJob, str], None] | None = None) -> None:
        self.name = name
        self._pending: QueuedJob | None = None
        self._running: QueuedJob | None = None
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._on_drop = on_drop
        self.accepted = 0
        self.dropped = 0
        self.rejected = 0
        self.completed = 0

    def offer(self, job: QueuedJob) -> tuple[bool, str]:
        """Try to enqueue. Returns ``(accepted, reason)``."""
        with self._not_empty:
            existing = self._pending
            if existing is not None:
                if existing.high_risk and not job.high_risk:
                    # Protected: a routine window may not evict a fall follow-up.
                    self.rejected += 1
                    return False, f"{self.name}_busy_high_risk_pending"
                self._pending = job
                self.dropped += 1
                self.accepted += 1
                self._notify_drop(existing, "superseded_by_newer_window")
                self._not_empty.notify()
                return True, "replaced_pending"
            self._pending = job
            self.accepted += 1
            self._not_empty.notify()
            return True, "queued"

    def take(self, timeout: float | None = None) -> QueuedJob | None:
        """Block until a pending job exists, then move it to the running slot."""
        with self._not_empty:
            if self._pending is None:
                self._not_empty.wait(timeout)
            job, self._pending = self._pending, None
            self._running = job
            return job

    def finish(self) -> None:
        with self._lock:
            if self._running is not None:
                self.completed += 1
            self._running = None

    def wake(self) -> None:
        """Unblock a waiting :meth:`take` so a worker can observe shutdown."""
        with self._not_empty:
            self._not_empty.notify_all()

    def _notify_drop(self, job: QueuedJob, reason: str) -> None:
        if self._on_drop is not None:
            try:
                self._on_drop(job, reason)
            except Exception:  # noqa: BLE001 - a drop hook must never break the queue
                pass

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "running": self._running is not None,
                "running_label": self._running.label if self._running else None,
                "pending": self._pending is not None,
                "pending_high_risk": bool(self._pending and self._pending.high_risk),
                "accepted": self.accepted,
                "dropped": self.dropped,
                "rejected": self.rejected,
                "completed": self.completed,
            }
