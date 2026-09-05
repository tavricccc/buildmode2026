"""Notification state machine (v4 12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.enums import NotificationStatus


@dataclass(frozen=True)
class NotificationContext:
    current: NotificationStatus
    delivered: bool = False
    callback_token_valid: bool = False
    callback_acknowledged: bool = False
    callback_false_alarm: bool = False
    send_attempt_failed: bool = False


def notification_transition(ctx: NotificationContext) -> NotificationStatus:
    if ctx.send_attempt_failed:
        return NotificationStatus.failed
    if ctx.current == NotificationStatus.queued:
        if ctx.delivered:
            return NotificationStatus.delivered
        return NotificationStatus.queued
    if ctx.current == NotificationStatus.delivered:
        if not ctx.callback_token_valid:
            return NotificationStatus.delivered
        if ctx.callback_acknowledged:
            return NotificationStatus.acknowledged
        if ctx.callback_false_alarm:
            return NotificationStatus.false_alarm
        return NotificationStatus.delivered
    return ctx.current
