"""The one place an action can be authorised (v5 02 §Policy Gateway).

The gateway calls no model, reads no free text, and takes no argument
that a model produced without validation. It sees only fields that
already passed a contract, plus the operator's configuration.

What a model may do: propose an interpretation, express uncertainty,
argue for a risk level, recommend an action.

What no model may do: move a threshold, name a recipient, choose a
channel, or cause a message to be sent. Those come from
:class:`NotificationPolicy` and nowhere else. That asymmetry is why L3's
``recommendation`` field arrives here as *evidence* and is weighed
against ``notify_on_l3_high_risk`` rather than obeyed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import ActionKind, EventStatus, EventType
from ..domain.ids import new_id
from ..domain.l3_contract import DeeperAnalysis
from ..domain.policy import NotificationPolicy


@dataclass
class PolicyInput:
    """Everything the gateway is allowed to look at."""

    event_type: EventType
    event_status: EventStatus
    event_id: str
    #: set by the state machine, never by a model
    alert_due: bool = False
    alert_reason: str = ""
    #: validated L3 output, advisory only
    analysis: DeeperAnalysis | None = None
    #: wall clock of the last delivered notification for this subject
    last_notified_at_ms: int | None = None
    now_ms: int = 0
    telegram_configured: bool = False


@dataclass
class PolicyDecision:
    action_id: str = field(default_factory=lambda: new_id("act"))
    kind: ActionKind = ActionKind.log_only
    reason: str = ""
    #: which rule authorised this, for the audit trail
    rule: str = ""
    event_id: str = ""
    severity: str = "info"
    suppressed: bool = False
    suppressed_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: (v.value if hasattr(v, "value") else v) for k, v in
                ((f, getattr(self, f)) for f in self.__dataclass_fields__)}


class PolicyGateway:
    def __init__(self, policy: NotificationPolicy) -> None:
        self.policy = policy

    def decide(self, request: PolicyInput) -> list[PolicyDecision]:
        decisions: list[PolicyDecision] = []

        # -- rule 1: a deterministic confirmation notifies ----------------
        if request.alert_due and request.event_type is EventType.fall:
            if request.alert_reason == "fall_confirmed" and self.policy.notify_on_fall_confirmed:
                decisions.append(
                    self._notify(request, "fall_confirmed",
                                 "Fall confirmed by two corroborating observations", "critical")
                )
            elif request.alert_reason == "no_recovery" and self.policy.notify_on_no_recovery:
                decisions.append(
                    self._notify(request, "no_recovery",
                                 "Confirmed fall with no recovery within the alert window", "critical")
                )
            else:
                decisions.append(
                    PolicyDecision(
                        kind=ActionKind.dashboard_alert,
                        reason=f"alert '{request.alert_reason}' is not enabled for notification",
                        rule="alert_not_enabled",
                        event_id=request.event_id,
                        severity="warning",
                    )
                )

        # -- rule 2: L3 risk is advisory and separately gated -------------
        analysis = request.analysis
        if analysis is not None and analysis.escalates_risk():
            if self.policy.notify_on_l3_high_risk:
                decisions.append(
                    self._notify(request, "l3_high_risk",
                                 f"Deep analysis rated risk {analysis.risk_level}", "warning")
                )
            else:
                # The model wanted a caregiver contacted; the operator has
                # not authorised model-initiated notification. It surfaces
                # on the Dashboard instead of being silently discarded.
                decisions.append(
                    PolicyDecision(
                        kind=ActionKind.dashboard_alert,
                        reason=f"L3 rated risk {analysis.risk_level} "
                               f"and recommended {analysis.recommendation}",
                        rule="l3_advisory_not_authorised",
                        event_id=request.event_id,
                        severity="warning",
                    )
                )

        if not decisions:
            decisions.append(
                PolicyDecision(
                    kind=ActionKind.log_only,
                    reason="no rule matched",
                    rule="default",
                    event_id=request.event_id,
                )
            )
        return decisions

    # -- helpers ---------------------------------------------------------

    def _notify(self, request: PolicyInput, rule: str, reason: str, severity: str) -> PolicyDecision:
        decision = PolicyDecision(
            kind=ActionKind.notify_telegram,
            reason=reason,
            rule=rule,
            event_id=request.event_id,
            severity=severity,
        )
        if not self.policy.telegram_enabled or not request.telegram_configured:
            decision.kind = ActionKind.dashboard_alert
            decision.suppressed = True
            decision.suppressed_reason = "telegram_not_configured"
            return decision

        if request.last_notified_at_ms is not None:
            gap_sec = (request.now_ms - request.last_notified_at_ms) / 1000.0
            if gap_sec < self.policy.min_seconds_between:
                decision.kind = ActionKind.dashboard_alert
                decision.suppressed = True
                decision.suppressed_reason = (
                    f"rate_limited: {gap_sec:.0f}s < {self.policy.min_seconds_between}s"
                )
        return decision
