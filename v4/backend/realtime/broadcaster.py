"""In-process WebSocket broadcaster.

Backed by an asyncio queue per subscriber. Tests can call
``broadcast`` directly; the API layer wires actual WebSocket
connections via ``attach_websocket``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from .messages import WSMessage
from ..domain.ids import new_id
from ..domain.time import isoformat, utc_now


logger = logging.getLogger(__name__)


class RealtimeBroadcaster:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[WSMessage]] = set()
        self._lock = asyncio.Lock()

    async def broadcast(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        msg = WSMessage(
            message_id=new_id("msg"),
            type=type_,  # type: ignore[arg-type]
            occurred_at=isoformat(utc_now()),
            payload=payload or {},
        )
        async with self._lock:
            queues = list(self._subscribers)
        dead: list[asyncio.Queue[WSMessage]] = []
        for q in queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Drop and disconnect; the next resync will rebuild the client view.
                dead.append(q)
        if dead:
            async with self._lock:
                for q in dead:
                    self._subscribers.discard(q)

    async def subscribe(self) -> AsyncIterator[WSMessage]:
        q: asyncio.Queue[WSMessage] = asyncio.Queue(maxsize=512)
        async with self._lock:
            self._subscribers.add(q)
        try:
            while True:
                msg = await q.get()
                yield msg
        finally:
            async with self._lock:
                self._subscribers.discard(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)
