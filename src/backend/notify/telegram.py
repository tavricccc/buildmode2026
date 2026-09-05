"""Telegram delivery and acknowledgement (docs/02_DATA_AND_POLICY.md §Telegram).

Four properties are load-bearing:

*The bot is unreachable from a model.* Nothing in this module is called
by L2 or L3. It is invoked only by the Cascade, and only for a
:class:`PolicyDecision` the deterministic gateway already authorised.

*The recipient comes from configuration.* ``telegram_chat_ids`` lives in
``NotificationPolicy``, and an inbound update from any other chat is
dropped without a reply. A model that somehow produced a chat id would
have nowhere to put it.

*Callback tokens are opaque and single-use.* The button payload is
random and carries no event id, so possession of a forwarded message
does not let anyone address an arbitrary event. The token is resolved
against ``notification_deliveries``, and a second use finds a row that
is no longer pending.

*Delivery is recorded either way.* pending -> sent -> acknowledged /
false_alarm, or -> failed with the provider's error. A notification that
silently failed to send is indistinguishable from one nobody read, and
this system cannot afford that ambiguity.
"""

from __future__ import annotations

import json
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://api.telegram.org"
USER_AGENT = "care-agent/1.0"


class TelegramError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_ids: tuple[str, ...],
        repos: Any,
        redact: Any = None,
        timeout_sec: float = 15.0,
    ) -> None:
        self.token = token
        self.chat_ids = tuple(str(c) for c in chat_ids)
        self.repos = repos
        self._redact = redact or (lambda text: text)
        self.timeout_sec = timeout_sec
        self._offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_ids)

    # -- transport -------------------------------------------------------

    def _call(self, method: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{API_BASE}/bot{self.token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        request.add_header("Content-Type", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_sec) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TelegramError(f"http_{exc.code}", self._redact(exc.read().decode("utf-8", "replace"))[:300]) from None
        except urllib.error.URLError as exc:
            raise TelegramError("network_error", str(exc.reason)) from None
        except TimeoutError:
            raise TelegramError("timeout", f"no response within {timeout or self.timeout_sec}s") from None
        if not body.get("ok"):
            raise TelegramError("api_error", str(body.get("description", body))[:300])
        return body.get("result", {})

    # -- sending ---------------------------------------------------------

    def dispatch(self, decision: Any, event: dict[str, Any] | None) -> list[str]:
        """Send one authorised decision to every allow-listed chat."""
        if not self.configured:
            return []

        delivery_ids: list[str] = []
        for chat_id in self.chat_ids:
            token = secrets.token_urlsafe(24)
            delivery_id = self.repos.save_delivery(decision.action_id, chat_id, token)
            delivery_ids.append(delivery_id)
            try:
                result = self._call("sendMessage", {
                    "chat_id": chat_id,
                    "text": _compose(decision, event),
                    "parse_mode": "HTML",
                    "reply_markup": {"inline_keyboard": [[
                        {"text": "✅ On my way", "callback_data": f"ack:{token}"},
                        {"text": "🚫 False alarm", "callback_data": f"nak:{token}"},
                    ]]},
                })
                self.repos.update_delivery(delivery_id, "sent",
                                           provider_msg_id=str(result.get("message_id", "")))
            except TelegramError as exc:
                self.repos.update_delivery(delivery_id, "failed", error=f"{exc.code}: {exc.message}")
                self.repos.log("error", "telegram", f"send failed: {exc.code}")
        return delivery_ids

    # -- receiving -------------------------------------------------------

    def start_polling(self, poll_sec: float = 25.0) -> None:
        if self._thread is not None or not self.configured:
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.is_set():
                try:
                    self.poll_once(poll_sec)
                except TelegramError as exc:
                    self.repos.log("warn", "telegram", f"poll failed: {exc.code}")
                    self._stop.wait(5)

        self._thread = threading.Thread(target=run, name="telegram-poll", daemon=True)
        self._thread.start()

    def stop_polling(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def poll_once(self, poll_sec: float = 25.0) -> int:
        updates = self._call(
            "getUpdates",
            {"offset": self._offset, "timeout": int(poll_sec), "allowed_updates": ["callback_query"]},
            timeout=poll_sec + 10,
        )
        handled = 0
        for update in updates if isinstance(updates, list) else []:
            self._offset = max(self._offset, int(update.get("update_id", 0)) + 1)
            if self.handle_callback(update.get("callback_query") or {}):
                handled += 1
        return handled

    def handle_callback(self, callback: dict[str, Any]) -> bool:
        """Resolve one button press. Returns whether it changed anything."""
        data = str(callback.get("data", ""))
        chat_id = str(((callback.get("message") or {}).get("chat") or {}).get("id", ""))
        callback_id = callback.get("id")

        # An update from a chat we did not configure is dropped in silence:
        # answering would confirm that this bot serves this deployment.
        if chat_id not in self.chat_ids:
            self.repos.log("warn", "telegram", "callback from a chat outside the allowlist")
            return False

        action, _, token = data.partition(":")
        if action not in {"ack", "nak"} or not token:
            return False

        delivery = self.repos.delivery_by_token(token)
        if delivery is None:
            self._answer(callback_id, "This alert is no longer active.")
            return False
        if delivery["status"] not in {"sent", "pending"}:
            # Single-use: a replayed or forwarded button finds a resolved row.
            self._answer(callback_id, f"Already recorded as {delivery['status']}.")
            return False

        status = "acknowledged" if action == "ack" else "false_alarm"
        self.repos.update_delivery(delivery["delivery_id"], status)
        self._answer(callback_id, "Thank you — recorded."
                     if status == "acknowledged" else "Recorded as a false alarm.")
        self.repos.log("info", "telegram", f"delivery {status}",
                       {"delivery_id": delivery["delivery_id"]})
        return True

    def _answer(self, callback_id: Any, text: str) -> None:
        if not callback_id:
            return
        try:
            self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
        except TelegramError:
            pass  # the acknowledgement is already recorded; the toast is cosmetic

    def probe(self) -> dict[str, Any]:
        """Auth check for Setup (docs/04_SETUP_DEPLOY_VERIFY.md §Capability probes)."""
        try:
            me = self._call("getMe", {})
        except TelegramError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}
        return {"ok": True, "bot": me.get("username"), "chats": len(self.chat_ids)}


def _compose(decision: Any, event: dict[str, Any] | None) -> str:
    lines = [
        f"<b>{'🚨' if decision.severity in {'critical', 'error'} else '⚠️'} "
        f"{decision.rule.replace('_', ' ').title()}</b>",
        decision.reason,
    ]
    if event:
        lines.append(f"\nEvent: <code>{event.get('event_type')}</code> · "
                     f"status <code>{event.get('status')}</code>")
    lines.append("\nReply with a button so the system knows this was seen.")
    return "\n".join(lines)
