from __future__ import annotations

import hashlib
import json
import random
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from ..domain.enums import EventStatus, EventType
from ..domain.ids import new_id
from ..domain.model_call import ModelCall
from ..domain.pipeline_run import PipelineRun
from ..domain.timeutil import iso, now_ms
from ..observer.daily import run_observer


SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {"label": "日常活動", "person": True, "posture": "standing", "summary": "住民正常走動"},
    "hydration": {"label": "完成飲水", "person": True, "posture": "sitting", "drinking": True,
                  "container": "cup", "summary": "住民正在飲水"},
    "fall_suspect": {"label": "疑似跌倒", "person": True, "posture": "lying", "near_floor": True,
                     "motionless": False, "escalate": True, "summary": "住民倒地，仍有動作"},
    "fall_confirmed": {"label": "確認跌倒", "person": True, "posture": "lying", "near_floor": True,
                       "motionless": True, "escalate": True, "summary": "住民倒地且持續沒有動作"},
    "recovery": {"label": "跌倒後恢復", "person": True, "posture": "sitting", "near_floor": False,
                 "motionless": False, "summary": "住民已坐起，持續追蹤恢復狀態"},
    "occluded": {"label": "畫面遮擋", "person": True, "posture": "unknown", "occluded": True,
                 "summary": "畫面遭遮擋，無法完整判讀"},
}


