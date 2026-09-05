"""Model install state machine.

States: pending → downloading → verifying → probing → ready
                                                ↘ failed
                                                ↘ cancelled
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.enums import ModelProbeStatus


@dataclass(frozen=True)
class InstallContext:
    job_id: str
    progress: float  # 0.0..1.0
    probe_status: ModelProbeStatus
    cancelled: bool
    error: str | None = None


def install_transition(ctx: InstallContext) -> str:
    """Return the new install status string.

    Cancellation is terminal: nothing else happens after. Failure is
    also terminal but the previous active model remains untouched.
    """
    if ctx.cancelled:
        return "cancelled"
    if ctx.error:
        return "failed"
    if ctx.probe_status == ModelProbeStatus.failed:
        return "failed"
    if ctx.probe_status == ModelProbeStatus.ok and ctx.progress >= 1.0:
        return "ready"
    if ctx.progress >= 1.0 and ctx.probe_status == ModelProbeStatus.running:
        return "probing"
    if ctx.progress >= 0.95:
        return "verifying"
    if ctx.progress > 0.0:
        return "downloading"
    return "pending"
