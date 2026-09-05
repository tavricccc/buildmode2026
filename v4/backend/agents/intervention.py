"""Intervention Agent (v3 02).

The Intervention agent only runs actions that the policy gateway
already approved. It must not enlarge scope (no extra chat IDs, no
template edits, no token reads).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterventionResult:
    action_id: str
    channel: str  # "dashboard" | "telegram" | "system_tts"
    status: str   # "completed" | "skipped" | "failed"
    detail: str = ""


class InterventionAgent:
    name = "intervention"

    def __init__(self, broadcaster=None, telegram=None) -> None:
        self._broadcaster = broadcaster
        self._telegram = telegram

    async def run(self, action_id: str, channel: str, payload: dict) -> InterventionResult:
        # Stub: in commit 2 this fans out to dashboard_alert / telegram_notify.
        if self._broadcaster is not None:
            try:
                await self._broadcaster.broadcast("action.triggered", {"action_id": action_id, "channel": channel})
            except Exception:  # noqa: BLE001
                pass
        return InterventionResult(action_id=action_id, channel=channel, status="completed", detail="stub")
