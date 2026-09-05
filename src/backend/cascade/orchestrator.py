"""The L1 -> L2 -> L3 -> Policy cascade (docs/01_PIPELINE.md, src/README.md §排程).

Threading model, and why it is shaped this way:

``_sample_loop``    runs the L1 detector at ``sample_fps`` and folds each
                    reading into the gate. Cheap, local, never blocks.
``_schedule_loop``  decides once per tick whether this window deserves an
                    L2 call, and offers it to the L2 queue.
``_l2_loop``        builds the clip, calls L2, drives the state machines,
                    persists, and hands any escalation to the L3 queue.
``_l3_loop``        calls L3 and re-runs the Policy Gateway with the deep
                    analysis in hand.

L3 gets its own thread for one reason, and it is a hard requirement
rather than tidiness: docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 9 says a MiniMax timeout must not stop
L1, L2, the state machines, SQLite or the Dashboard. If L3 ran inline in
the L2 worker, a 90-second MiniMax stall would silently stop every
observation of a person who is on the floor — precisely when
observations matter most.

The scheduling rules, in priority order:

1. A *fall* in ``suspect`` or ``confirmed`` forces an L2 call and ignores
   L1 entirely (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 8). Hydration deliberately does not: nobody is
   harmed by learning about a glass of water four seconds late.
2. A fresh, healthy ``no_person`` skips the normal call, but still gets a
   sparse safety heartbeat (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md items 3–4).
3. Anything else — present, stale, unavailable, degraded — calls L2. The
   fail-open direction is always "spend a call" (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 5).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..domain.enums import (
    ActionKind,
    EscalationTrigger,
    EventStatus,
    EventType,
    Health,
    L2Outcome,
    L3Outcome,
)
from ..domain.ids import dedup_key, new_id
from ..domain.l3_contract import EvidenceBundle, VideoClip
from ..domain.observation import GeminiObservation
from ..domain.pipeline_run import PipelineRun
from ..domain.policy import CarePolicy
from ..domain.timeutil import day_key, now_ms
from ..l1.gate import PersonGate
from ..media import ffmpeg
from ..media.frames import FramePacket, FrameWindow
from ..policy.gateway import PolicyDecision, PolicyGateway, PolicyInput
from ..state_machines import (
    FallContext,
    HydrationContext,
    fall_transition,
    hydration_transition,
)
from .queue import LayerQueue, QueuedJob
from .change_gate import detect_frame_change

#: How many observations of each type to keep for corroboration.
HISTORY_DEPTH = 8


@dataclass
class WindowDecision:
    outcome: L2Outcome
    reason: str
    high_risk: bool = False
    heartbeat: bool = False

    @property
    def should_call_l2(self) -> bool:
        return self.outcome.is_call()


@dataclass
class TrackedEvent:
    """In-memory mirror of one event type's state machine."""

    event_type: EventType
    status: EventStatus = EventStatus.idle
    event_id: str | None = None
    episode_started_ms: int | None = None
    confirmed_at_ms: int | None = None
    alert_sent: bool = False
    last_completed_ms: int | None = None
    history: list[GeminiObservation] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

    def push(self, observation: GeminiObservation) -> None:
        self.history.append(observation)
        del self.history[:-HISTORY_DEPTH]

    def is_high_risk(self) -> bool:
        return self.status.is_high_risk()


