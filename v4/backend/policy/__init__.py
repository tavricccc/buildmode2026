"""Deterministic Policy Gateway.

The gateway is a small, table-driven policy engine. It does not call
any model. It only reads already-validated fields and the active
``PolicyBundle``. Higher-risk patches (lower fall confidence, change
of notification recipient, etc.) are returned with
``requires_confirmation=True`` so the API layer can demand a second
step before applying.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.policy import PolicyBundle


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
    restart_required: bool = False


class DeterministicPolicyGateway:
    def __init__(self) -> None:
        # Keys that always require a second confirmation.
        self._confirmation_keys = {
            "fall.min_confidence",
            "fall.no_recovery_alert_sec",
            "notification.allowed_chat_ids",
            "notification.bot_token",
        }
        # Keys that trigger a service restart.
        self._restart_keys = {
            "audio.sample_rate",
            "audio.channels",
            "vision_loop.fps",
            "vision_loop.max_frames",
        }

    def evaluate(self, proposed: dict[str, Any], current: PolicyBundle) -> PolicyDecision:
        changed = list(proposed.keys())
        needs_confirm = any(_has_key(c, self._confirmation_keys) for c in changed)
        needs_restart = any(_has_key(c, self._restart_keys) for c in changed)
        return PolicyDecision(
            allowed=True,
            requires_confirmation=needs_confirm,
            reason="high_risk_change" if needs_confirm else "",
            restart_required=needs_restart,
        )


def _has_key(changed: str, keys: set[str]) -> bool:
    return any(changed == k or changed.startswith(k + ".") for k in keys)