class DebugSimulator:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()
        self._stream_status: dict[str, Any] = {"running": False}

    def scenarios(self) -> list[dict[str, Any]]:
        return [{"id": key, "name": value["label"]} for key, value in SCENARIOS.items()]

    def generate_history(self, *, days: int = 45, profile: str = "mixed", seed: int = 20260906) -> dict[str, Any]:
        days = max(1, min(90, int(days)))
        if profile not in {"stable", "gradual-decline", "event-heavy", "mixed"}:
            raise ValueError("unknown history profile")
        end_day = datetime.now(tz=timezone.utc).date()
        key = f"history:{days}:{profile}:{seed}:{end_day.isoformat()}"
        simulation_id = "sim_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        existing = self.ctx.db.query_one(
            "SELECT * FROM simulation_runs WHERE simulation_id=?", (simulation_id,))
        if existing is not None:
            return {"simulation_id": simulation_id, "status": "already_generated",
                    "generated_rows": int(existing["generated_rows"])}

        started = now_ms()
        self.ctx.db.execute(
            """INSERT INTO simulation_runs
               (simulation_id, kind, profile, mode, seed, status, parameters_json,
                generated_rows, started_at_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (simulation_id, "history", profile, "contract", seed, "running",
             json.dumps({"days": days, "end_day": end_day.isoformat()}), 0, started, iso()),
        )
        rng = random.Random(seed)
        rows = 0
        for offset in range(days - 1, -1, -1):
            day = end_day - timedelta(days=offset)
            day_start = int(datetime(day.year, day.month, day.day, 8, tzinfo=timezone.utc).timestamp() * 1000)
            decline = (days - 1 - offset) / max(1, days - 1)
            hydration_target = 1450
            activity = 0.62
            if profile in {"gradual-decline", "mixed"}:
                hydration_target -= int(500 * decline)
                activity -= 0.25 * decline

            for metric, value, unit in (
                ("heart_rate", 70 + rng.randint(-5, 7) + int(5 * decline), "bpm"),
                ("blood_oxygen", 97 + rng.randint(-1, 1) - int(2 * decline), "%"),
                ("temperature", round(36.4 + rng.uniform(-0.2, 0.25), 1), "°C"),
            ):
                self.ctx.repos.save_health_sample(
                    self.ctx.config.subject_id, metric, value, unit,
                    f"simulation:{simulation_id}", day_start + rng.randint(0, 28_800_000))
                rows += 1

            drink_count = max(2, round(hydration_target / 250))
            for index in range(drink_count):
                at = day_start + (index + 1) * 3_600_000
                event_id, _ = self.ctx.repos.upsert_event(
                    self.ctx.config.subject_id, EventType.hydration, EventStatus.completed,
                    f"{simulation_id}:hydration:{day}:{index}", at, 0.9,
                    {"simulation_id": simulation_id, "seed": seed, "generated": True},
                    "debug.simulation.v1", at)
                self.ctx.db.execute(
                    "UPDATE events SET created_at=?, updated_at_ms=? WHERE event_id=?",
                    (iso(at), at, event_id))
                self.ctx.repos.save_hydration_session(
                    event_id, self.ctx.config.subject_id, at - 60_000, at, 250)
                rows += 2

            fall_today = profile == "event-heavy" and rng.random() < 0.25
            fall_today = fall_today or (profile == "mixed" and decline > 0.65 and rng.random() < 0.18)
            fall_event_id = None
            if fall_today:
                fall_at = day_start + 36_000_000
                fall_event_id, _ = self.ctx.repos.upsert_event(
                    self.ctx.config.subject_id, EventType.fall, EventStatus.resolved,
                    f"{simulation_id}:fall:{day}", fall_at, 0.91,
                    {"simulation_id": simulation_id, "seed": seed, "generated": True,
                     "resolved_after_sec": 90}, "debug.simulation.v1", fall_at + 90_000)
                self.ctx.db.execute(
                    "UPDATE events SET created_at=?, updated_at_ms=? WHERE event_id=?",
                    (iso(fall_at), fall_at + 90_000, fall_event_id))
                rows += 1

            for index in range(16):
                at = day_start + index * 3_000_000
                called = rng.random() < max(0.25, activity)
                observation = {
                    "person_visible": called, "person_count": 1 if called else 0,
                    "scene_summary": "住民正常活動" if called else "畫面無人",
                    "confidence": 0.88, "uncertainty_reasons": [],
                    "fall": {"posture": "standing" if called else "unknown", "vertical_transition": "none",
                             "near_floor": False, "motionless": False, "confidence": 0.88},
                    "hydration": {"container": "none", "container_near_mouth": False,
                                  "drinking_motion": False, "confidence": 0.8},
                    "escalation": {"required": False, "reason_codes": [],
                                   "requested_evidence_window_sec": 10},
                    "schema_version": "l2.observation.v1",
                    "simulation": {"simulation_id": simulation_id, "seed": seed, "generated": True},
                }
                run = PipelineRun(
                    subject_id=self.ctx.config.subject_id,
                    window_started_at_ms=at - 5000, window_ended_at_ms=at,
                    config_version=f"debug:{simulation_id}",
                    l1_decision="person_present" if called else "no_person",
                    l1_confidence=0.9, l1_detector_id="simulation", l1_health="ok",
                    l2_outcome="called" if called else "skipped_l1",
                    l2_reason="simulation_activity" if called else "simulation_empty_room",
                    l2_model="stub-l2" if called else None,
                    l2_latency_ms=5 if called else None,
                    l3_outcome="not_required", l3_reason="no_escalation_requested",
                    created_at=iso(at),
                )
                if called:
                    call = ModelCall(
                        layer="l2_gemini", provider="stub", model="stub-l2",
                        purpose="simulation_contract", prompt_version="l2.observation.v1",
                        schema_version="l2.observation.v1", latency_ms=5,
                        input_hash=simulation_id, response_text=json.dumps(observation, ensure_ascii=False),
                        created_at=iso(at))
                    self.ctx.repos.save_model_call(call)
                    run.l2_call_id = call.call_id
                    # Observations and actions reference the run, so write the
                    # initial audit row before those child records.
                    self.ctx.repos.save_run(run)
                    self.ctx.repos.save_observation(
                        run.run_id, self.ctx.config.subject_id, at,
                        observation["scene_summary"], 0.88, observation)
                    rows += 2
                if fall_event_id and index == 12:
                    run.event_ids = [fall_event_id]
                    run.l2_escalation_required = True
                    run.l2_escalation_reasons = ["possible_fall", "person_motionless_on_floor"]
                    run.l3_outcome = "called"
                    run.l3_model = "stub-l3"
                    run.l3_latency_ms = 5
                    run.l3_risk_level = "critical"
                    self.ctx.repos.save_analysis(
                        fall_event_id, run.run_id, None, "simulation_contract",
                        run.l2_escalation_reasons, False,
                        {"risk_level": "critical", "recommendation": "suggest_caregiver_notification",
                         "supports_l2": True, "simulation_id": simulation_id})
                    action = SimpleNamespace(
                        action_id=new_id("act"), event_id=fall_event_id,
                        kind=SimpleNamespace(value="dashboard_alert"),
                        rule="l3_advisory_not_authorised",
                        reason="L3 建議照護人員複核跌倒事件", severity="critical",
                        suppressed=False, suppressed_reason="")
                    self.ctx.repos.save_action(action, run.run_id)
                    run.action_ids = [action.action_id]
                    rows += 2
                self.ctx.repos.save_run(run)
                simulation_meta = {"simulation_id": simulation_id, "seed": seed, "generated": True}
                self.ctx.repos.save_pipeline_step(
                    run_id=run.run_id, step="l1_gate", status="succeeded",
                    summary="歷史模擬的 L1 判讀", output_data={"decision": run.l1_decision, **simulation_meta},
                    mode="debug", started_at_ms=at - 20)
                self.ctx.repos.save_pipeline_step(
                    run_id=run.run_id, step="l2_observation",
                    status="succeeded" if called else "skipped",
                    summary="歷史模擬的 L2 觀察" if called else "歷史模擬的空房略過",
                    output_data=simulation_meta, mode="debug", started_at_ms=at - 10)
                self.ctx.repos.save_pipeline_step(
                    run_id=run.run_id, step="persistence", status="succeeded",
                    summary="歷史模擬資料已寫入 SQLite", output_data=simulation_meta,
                    mode="debug", started_at_ms=at)
                rows += 3
                rows += 1

            observed = run_observer(self.ctx, day.isoformat(), threshold=999.0)
            self.ctx.db.execute(
                "UPDATE observer_runs SET window_started_at_ms=?, window_ended_at_ms=?, created_at=? "
                "WHERE observer_run_id=?",
                (day_start, day_start + 43_200_000, iso(day_start + 43_200_000), observed["observer_run_id"]))
            rows += 2

        self.ctx.db.execute(
            "UPDATE simulation_runs SET status='completed', generated_rows=?, completed_at_ms=? "
            "WHERE simulation_id=?", (rows, now_ms(), simulation_id))
        self.ctx.broadcaster.publish("debug.history.generated", {
            "simulation_id": simulation_id, "days": days, "profile": profile, "rows": rows})
        return {"simulation_id": simulation_id, "status": "completed",
                "days": days, "profile": profile, "seed": seed, "generated_rows": rows}

    def trigger(self, scenario: str, mode: str = "contract") -> dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError("unknown scenario")
        if mode not in {"contract", "evaluation"}:
            raise ValueError("mode must be contract or evaluation")
        simulation_id = new_id("sim")
        annotation = dict(SCENARIOS[scenario])
        annotation.update({"simulation_id": simulation_id, "seed": 0, "generated": True,
                           "simulation_mode": mode})
        if mode == "evaluation":
            annotation["simulation_context"] = {
                "scenario": scenario,
                "description": annotation.get("summary", annotation["label"]),
                "instruction": "根據目前事件證據判斷風險與是否需要升級；不要假設預期答案。",
            }
        manifest = {
            "name": f"Debug · {annotation['label']}",
            "description": "Generated debug scenario",
            "segments": [{**annotation, "duration_sec": 8}],
        }
        self.ctx.db.execute(
            """INSERT INTO simulation_runs
               (simulation_id, kind, profile, mode, seed, status, parameters_json,
                generated_rows, started_at_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (simulation_id, "manual", scenario, mode, 0, "running",
             json.dumps({"scenario": scenario}, ensure_ascii=False), 0, now_ms(), iso()))
        source = self.ctx.start_scripted_source(manifest, f"simulation:{simulation_id}")
        return {"simulation_id": simulation_id, "scenario": scenario, "mode": mode,
                "status": "running", "source": source,
                "provider": getattr(self.ctx.l2, "provider", "unknown")}

    def start_stream(self, *, profile: str = "mixed", seed: int = 20260906,
                     interval_sec: float = 12.0) -> dict[str, Any]:
        if self._stream_thread is not None and self._stream_thread.is_alive():
            return self._stream_status
        self._stream_stop.clear()
        rng = random.Random(seed)
        choices = ["normal", "normal", "hydration", "fall_suspect", "fall_confirmed", "occluded"]
        self._stream_status = {"running": True, "profile": profile, "seed": seed,
                               "interval_sec": max(2.0, interval_sec), "events": 0}

        def run() -> None:
            while not self._stream_stop.is_set():
                scenario = rng.choice(choices)
                self.trigger(scenario, "contract")
                self._stream_status["events"] += 1
                self._stream_status["last_scenario"] = scenario
                self._stream_stop.wait(max(2.0, interval_sec))
            self._stream_status["running"] = False

        self._stream_thread = threading.Thread(target=run, name="debug-stream", daemon=True)
        self._stream_thread.start()
        return self._stream_status

    def stop_stream(self) -> dict[str, Any]:
        self._stream_stop.set()
        if self._stream_thread is not None:
            self._stream_thread.join(timeout=3)
            self._stream_thread = None
        self._stream_status["running"] = False
        return self._stream_status

    def status(self) -> dict[str, Any]:
        return {"stream": dict(self._stream_status), "scenarios": self.scenarios()}
