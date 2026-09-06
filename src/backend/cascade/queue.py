"""Bounded per-layer work queue (docs/01_PIPELINE.md §Failure behavior).

"L2/L3 queue 預設各 1 running + 1 pending；高風險 pending 受保護."

Depth one is still the default, and it is the whole idea for a metered
slot. A camera produces windows faster than a cloud model can answer
them, so an unbounded queue does not buy throughput — it buys latency,
and stale answers about a scene that has already changed. Keeping the
newest pending window and dropping the one it replaced means the model
always answers about *now*.

The bounds are parameters rather than constants only because a local
vLLM changes the arithmetic: there a window costs GPU time already paid
for, so answering several at once is free where it would otherwise be
both slow and billed. The orchestrator raises the limits for that slot
alone; everything else gets the depth this docstring describes.

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
    """Bounded queue with high-risk priority and fair routine draining."""

    def __init__(self, name: str, on_drop: Callable[[QueuedJob, str], None] | None = None,
                 *, max_running: int = 1, max_pending: int = 1) -> None:
        if max_running <= 0 or max_pending <= 0:
            raise ValueError("queue limits must be positive")
        self.name = name
        self.max_running = max_running
        self.max_pending = max_pending
        self._pending: list[QueuedJob] = []
        self._running = 0
        self._running_labels: list[str] = []
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
            superseded = False
            if len(self._pending) >= self.max_pending:
                routine_indexes = [i for i, existing in enumerate(self._pending)
                                   if not existing.high_risk]
                if not job.high_risk and not routine_indexes:
                    # All pending work is urgent; routine work waits for a slot.
                    self.rejected += 1
                    return False, f"{self.name}_busy_high_risk_pending"
                # Prefer retaining urgent work. For routine overflow, evict
                # the oldest routine so newer evidence is not lost forever.
                index = routine_indexes[0] if routine_indexes else 0
                existing = self._pending.pop(index)
                self.dropped += 1
                superseded = True
                self._notify_drop(existing, "superseded_by_newer_window")
            self._pending.append(job)
            self.accepted += 1
            self._not_empty.notify()
            # Accepting into a free slot and accepting by evicting an older
            # window are different events for anything reading this reason,
            # so they keep the two names the depth-one queue used.
            return True, "replaced_pending" if superseded else "queued"

    def take(self, timeout: float | None = None) -> QueuedJob | None:
        """Block until a pending job exists, then move it to the running slot."""
        with self._not_empty:
            if not self._pending or self._running >= self.max_running:
                self._not_empty.wait(timeout)
            if not self._pending or self._running >= self.max_running:
                return None
            # Urgent work wins; within each class FIFO prevents starvation.
            index = next((i for i, item in enumerate(self._pending) if item.high_risk), 0)
            job = self._pending.pop(index)
            self._running += 1
            self._running_labels.append(job.label)
            return job

    def finish(self) -> None:
        with self._not_empty:
            if self._running > 0:
                self.completed += 1
                self._running -= 1
                if self._running_labels:
                    self._running_labels.pop(0)
            self._not_empty.notify_all()

    def wake(self) -> None:
        """Unblock a waiting :meth:`take` so a worker can observe shutdown."""
        with self._not_empty:
            self._not_empty.notify_all()

    def reset(self) -> None:
        """Drop pending work and reset counters after a history reset."""
        with self._not_empty:
            self._pending.clear()
            self._running = 0
            self._running_labels.clear()
            self.accepted = 0
            self.dropped = 0
            self.rejected = 0
            self.completed = 0
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
                "running": self._running > 0,
                "running_count": self._running,
                "max_running": self.max_running,
                "running_label": self._running_labels[0] if self._running_labels else None,
                "pending_count": len(self._pending),
                "max_pending": self.max_pending,
                "pending": bool(self._pending),
                "pending_high_risk": any(item.high_risk for item in self._pending),
                "accepted": self.accepted,
                "dropped": self.dropped,
                "rejected": self.rejected,
                "completed": self.completed,
            }
