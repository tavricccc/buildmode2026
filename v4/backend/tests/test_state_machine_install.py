"""Model install state machine tests."""

from __future__ import annotations

from v4.backend.domain.enums import ModelProbeStatus
from v4.backend.state_machines.model_install import InstallContext, install_transition


def test_pending() -> None:
    out = install_transition(InstallContext(job_id="j", progress=0.0, probe_status=ModelProbeStatus.pending, cancelled=False))
    assert out == "pending"


def test_downloading() -> None:
    out = install_transition(InstallContext(job_id="j", progress=0.5, probe_status=ModelProbeStatus.pending, cancelled=False))
    assert out == "downloading"


def test_probing() -> None:
    out = install_transition(InstallContext(job_id="j", progress=1.0, probe_status=ModelProbeStatus.running, cancelled=False))
    assert out == "probing"


def test_ready() -> None:
    out = install_transition(InstallContext(job_id="j", progress=1.0, probe_status=ModelProbeStatus.ok, cancelled=False))
    assert out == "ready"


def test_cancelled_terminal() -> None:
    out = install_transition(InstallContext(job_id="j", progress=0.5, probe_status=ModelProbeStatus.running, cancelled=True))
    assert out == "cancelled"


def test_failed_terminal() -> None:
    out = install_transition(InstallContext(job_id="j", progress=0.5, probe_status=ModelProbeStatus.failed, cancelled=False, error="boom"))
    assert out == "failed"