class Cascade:
    def __init__(
        self,
        *,
        policy: CarePolicy,
        repos: Any,
        detector: Any,
        gate: PersonGate,
        l2_service: Any,
        l3_service: Any | None,
        frames: FrameWindow,
        clips_dir: Path,
        subject_id: str = "subject-1",
        legacy_flow: Any = None,
        broadcast: Callable[[str, dict[str, Any]], None] | None = None,
        telegram_configured: bool = False,
        notifier: Any = None,
        runtime_mode: str = "production",
    ) -> None:
        self.policy = policy
        self.repos = repos
        self.detector = detector
        self.gate = gate
        self.l2 = l2_service
        self.l3 = l3_service
        self.frames = frames
        self.clips_dir = Path(clips_dir)
        self.subject_id = subject_id
        self.legacy_flow = legacy_flow
        self.broadcast = broadcast or (lambda topic, payload: None)
        self.telegram_configured = telegram_configured
        #: Set only when a bot token *and* an allow-listed chat exist. The
        #: Policy Gateway decides whether to notify; this only delivers.
        self.notifier = notifier
        self.runtime_mode = runtime_mode

        self.policy_gateway = PolicyGateway(policy.notification)
        # docs/01_PIPELINE.md §Failure behavior: "L2/L3 queue 預設各 1 running + 1 pending".
        # cadence.max_parallel_observations is documented as the *local vLLM*
        # fan-out and defaults to VLLM_MAX_CONCURRENCY — a window there costs
        # GPU time already paid for. Handing the same 12/48 to a metered slot
        # means twelve concurrent billed calls and a queue 48 windows deep,
        # which is exactly the staleness the depth-one design exists to stop:
        # the model would be answering about a scene that has already moved
        # on, and charging for it. So the fan-out applies only where it was
        # measured, and every other slot keeps the spec's depth.
        local_l2 = getattr(l2_service, "provider", "") == "local_vllm"
        self.l2_queue = LayerQueue(
            "l2", on_drop=self._on_drop,
            max_running=max(1, int(policy.cadence.max_parallel_observations)) if local_l2 else 1,
            max_pending=max(1, int(policy.cadence.observation_queue_capacity)) if local_l2 else 1,
        )
        self.l3_queue = LayerQueue("l3", on_drop=self._on_drop, max_running=1, max_pending=8)

        self.tracked: dict[EventType, TrackedEvent] = {
            EventType.fall: TrackedEvent(EventType.fall),
            EventType.hydration: TrackedEvent(EventType.hydration),
        }

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._state_lock = threading.Lock()
        self._last_l2_call_ms = 0
        self._last_heartbeat_ms = 0
        self._last_audio_level: float | None = None
        self._last_change_gate: dict[str, Any] | None = None
        self._last_escalation_ms: dict[str, int] = {}
        self._escalations_today = 0
        self._escalation_day = day_key()
        self._starved_since_ms = 0
        self._starved_logged = False
        self.windows_seen = 0

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        workers = [("l1-sampler", self._sample_loop), ("scheduler", self._schedule_loop)]
        workers.extend((f"l2-worker-{index + 1}", self._l2_loop)
                       for index in range(self.l2_queue.max_running))
        workers.append(("l3-worker", self._l3_loop))
        for name, target in workers:
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        self.l2_queue.wake()
        self.l3_queue.wake()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def ingest(self, packet: FramePacket) -> None:
        self.frames.ingest(packet)

    def reset_source_state(self) -> None:
        self._starved_since_ms = 0
        self._starved_logged = False
        self._last_change_gate = None
        self._last_audio_level = None

    def _step(self, run_id: str, step: str, status: str, summary: str, *,
              reason_codes: list[str] | None = None, input_data: dict[str, Any] | None = None,
              output_data: dict[str, Any] | None = None, event_id: str | None = None,
              step_id: str | None = None, started_at_ms: int | None = None) -> str:
        completed = now_ms() if status not in {"waiting", "running"} else None
        identity = self.repos.save_pipeline_step(
            run_id=run_id, step=step, status=status, summary=summary,
            reason_codes=reason_codes, input_data=input_data, output_data=output_data,
            mode="debug" if self.runtime_mode == "debug" else "live",
            event_id=event_id, step_id=step_id, started_at_ms=started_at_ms,
            completed_at_ms=completed,
        )
        self.broadcast("pipeline.step", {
            "step_id": identity, "run_id": run_id, "event_id": event_id,
            "step": step, "status": status, "summary": summary,
            "reason_codes": reason_codes or [], "started_at_ms": started_at_ms or now_ms(),
            "completed_at_ms": completed,
        })
        return identity

    # -- L1 sampling -----------------------------------------------------

    def _sample_loop(self) -> None:
        interval = 1.0 / max(0.5, self.policy.l1.sample_fps)
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(interval)

    def _sample_once(self) -> None:
        latest = self.frames.buffer.latest(1)
        if not latest:
            return
        try:
            reading = self.detector.detect(latest[-1])
        except Exception as exc:  # noqa: BLE001 - a detector crash is fail-open, not fatal
            self.repos.log("error", "l1", f"detector raised: {exc}")
            return
        self.gate.observe(reading)

    # -- scheduling ------------------------------------------------------

    def decide_window(self, at_ms: int | None = None) -> WindowDecision:
        """The routing rule, isolated so it can be unit-tested directly."""
        at = now_ms() if at_ms is None else at_ms
        decision = self.gate.decide(at)

        with self._state_lock:
            # docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 8 names fall.suspect and fall.confirmed specifically.
            # A hydration suspect is not a reason to burn the high-risk
            # cadence: nobody is harmed by finding out about a glass of
            # water four seconds late.
            high_risk = self.tracked[EventType.fall].is_high_risk()
            since_call = (at - self._last_l2_call_ms) / 1000.0 if self._last_l2_call_ms else 1e9
            since_beat = (at - self._last_heartbeat_ms) / 1000.0 if self._last_heartbeat_ms else 1e9

        cadence = self.policy.cadence
        packets = self.frames.window(int(cadence.window_seconds * 1000), at,
                                     max(4, int(cadence.window_seconds * cadence.clip_fps)))
        audio_pcm = getattr(packets[-1], "audio_pcm", None) if packets else None
        change = detect_frame_change(
            [packet.jpeg for packet in packets],
            threshold=cadence.change_gate_threshold,
            audio_pcm=audio_pcm,
            previous_audio_level=self._last_audio_level,
            audio_delta_threshold=cadence.change_gate_audio_delta_threshold,
            min_changed_pairs=cadence.change_gate_min_changed_pairs,
            strong_score_multiplier=cadence.change_gate_strong_score_multiplier,
        ) if cadence.change_gate_enabled else {"changed": True, "change_score": 1.0,
                                                "change_reasons": ["change_gate_disabled"]}
        self._last_audio_level = change.get("audio_level")
        self._last_change_gate = change

        if high_risk:
            if since_call < cadence.high_risk_interval_sec:
                return WindowDecision(L2Outcome.skipped_l1, "high_risk_cadence_not_due", True)
            return WindowDecision(
                L2Outcome.forced_high_risk,
                f"event tracked in high-risk state; L1 said {decision.decision}",
                high_risk=True,
            )

        if decision.permits_skip():
            if since_beat >= cadence.heartbeat_interval_sec:
                return WindowDecision(
                    L2Outcome.heartbeat,
                    f"safety heartbeat after {since_beat:.0f}s of no-person",
                    heartbeat=True,
                )
            return WindowDecision(L2Outcome.skipped_l1, decision.reason)

        if since_call < cadence.l2_interval_sec:
            return WindowDecision(L2Outcome.skipped_l1, "cadence_not_due")

        # Scripted replay fixtures intentionally use tiny identical JPEGs and
        # carry truth in annotations; keep their deterministic contract. The
        # real browser/RTSP inputs use the pixel/audio gate.
        is_annotated_replay = bool(packets and packets[-1].source_kind == "replay"
                                   and packets[-1].annotation is not None)
        if cadence.change_gate_enabled and not is_annotated_replay and not change.get("changed", True):
            return WindowDecision(L2Outcome.skipped_l1, "no_change_gate")

        return WindowDecision(L2Outcome.called, decision.reason)

    def _schedule_loop(self) -> None:
        # Tick faster than the shortest cadence so the decision is not itself
        # a source of latency.
        tick = max(0.25, min(self.policy.cadence.high_risk_interval_sec, 2.0) / 2.0)
        while not self._stop.is_set():
            self._stop.wait(tick)
            if self._stop.is_set():
                return
            at = now_ms()

            # No footage means there is no window to audit. Recording one
            # would inflate the L2 failure count with what is really a
            # source outage, so the source's own health reports that
            # instead (docs/03_API_AND_FRONTEND.md Dashboard shows the two separately).
            if not self.frames.window(int(self.policy.cadence.window_seconds * 1000), at, 1):
                self._note_starved(at)
                continue
            self._starved_since_ms = 0

            decision = self.decide_window(at)
            if not decision.should_call_l2:
                if decision.reason and not decision.reason.endswith("not_due"):
                    self._record_skip(at, decision)
                continue
            job = QueuedJob(
                payload=at,
                high_risk=decision.high_risk,
                enqueued_at_ms=at,
                label=decision.outcome.value,
                meta={"decision": decision},
            )
            accepted, reason = self.l2_queue.offer(job)
            if not accepted:
                self.repos.log("debug", "cascade", f"L2 job not queued: {reason}")

    def _note_starved(self, at: int) -> None:
        """Log once per outage that the buffer has no frames to look at."""
        if not self._starved_since_ms:
            self._starved_since_ms = at
            self._starved_logged = False
            return
        if not self._starved_logged and (at - self._starved_since_ms) >= 10_000:
            self._starved_logged = True
            self.repos.log(
                "warn", "cascade",
                "no frames in the ring buffer; the source has stopped producing",
                {"starved_ms": at - self._starved_since_ms},
            )

    def _record_skip(self, at: int, decision: WindowDecision) -> None:
        """Persist a skipped window so the audit trail has no holes."""
        gate = self.gate.decide(at)
        run = PipelineRun(
            subject_id=self.subject_id,
            window_started_at_ms=at,
            window_ended_at_ms=at,
            config_version=self.policy.version,
            l1_decision=gate.decision,
            l1_confidence=gate.confidence,
            l1_detector_id=gate.detector_id,
            l1_health=gate.health,
        )
        change = self._last_change_gate or {}
        run.change_detected = bool(change.get("changed", True))
        run.change_score = change.get("change_score")
        run.change_reasons = list(change.get("change_reasons") or [])
        run.mark_l2_skipped(decision.reason)
        run.mark_l3_not_required("l2_not_called")
        self.windows_seen += 1
        self.repos.save_run(run.close())
        self._step(run.run_id, "l1_gate", "succeeded", "L1 人體判讀完成",
                   reason_codes=[decision.reason],
                   output_data={"decision": gate.decision, "confidence": gate.confidence})
        self._step(run.run_id, "l2_observation", "skipped", "本視窗略過 L2",
                   reason_codes=[decision.reason])
        self._step(run.run_id, "persistence", "succeeded", "稽核紀錄已寫入 SQLite")
        self.repos.prune_pipeline_steps()
        self.broadcast("pipeline.run", run.to_dict())

    # -- L2 worker -------------------------------------------------------

    def _l2_loop(self) -> None:
        while not self._stop.is_set():
            job = self.l2_queue.take(timeout=1.0)
            if job is None:
                continue
            try:
                self.run_window(job.meta["decision"], job.payload)
            except Exception as exc:  # noqa: BLE001 - a bad window must not kill the loop
                self.repos.log("error", "cascade", f"window failed: {exc}")
            finally:
                self.l2_queue.finish()

    def run_window(self, decision: WindowDecision, at_ms: int) -> PipelineRun:
        """Process one window end to end through L2 and the state machines."""
        cadence = self.policy.cadence
        gate = self.gate.decide(at_ms)
        span_ms = int(cadence.window_seconds * 1000)
        max_frames = max(4, int(cadence.window_seconds * cadence.clip_fps))
        packets = self.frames.window(span_ms, at_ms, max_frames)
        change = self._last_change_gate or detect_frame_change(
            [packet.jpeg for packet in packets],
            threshold=cadence.change_gate_threshold,
            audio_pcm=getattr(packets[-1], "audio_pcm", None) if packets else None,
            previous_audio_level=self._last_audio_level,
            min_changed_pairs=cadence.change_gate_min_changed_pairs,
            strong_score_multiplier=cadence.change_gate_strong_score_multiplier,
        )

        run = PipelineRun(
            subject_id=self.subject_id,
            window_started_at_ms=packets[0].captured_at_ms if packets else at_ms,
            window_ended_at_ms=at_ms,
            config_version=self.policy.version,
            l1_decision=gate.decision,
            l1_confidence=gate.confidence,
            l1_detector_id=gate.detector_id,
            l1_health=gate.health,
            l2_outcome=decision.outcome.value,
            l2_reason=decision.reason,
            change_detected=bool(change.get("changed", True)),
            change_score=change.get("change_score"),
            change_reasons=list(change.get("change_reasons") or []),
        )
        self.windows_seen += 1
        self._step(run.run_id, "l1_gate", "succeeded", "L1 人體判讀完成",
                   reason_codes=[decision.reason],
                   output_data={"decision": gate.decision, "confidence": gate.confidence})
        l2_step = self._step(run.run_id, "l2_observation", "running", "正在執行情境觀察",
                             reason_codes=[decision.reason])

        with self._state_lock:
            self._last_l2_call_ms = at_ms
            if decision.heartbeat:
                self._last_heartbeat_ms = at_ms

        if not packets:
            run.l2_outcome = L2Outcome.failed.value
            run.l2_error = "no_frames_in_window"
            run.mark_l3_not_required("l2_failed")
            self._step(run.run_id, "l2_observation", "failed", "沒有可分析的影格",
                       reason_codes=["no_frames_in_window"], step_id=l2_step)
            self._persist(run)
            return run

        clip = self._encode_clip(packets, run)
        state_before = self._tracked_snapshot()

        result = self.l2.observe(
            clip,
            frames=[p.jpeg for p in packets],
            audio_pcm=getattr(packets[-1], "audio_pcm", None) if packets else None,
            event_state=state_before["fall"]["status"],
            transcript=self._transcript(run.window_started_at_ms),
            heartbeat=decision.heartbeat,
            purpose=decision.outcome.value,
            simulation_context=(packets[-1].annotation or {}).get("simulation_context")
            if packets and packets[-1].annotation else None,
        )
        run.l2_call_id = result.call.call_id
        run.l2_model = result.call.model
        run.l2_latency_ms = result.call.latency_ms
        run.l2_repaired = result.call.status == "repaired"
        result.call.evidence_id = run.evidence_id
        self.repos.save_model_call(result.call)

        if not result.ok:
            # docs/01_PIPELINE.md: an invalid observation does not update event state. A
            # window we could not read is not a window we can call safe.
            run.l2_outcome = L2Outcome.failed.value
            run.l2_error = f"{result.call.error_code}: {result.call.error_message}"
            run.mark_l3_not_required("no_valid_observation")
            self._step(run.run_id, "l2_observation", "failed", "L2 未產生有效觀察",
                       reason_codes=[result.call.error_code or "l2_failed"], step_id=l2_step,
                       output_data={"error": result.call.error_message})
            self._persist(run)
            return run

        observation = result.observation
        self._step(run.run_id, "l2_observation", "succeeded", observation.scene_summary,
                   reason_codes=observation.escalation.normalised_reasons(), step_id=l2_step,
                   output_data={"confidence": observation.confidence,
                                "escalation_required": observation.needs_escalation()})
        run.l2_escalation_required = observation.needs_escalation()
        run.l2_escalation_reasons = observation.escalation.normalised_reasons()

        # Insert the run row before the state machines run: actions and
        # event_runs both carry a foreign key to it, and an alert can be
        # raised inside _advance_state. save_run is INSERT OR REPLACE, so
        # the later _persist call updates this same row.
        self.repos.save_run(run)
        self.repos.save_observation(
            run.run_id, self.subject_id, at_ms,
            observation.scene_summary, observation.confidence,
            observation.to_dict(with_version=True),
        )

        state_step = self._step(run.run_id, "state_machine", "running", "正在更新事件狀態")
        events, decisions = self._advance_state(observation, run, at_ms)
        run.event_ids = [e for e in events]
        run.action_ids = [d.action_id for d in decisions]
        self._step(run.run_id, "state_machine", "succeeded",
                   "事件狀態已更新" if events else "沒有事件狀態變化",
                   event_id=events[0] if events else None, step_id=state_step,
                   output_data={"event_ids": events})

        # Preserve the original Main Agent boundary: it receives the bounded
        # current evidence plus typed state, runs independently, and remains
        # advisory. Routine low-signal windows stay on the cheaper L2 path.
        main_trigger = None
        if decision.high_risk or observation.needs_escalation():
            main_trigger = "high_risk_focus"
        elif observation.fall.indicates_fall(self.policy.fall.min_confidence):
            main_trigger = "multimodal_window"
        elif observation.hydration.indicates_drinking(self.policy.hydration.min_confidence):
            main_trigger = "multimodal_window"
        if main_trigger and self.legacy_flow is not None:
            self.legacy_flow.submit_main_agent(
                window={"window_id": run.run_id, "frame_count": len(packets),
                        "start_ms": run.window_started_at_ms, "end_ms": run.window_ended_at_ms},
                observation=observation.to_dict(with_version=True),
                persisted={"events": self.repos.list_events(limit=12)},
                frames=[p.jpeg for p in packets],
                trigger_type=main_trigger,
            )

        trigger, reasons = self._escalation_trigger(observation, at_ms)
        if trigger is None:
            run.mark_l3_not_required(reasons or "no_escalation_requested")
            self._step(run.run_id, "l3_review", "skipped", "本視窗不需要深度覆核",
                       reason_codes=[reasons or "no_escalation_requested"],
                       event_id=run.event_ids[0] if run.event_ids else None)
            self._persist(run)
            return run

        self._persist(run)
        self._offer_escalation(run, observation, trigger, reasons, packets, clip, at_ms)
        return run

    # -- clip ------------------------------------------------------------

    def _encode_clip(self, packets: list[FramePacket], run: PipelineRun) -> VideoClip | None:
        try:
            path = self.clips_dir / f"{run.run_id}.mp4"
            clip = ffmpeg.encode_clip(
                [p.jpeg for p in packets],
                path,
                self.policy.cadence.clip_fps,
                packets[0].captured_at_ms,
            )
        except Exception as exc:  # noqa: BLE001 - a clip failure degrades, never aborts
            self.repos.log("warn", "cascade", f"clip encode failed: {exc}")
            return None

        # Replay ground truth rides along so the stub backends stay honest.
        annotation = packets[-1].annotation
        if annotation is not None:
            clip.annotation = annotation

        run.clip_path = clip.path
        run.evidence_id = self.repos.save_evidence(
            subject_id=self.subject_id,
            kind="clip",
            uri=clip.path,
            mime_type=clip.mime_type,
            started_at_ms=clip.started_at_ms,
            duration_sec=clip.duration_sec,
            frame_count=clip.frame_count,
            size_bytes=clip.size_bytes,
            metadata={"source_kind": packets[-1].source_kind},
        )
        return clip

    def _transcript(self, since_ms: int) -> str | None:
        try:
            text = self.repos.recent_transcript(self.subject_id, since_ms - 30_000)
        except Exception:  # noqa: BLE001
            return None
        return text or None

    # -- state machines --------------------------------------------------

    def _advance_state(
        self, observation: GeminiObservation, run: PipelineRun, at_ms: int
    ) -> tuple[list[str], list[PolicyDecision]]:
        event_ids: list[str] = []
        decisions: list[PolicyDecision] = []

        with self._state_lock:
            fall = self.tracked[EventType.fall]
            hydration = self.tracked[EventType.hydration]
            fall.push(observation)
            hydration.push(observation)

            fall_next, fall_attrs = fall_transition(
                FallContext(
                    subject_id=self.subject_id,
                    history=tuple(fall.history),
                    policy=self.policy.fall,
                    now_ms=at_ms,
                    confirmed_at_ms=fall.confirmed_at_ms,
                    alert_sent=fall.alert_sent,
                ),
                fall.status,
            )
            hydration_next, hydration_attrs = hydration_transition(
                HydrationContext(
                    subject_id=self.subject_id,
                    history=tuple(hydration.history),
                    policy=self.policy.hydration,
                    now_ms=at_ms,
                    last_completed_at_ms=hydration.last_completed_ms,
                    started_at_ms=hydration.episode_started_ms,
                ),
                hydration.status,
            )

            fall_id = self._apply(fall, fall_next, fall_attrs, observation, at_ms)
            hydration_id = self._apply(hydration, hydration_next, hydration_attrs, observation, at_ms)

            if hydration_attrs.get("counted") and hydration_id:
                self.repos.save_hydration_session(
                    hydration_id, self.subject_id,
                    hydration.episode_started_ms or at_ms, at_ms,
                    float(hydration_attrs.get("estimated_ml", 0.0)),
                )
                hydration.last_completed_ms = at_ms
                hydration.episode_started_ms = None

            alert_due = bool(fall_attrs.get("alert_due"))
            alert_reason = str(fall_attrs.get("alert_reason", ""))
            if alert_due:
                fall.alert_sent = True

        for event_id in (fall_id, hydration_id):
            if event_id:
                event_ids.append(event_id)

        if alert_due and fall_id:
            decisions = self._apply_policy(
                PolicyInput(
                    event_type=EventType.fall,
                    event_status=self.tracked[EventType.fall].status,
                    event_id=fall_id,
                    alert_due=True,
                    alert_reason=alert_reason,
                    last_notified_at_ms=self.repos.last_notification_ms(self.subject_id),
                    now_ms=at_ms,
                    telegram_configured=self.telegram_configured,
                ),
                run,
            )
        return event_ids, decisions

    def _apply(
        self,
        tracked: TrackedEvent,
        next_status: EventStatus,
        attrs: dict[str, Any],
        observation: GeminiObservation,
        at_ms: int,
    ) -> str | None:
        """Persist a state-machine result; returns the event id if there is one."""
        terminal = {EventStatus.idle, EventStatus.dismissed, EventStatus.resolved,
                    EventStatus.completed}

        if next_status is EventStatus.idle and tracked.status is EventStatus.idle:
            return None

        if tracked.status is EventStatus.idle and next_status is not EventStatus.idle:
            # A new episode begins; its start time is the dedup identity, so
            # replaying the same footage lands on the same event row.
            tracked.episode_started_ms = at_ms

        if next_status is EventStatus.confirmed and tracked.status is not EventStatus.confirmed:
            tracked.confirmed_at_ms = at_ms
            tracked.alert_sent = False

        started = tracked.episode_started_ms or at_ms
        key = dedup_key(self.subject_id, tracked.event_type.value, str(started))
        event_id, created = self.repos.upsert_event(
            subject_id=self.subject_id,
            event_type=tracked.event_type,
            status=next_status,
            dedup_key=key,
            occurred_at_ms=started,
            confidence=observation.confidence,
            attributes={**attrs, "observation": observation.to_dict()},
            schema_version=observation.schema_version,
            ended_at_ms=at_ms if next_status in terminal else None,
        )
        changed = next_status is not tracked.status
        tracked.status = next_status
        tracked.event_id = event_id

        if next_status in terminal:
            tracked.history.clear()
            tracked.episode_started_ms = None
            tracked.confirmed_at_ms = None
            tracked.status = EventStatus.idle

        if created or changed:
            self.broadcast(
                "event.updated",
                {"event_id": event_id, "event_type": tracked.event_type.value,
                 "status": next_status.value, "attributes": attrs},
            )
        return event_id

    def _tracked_snapshot(self) -> dict[str, dict[str, Any]]:
        with self._state_lock:
            return {
                t.event_type.value: {
                    "status": t.status.value,
                    "event_id": t.event_id,
                    "observations": len(t.history),
                }
                for t in self.tracked.values()
            }

    # -- escalation ------------------------------------------------------

    def _escalation_trigger(
        self, observation: GeminiObservation, at_ms: int
    ) -> tuple[EscalationTrigger | None, str]:
        escalation = self.policy.escalation
        if not escalation.enabled or self.l3 is None:
            return None, "l3_disabled"

        today = day_key(at_ms)
        with self._state_lock:
            if today != self._escalation_day:
                self._escalation_day = today
                self._escalations_today = 0
            if self._escalations_today >= escalation.max_per_day:
                return None, f"daily_cap_reached_{escalation.max_per_day}"

            fall_status = self.tracked[EventType.fall].status

        forced = fall_status.value in escalation.force_on_states
        requested = escalation.honour_model_request and observation.needs_escalation()
        if not (forced or requested):
            return None, "no_escalation_requested"

        scope = "fall" if forced else "observation"
        last = self._last_escalation_ms.get(scope)
        if last is not None and (at_ms - last) / 1000.0 < escalation.min_seconds_between:
            gap = (at_ms - last) / 1000.0
            return None, f"escalation_rate_limited_{gap:.0f}s"

        trigger = EscalationTrigger.high_risk_state if forced else EscalationTrigger.gemini_requested
        with self._state_lock:
            self._last_escalation_ms[scope] = at_ms
            self._escalations_today += 1
        return trigger, ", ".join(observation.escalation.normalised_reasons()) or fall_status.value

    def _offer_escalation(
        self,
        run: PipelineRun,
        observation: GeminiObservation,
        trigger: EscalationTrigger,
        reason: str,
        packets: list[FramePacket],
        clip: VideoClip | None,
        at_ms: int,
    ) -> None:
        reasons = observation.escalation.normalised_reasons() or [reason or "other"]
        bundle = EvidenceBundle(
            escalation_id=new_id("esc"),
            trigger=trigger,
            reason_codes=reasons,
            l2_observation=observation.to_dict(),
            event_state=self._tracked_snapshot(),
            clip=clip,
            transcript=self._transcript(run.window_started_at_ms),
            aggregates=self._aggregates(),
        )
        step_id = self._step(run.run_id, "l3_review", "waiting", "等待 L3 深度覆核",
                             reason_codes=reasons,
                             event_id=run.event_ids[0] if run.event_ids else None)
        job = QueuedJob(
            payload=(run, bundle, [p.jpeg for p in packets], at_ms, step_id),
            high_risk=trigger is EscalationTrigger.high_risk_state,
            enqueued_at_ms=at_ms,
            label=trigger.value,
        )
        accepted, queue_reason = self.l3_queue.offer(job)
        if not accepted:
            run.mark_l3_not_required(queue_reason)
            self._step(run.run_id, "l3_review", "skipped", "L3 queue 未接受本視窗",
                       reason_codes=[queue_reason], step_id=step_id,
                       event_id=run.event_ids[0] if run.event_ids else None)
            self.repos.save_run(run)

    def _aggregates(self) -> dict[str, Any]:
        try:
            return {
                "hydration_today": self.repos.hydration_summary(),
                "recent_windows": self.repos.run_stats(now_ms() - 3_600_000),
            }
        except Exception:  # noqa: BLE001
            return {}

    # -- L3 worker -------------------------------------------------------

    def _l3_loop(self) -> None:
        while not self._stop.is_set():
            job = self.l3_queue.take(timeout=1.0)
            if job is None:
                continue
            try:
                self._run_escalation(*job.payload)
            except Exception as exc:  # noqa: BLE001
                self.repos.log("error", "cascade", f"escalation failed: {exc}")
            finally:
                self.l3_queue.finish()

    def _run_escalation(
        self, run: PipelineRun, bundle: EvidenceBundle, frames: list[bytes], at_ms: int,
        step_id: str | None = None,
    ) -> None:
        if step_id is not None:
            self._step(run.run_id, "l3_review", "running", "正在執行 L3 深度覆核",
                       reason_codes=bundle.reason_codes, step_id=step_id,
                       event_id=run.event_ids[0] if run.event_ids else None)
        result = self.l3.analyse(
            bundle,
            frames,
            allow_text_only=self.policy.escalation.allow_text_only_fallback,
        )
        run.l3_outcome = result.outcome.value
        run.l3_reason = result.reason
        run.l3_call_id = result.call.call_id
        run.l3_model = result.call.model
        run.l3_latency_ms = result.call.latency_ms
        run.l3_error = (
            f"{result.call.error_code}: {result.call.error_message}" if not result.ok else None
        )
        self.repos.save_model_call(result.call)

        if result.ok:
            run.l3_risk_level = result.analysis.risk_level
            self.repos.save_analysis(
                event_id=run.event_ids[0] if run.event_ids else None,
                run_id=run.run_id,
                call_id=result.call.call_id,
                trigger=bundle.trigger.value,
                reason_codes=bundle.reason_codes,
                degraded=bundle.degraded_text_only,
                payload=result.analysis.to_dict(),
            )
            decisions = self._apply_policy(
                PolicyInput(
                    event_type=EventType.fall,
                    event_status=self.tracked[EventType.fall].status,
                    event_id=run.event_ids[0] if run.event_ids else "",
                    analysis=result.analysis,
                    last_notified_at_ms=self.repos.last_notification_ms(self.subject_id),
                    now_ms=at_ms,
                    telegram_configured=self.telegram_configured,
                ),
                run,
            )
            run.action_ids.extend(d.action_id for d in decisions)

        self._step(run.run_id, "l3_review", "succeeded" if result.ok else "failed",
                   result.analysis.interpretation if result.ok else "L3 深度覆核失敗",
                   reason_codes=bundle.reason_codes, step_id=step_id,
                   event_id=run.event_ids[0] if run.event_ids else None,
                   output_data={"risk_level": run.l3_risk_level,
                                "recommendation": result.analysis.recommendation if result.ok else None,
                                "error": run.l3_error})

        self.repos.save_run(run)
        self.broadcast("pipeline.run", run.to_dict())

    # -- policy ----------------------------------------------------------

    def _apply_policy(self, request: PolicyInput, run: PipelineRun) -> list[PolicyDecision]:
        decisions = self.policy_gateway.decide(request)
        for decision in decisions:
            self.repos.save_action(decision, run.run_id)
            if decision.kind.value != "log_only":
                self.broadcast("action.created", decision.to_dict())
            self._deliver(decision, request.event_id)
        self._step(run.run_id, "policy_gateway", "succeeded", "Policy 決策完成",
                   reason_codes=[decision.rule for decision in decisions],
                   event_id=request.event_id or None,
                   output_data={"actions": [decision.kind.value for decision in decisions]})
        return decisions

    def _deliver(self, decision: PolicyDecision, event_id: str) -> None:
        """Hand an authorised decision to a channel. Delivery cannot fail loudly.

        A transport problem must not roll back the event or the action row:
        the decision was made and is recorded either way, and the delivery
        row carries whether it actually reached anyone.
        """
        if self.notifier is None or decision.suppressed:
            return
        if decision.kind is not ActionKind.notify_telegram:
            return
        try:
            event = self.repos.get_event(event_id) if event_id else None
            self.notifier.dispatch(decision, event)
        except Exception as exc:  # noqa: BLE001
            self.repos.log("error", "cascade", f"notification dispatch failed: {exc}")

    # -- persistence / introspection --------------------------------------

    def _persist(self, run: PipelineRun) -> None:
        self.repos.save_run(run.close())
        self._step(run.run_id, "persistence", "succeeded", "稽核紀錄已寫入 SQLite",
                   event_id=run.event_ids[0] if run.event_ids else None)
        self.repos.prune_pipeline_steps()
        self.broadcast("pipeline.run", run.to_dict())

    def _on_drop(self, job: QueuedJob, reason: str) -> None:
        self.repos.log("debug", "cascade", f"dropped {job.label}: {reason}")

    def status(self) -> dict[str, Any]:
        detector_health = self.detector.health()
        gate_decision = self.gate.decide()
        return {
            "subject_id": self.subject_id,
            "config_version": self.policy.version,
            "windows_seen": self.windows_seen,
            "starved_since_ms": self._starved_since_ms or None,
            "frames": self.frames.metrics(),
            "l1": {
                "detector": detector_health,
                "decision": gate_decision.to_dict(),
                "gate": self.gate.metrics(),
                "health": detector_health.get("status", Health.unknown.value),
            },
            "l2": {"queue": self.l2_queue.metrics(), "model": getattr(self.l2.backend, "model", None)},
            "l3": {
                "queue": self.l3_queue.metrics(),
                "model": getattr(getattr(self.l3, "backend", None), "model", None),
                "enabled": self.l3 is not None and self.policy.escalation.enabled,
                "today": self._escalations_today,
            },
            "events": self._tracked_snapshot(),
            "notifier": {
                "channel": "telegram",
                "configured": self.notifier is not None and self.notifier.configured,
                "chats": len(self.notifier.chat_ids) if self.notifier is not None else 0,
            },
        }
