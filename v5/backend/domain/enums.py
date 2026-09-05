"""Enumerations shared by the three layers (v5 00, 02)."""

from __future__ import annotations

from enum import Enum


class Layer(str, Enum):
    """The three cascade layers. Used as a label in ``pipeline_runs``."""

    l1_person_gate = "l1_person_gate"
    l2_gemini = "l2_gemini"
    l3_minimax = "l3_minimax"


class L1Decision(str, Enum):
    """What the local person gate concluded about a window."""

    person_present = "person_present"
    no_person = "no_person"
    #: detector answered too long ago to trust — v5 01 requires fail-open.
    stale = "stale"
    #: detector crashed or was never configured — also fail-open.
    unavailable = "unavailable"

    def permits_skip(self) -> bool:
        """Only a *fresh, healthy* no-person answer may suppress L2.

        v5 00: "L1 unavailable/stale 時，系統 fail-open，不把該狀態當成空房."
        """
        return self is L1Decision.no_person


class L2Outcome(str, Enum):
    """Why L2 ran, or why it did not (v5 02 ``pipeline_runs``)."""

    called = "called"
    skipped_l1 = "skipped_l1"
    heartbeat = "heartbeat"
    forced_high_risk = "forced_high_risk"
    failed = "failed"

    def is_call(self) -> bool:
        return self in {L2Outcome.called, L2Outcome.heartbeat, L2Outcome.forced_high_risk}


class L3Outcome(str, Enum):
    """Why L3 ran, or why it did not (v5 02 ``pipeline_runs``)."""

    not_required = "not_required"
    called = "called"
    #: v5 01: text-only is a *degraded* mode, allowed only when the clip is
    #: missing, and it must be visible in SQLite and the UI.
    degraded_text_only = "degraded_text_only"
    failed = "failed"


class EscalationTrigger(str, Enum):
    """Who asked for L3 (v5 01 §L3)."""

    gemini_requested = "gemini_requested"
    high_risk_state = "high_risk_state"
    policy_second_opinion = "policy_second_opinion"
    manual = "manual"


class EventType(str, Enum):
    fall = "fall"
    hydration = "hydration"


class EventStatus(str, Enum):
    """Union of both state machines (v5 01 §Event state machine)."""

    idle = "idle"
    suspect = "suspect"
    confirmed = "confirmed"
    # fall only
    recovering = "recovering"
    resolved = "resolved"
    # hydration only
    active = "active"
    completed = "completed"
    # shared terminal
    dismissed = "dismissed"

    def is_high_risk(self) -> bool:
        """High-risk states bypass L1 entirely (v5 00 item 8)."""
        return self in {EventStatus.suspect, EventStatus.confirmed}


class Health(str, Enum):
    ok = "ok"
    degraded = "degraded"
    unavailable = "unavailable"
    unknown = "unknown"


class ActionKind(str, Enum):
    notify_telegram = "notify_telegram"
    dashboard_alert = "dashboard_alert"
    log_only = "log_only"
