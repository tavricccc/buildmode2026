"""WebSocket endpoint.

Mounts ``/ws`` on the FastAPI app. The endpoint is a thin wrapper
over ``RealtimeBroadcaster.subscribe``.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)


def attach_websocket(app: FastAPI) -> None:
    @app.websocket("/ws")
    async def _ws(ws: WebSocket) -> None:
        await ws.accept()
        broadcaster = app.state.broadcaster
        gen = broadcaster.subscribe()
        send_task = asyncio.create_task(_pump(ws, gen), name="ws-send")
        recv_task = asyncio.create_task(_receive(ws), name="ws-recv")
        try:
            done, pending = await asyncio.wait(
                {send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for t in pending:
                t.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            send_task.cancel()
            recv_task.cancel()
            try:
                await send_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            try:
                await recv_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


async def _pump(ws: WebSocket, gen) -> None:
    async for msg in gen:
        await ws.send_json(msg.model_dump(mode="json"))


async def _receive(ws: WebSocket) -> None:
    while True:
        # We accept (and discard) client pings so the socket stays alive.
        await ws.receive_text()
