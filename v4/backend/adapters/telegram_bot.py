"""Telegram Bot protocol (v4 12).

Long-polling with an opaque callback token, allowlisted chat IDs and
idempotency. The protocol lives in ``adapters/`` because Telegram is
a vendor SDK; the Intervention agent depends only on the protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    chat_id: str
    callback_token: str
    action_id: str


@runtime_checkable
class TelegramBot(Protocol):
    async def send_message(self, chat_id: str, text: str, **kwargs: Any) -> str: ...
    async def send_photo(self, chat_id: str, photo_ref: str, caption: str = "", **kwargs: Any) -> str: ...
    async def poll(self) -> list[TelegramUpdate]: ...
