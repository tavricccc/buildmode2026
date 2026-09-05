"""Deterministic thresholds (v5 02 §Policy Gateway).

Every number a model could otherwise "decide" lives here, is versioned
with the config, and is editable only through Settings. A model may not
move any of them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any


def _env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    if maximum is not None:
        value = min(maximum, value)
    return max(minimum, value)


@dataclass(frozen=True)
class L1Policy:
    """Person-gate behaviour (v5 01 §L1)."""

    enabled: bool = True
    detector_id: str = "stub"
    confidence_threshold: float = 0.45
    sample_fps: float = 2.0
    #: hysteresis — how many consecutive readings flip the gate.
    frames_to_enter: int = 2
    frames_to_exit: int = 4
    #: a reading older than this is ``stale`` and therefore fail-open.
    stale_after_ms: int = 6_000


@dataclass(frozen=True)
class CadencePolicy:
    """How often each layer is allowed to run (v5 README §排程)."""

    #: normal L2 cadence while a person is present
    l2_interval_sec: float = 6.0
    #: sparse safety heartbeat while the room reads as empty
    heartbeat_interval_sec: float = 45.0
    #: follow-up cadence once an event is suspect/confirmed
    high_risk_interval_sec: float = 4.0
    window_seconds: float = 5.0
    clip_fps: float = 2.0
    #: Local vLLM observation fan-out. 12 is a ceiling, not a requirement.
    max_parallel_observations: int = _env_int("VLLM_MAX_CONCURRENCY", 12, maximum=12)
    #: Keep recent work for the idle drain; urgent items are selected first.
    observation_queue_capacity: int = _env_int("VLLM_MAX_PENDING_WINDOWS", 48)
    #: Original Longcare L0 change gate. It is an accelerator, never a
    #: safety veto for high-risk or heartbeat windows.
    change_gate_enabled: bool = True
    change_gate_threshold: float = 0.06
    change_gate_audio_delta_threshold: float = 0.06
    change_gate_min_changed_pairs: int = 2
    change_gate_strong_score_multiplier: float = 2.5


@dataclass(frozen=True)
class FallPolicy:
    min_confidence: float = 0.5
    #: consecutive corroborating observations required to confirm
    confirm_observations: int = 2
    #: seconds without recovery after ``confirmed`` before an alert is due
    no_recovery_alert_sec: int = 60
    recovery_confidence: float = 0.5


@dataclass(frozen=True)
class HydrationPolicy:
    min_confidence: float = 0.5
    confirm_observations: int = 2
    #: a session must be quiet this long before a new one may be counted
    session_cooldown_sec: int = 45
    container_volume_ml: float = 200.0
    daily_target_ml: float = 1500.0


@dataclass(frozen=True)
class EscalationPolicy:
    """When L3 may be spent (v5 01 §L3)."""

    enabled: bool = True
    #: honour Gemini's own ``escalation.required``
    honour_model_request: bool = True
    #: force an escalation when an event enters these states
    force_on_states: tuple[str, ...] = ("confirmed",)
    #: never escalate the same event more than this often
    min_seconds_between: int = 90
    #: hard daily ceiling so a stuck loop cannot drain the budget
    max_per_day: int = 200
    allow_text_only_fallback: bool = True


@dataclass(frozen=True)
class NotificationPolicy:
    telegram_enabled: bool = False
    #: Chat ids allowed to receive alerts and to answer them. A model can
    #: never add to this list; only Settings can (v5 02 §Telegram).
    telegram_chat_ids: tuple[str, ...] = ()
    #: only these deterministic conditions may notify
    notify_on_fall_confirmed: bool = True
    notify_on_no_recovery: bool = True
    notify_on_l3_high_risk: bool = False
    min_seconds_between: int = 300


@dataclass(frozen=True)
class CarePolicy:
    """The whole deterministic policy set, versioned as one unit."""

    version: str = "policy.v5.0"
    l1: L1Policy = L1Policy()
    cadence: CadencePolicy = CadencePolicy()
    fall: FallPolicy = FallPolicy()
    hydration: HydrationPolicy = HydrationPolicy()
    escalation: EscalationPolicy = EscalationPolicy()
    notification: NotificationPolicy = NotificationPolicy()

    def to_dict(self) -> dict[str, Any]:
        def unwrap(value: Any) -> Any:
            if hasattr(value, "__dataclass_fields__"):
                return {k: unwrap(getattr(value, k)) for k in value.__dataclass_fields__}
            if isinstance(value, tuple):
                return list(value)
            return value

        return unwrap(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CarePolicy":
        """Rebuild from a stored config version, ignoring unknown keys."""
        groups = {
            "l1": L1Policy,
            "cadence": CadencePolicy,
            "fall": FallPolicy,
            "hydration": HydrationPolicy,
            "escalation": EscalationPolicy,
            "notification": NotificationPolicy,
        }
        kwargs: dict[str, Any] = {"version": payload.get("version", cls.version)}
        for name, klass in groups.items():
            raw = payload.get(name) or {}
            allowed = {k: v for k, v in raw.items() if k in klass.__dataclass_fields__}
            if name == "escalation" and "force_on_states" in allowed:
                allowed["force_on_states"] = tuple(allowed["force_on_states"])
            if name == "notification" and "telegram_chat_ids" in allowed:
                allowed["telegram_chat_ids"] = tuple(str(c) for c in allowed["telegram_chat_ids"])
            kwargs[name] = klass(**allowed)
        return cls(**kwargs)

    def with_version(self, version: str) -> "CarePolicy":
        return replace(self, version=version)


DEFAULT_POLICY = CarePolicy()
