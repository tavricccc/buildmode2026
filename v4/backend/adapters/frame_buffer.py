"""Bounded ring buffer.

Used by the Source / Vision Loop / Audio Pipeline to keep only the
most recent N items. Critical for memory bounds on a long-running
process: the v4 spec forbids accumulating backlogs.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Generic, Iterable, TypeVar

T = TypeVar("T")


class BoundedRingBuffer(Generic[T]):
    def __init__(self, max_items: int) -> None:
        if max_items <= 0:
            raise ValueError("max_items must be > 0")
        self._max = max_items
        self._buf: deque[T] = deque(maxlen=max_items)
        self._lock = threading.Lock()

    def push(self, item: T) -> None:
        with self._lock:
            self._buf.append(item)

    def extend(self, items: Iterable[T]) -> None:
        with self._lock:
            for it in items:
                self._buf.append(it)

    def snapshot(self) -> list[T]:
        with self._lock:
            return list(self._buf)

    def peek_latest(self) -> T | None:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def capacity(self) -> int:
        return self._max

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
