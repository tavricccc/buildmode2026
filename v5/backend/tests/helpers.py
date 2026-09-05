"""Shared fixtures: a fully wired cascade with no network and no keys."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..cascade import Cascade
from ..domain.observation import GeminiObservation
from ..domain.policy import (
    CadencePolicy,
    CarePolicy,
    EscalationPolicy,
    FallPolicy,
    HydrationPolicy,
    L1Policy,
    NotificationPolicy,
)
from ..domain.timeutil import now_ms
from ..l1.detector import StubPersonDetector
from ..l1.gate import PersonGate
from ..l2.service import L2Service
from ..l2.stub import StubL2Backend
from ..l3.service import L3Service
from ..l3.stub import StubL3Backend
from ..media.frames import FrameWindow
from ..media.replay_source import ScriptedSource
from ..store import Database, Repositories, migrate


def test_policy(**overrides: Any) -> CarePolicy:
    """Fast cadences so a scenario runs in milliseconds, same rules."""
    base = {
        "l1": L1Policy(detector_id="stub", frames_to_enter=2, frames_to_exit=4, stale_after_ms=6000),
        "cadence": CadencePolicy(
            l2_interval_sec=0.0, heartbeat_interval_sec=6.0, high_risk_interval_sec=0.0,
            window_seconds=4.0, clip_fps=4.0,
        ),
        "fall": FallPolicy(),
        "hydration": HydrationPolicy(),
        "escalation": EscalationPolicy(min_seconds_between=0, max_per_day=1000),
        "notification": NotificationPolicy(telegram_enabled=True),
    }
    base.update(overrides)
    return CarePolicy(**base)


class Harness:
    """A cascade driven frame by frame, with no threads, for determinism."""

    def __init__(self, policy: CarePolicy | None = None, *,
                 l2_backend: Any = None, l3_backend: Any = None,
                 telegram_configured: bool = True) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="care-v5-test-"))
        self.db = Database(self.tmp / "care.sqlite3")
        migrate(self.db)
        self.repos = Repositories(self.db)
        self.policy = policy or test_policy()
        self.detector = StubPersonDetector()
        self.gate = PersonGate(self.policy.l1)
        self.l2_backend = l2_backend or StubL2Backend(latency_ms=0)
        self.l3_backend = l3_backend or StubL3Backend(latency_ms=0)
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.cascade = Cascade(
            policy=self.policy,
            repos=self.repos,
            detector=self.detector,
            gate=self.gate,
            l2_service=L2Service(self.l2_backend, provider="stub"),
            l3_service=L3Service(self.l3_backend, provider="stub") if self.l3_backend else None,
            frames=FrameWindow(capacity=600),
            clips_dir=self.tmp / "clips",
            broadcast=lambda topic, payload: self.published.append((topic, payload)),
            telegram_configured=telegram_configured,
        )

    def close(self) -> None:
        self.cascade.stop()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- driving ---------------------------------------------------------

    def play(self, scenario: dict[str, Any], *, sample_every: int = 2,
             window_every: int = 8, fps: float = 4.0) -> list[Any]:
        """Feed a scripted scenario through the cascade synchronously.

        L1 samples every ``sample_every`` frames and a window is evaluated
        every ``window_every`` frames, mirroring the real scheduler's rates
        without depending on wall-clock timing.
        """
        # Stamp the scenario so it *ends* at wall-clock now. The detector
        # stamps its readings with the real clock, so a fixture timeline
        # running into the future would make every reading look stale and
        # turn the whole run into a fail-open.
        duration_ms = int(sum(float(seg.get("duration_sec", 1.0))
                              for seg in scenario.get("segments", [])) * 1000)
        frames = ScriptedSource(scenario, fps=fps, realtime=False).frames(
            base_ms=now_ms() - duration_ms
        )
        runs: list[Any] = []
        for index, frame in enumerate(frames, start=1):
            self.cascade.ingest(frame)
            if index % sample_every == 0:
                self.cascade._sample_once()
            if index % window_every == 0:
                runs.append(self.step(frame.captured_at_ms))
        return [r for r in runs if r is not None]

    def step(self, at_ms: int) -> Any:
        """Evaluate one window, draining any escalation synchronously."""
        decision = self.cascade.decide_window(at_ms)
        if not decision.should_call_l2:
            self.cascade._record_skip(at_ms, decision)
            return self.repos.list_runs(limit=1)[0]
        run = self.cascade.run_window(decision, at_ms)
        job = self.cascade.l3_queue.take(timeout=0.01)
        if job is not None:
            try:
                self.cascade._run_escalation(*job.payload)
            finally:
                self.cascade.l3_queue.finish()
        return run

    # -- assertions helpers ----------------------------------------------

    def outcomes(self) -> list[str]:
        return [r["l2_outcome"] for r in reversed(self.repos.list_runs(limit=500))]

    def events(self) -> list[tuple[str, str]]:
        return [(e["event_type"], e["status"]) for e in self.repos.list_events(limit=50)]

    def actions(self) -> list[tuple[str, str, str]]:
        return [(a["kind"], a["rule"], a["suppressed_reason"]) for a in self.repos.list_actions()]


def observation(**overrides: Any) -> GeminiObservation:
    payload: dict[str, Any] = {
        "person_visible": True,
        "confidence": 0.9,
        "fall": {"posture": "standing", "confidence": 0.9},
        "hydration": {"container": "none", "confidence": 0.9},
    }
    payload.update(overrides)
    return GeminiObservation.parse(payload)


FALL_SCENARIO = {
    "name": "fall",
    "segments": [
        {"duration_sec": 6, "person": False},
        {"duration_sec": 6, "person": True, "posture": "standing"},
        {"duration_sec": 16, "person": True, "posture": "lying",
         "near_floor": True, "motionless": True},
        {"duration_sec": 8, "person": True, "posture": "standing"},
    ],
}

EMPTY_SCENARIO = {
    "name": "empty",
    "segments": [{"duration_sec": 40, "person": False}],
}

DETECTOR_FAULT_SCENARIO = {
    "name": "l1-fault",
    "segments": [
        {"duration_sec": 6, "person": True, "posture": "standing"},
        {"duration_sec": 6, "person": False},
        {"duration_sec": 16, "person": True, "posture": "lying", "near_floor": True,
         "motionless": True, "detector_fault": True},
    ],
}

HYDRATION_SCENARIO = {
    "name": "hydration",
    "segments": [
        {"duration_sec": 6, "person": True, "posture": "sitting"},
        {"duration_sec": 12, "person": True, "posture": "sitting", "drinking": True},
        {"duration_sec": 6, "person": True, "posture": "sitting"},
        {"duration_sec": 8, "person": True, "posture": "sitting", "drinking": True},
        {"duration_sec": 6, "person": True, "posture": "sitting"},
    ],
}
