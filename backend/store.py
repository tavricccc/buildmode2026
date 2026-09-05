from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable

from .config import Settings
from .db import Database
from .schemas import VisionObservation, row_json
from .state_tracker import initial_state, update_state


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_reminder_time(value: str) -> str | None:
    """Accept model-normalized ISO datetime or a local HH:MM reminder time."""
    text = (value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except ValueError:
        pass
    match = re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", text)
    if not match:
        return None
    hour, minute = (int(part) for part in text.split(":"))
    local_now = datetime.now().astimezone()
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def json_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class Store:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def log(self, level: str, component: str, message: str, event_id: str | None = None, context: dict | None = None) -> None:
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO app_logs(ts,level,component,event_id,message,context_json) VALUES(?,?,?,?,?,?)",
                         (now_iso(), level, component, event_id, message, self.db.dumps(context or {})))

    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.db.fetch_one("SELECT value_json FROM runtime_state WHERE key=?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def set_state(self, key: str, value: Any) -> None:
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO runtime_state(key,value_json,version,updated_at) VALUES(?,?,1,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,version=runtime_state.version+1,updated_at=excluded.updated_at""",
                         (key, self.db.dumps(value), now_iso()))

    def save_setting(self, key: str, value: Any, config_version: str | None = None) -> None:
        version = config_version or self.settings.config_version
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO settings(key,value_json,config_version,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,config_version=excluded.config_version,updated_at=excluded.updated_at",
                         (key, self.db.dumps(value), version, now_iso()))

    def clear_runtime(self) -> None:
        with self.db.transaction() as conn:
            # Setup/configuration is durable state, while these keys belong to a
            # replay run and must never leak into the next run.
            conn.execute("DELETE FROM runtime_state WHERE key IN ('fall_state','hydration_state','replay_state','high_risk_state','resident_proactive_last_check') OR key LIKE 'posture_tracker:%'" )

    def high_risk_state(self) -> dict[str, Any]:
        value = self.get_state("high_risk_state", {})
        return value if isinstance(value, dict) else {}

    def high_risk_active(self) -> bool:
        return self.high_risk_state().get("status") in {"active", "awaiting_response", "confirmed"}

    def begin_high_risk(self, *, stream_id: str, source_window_id: str, event_type: str,
                        event_label: str, confidence: float, reason: str, question: str,
                        started_at: str, response_deadline_at: str, next_question_at: str) -> dict[str, Any]:
        current = self.high_risk_state()
        if current.get("status") in {"active", "awaiting_response", "confirmed"}:
            return current
        state = {"status": "awaiting_response", "stream_id": stream_id, "source_window_id": source_window_id,
                 "event_type": event_type, "event_label": event_label, "confidence": float(confidence),
                 "reason": reason[:500], "question": question[:300], "question_count": 1,
                 "started_at": started_at, "last_question_at": started_at,
                 "response_deadline_at": response_deadline_at, "next_question_at": next_question_at,
                 "response_received_at": None, "response_text": None, "focus_window_id": None,
                 "main_agent_run_id": None, "cloud_confirmation": None, "action_executed": False}
        self.set_state("high_risk_state", state)
        return state

    def update_high_risk(self, **updates: Any) -> dict[str, Any]:
        state = self.high_risk_state()
        state.update(updates)
        self.set_state("high_risk_state", state)
        return state

    def finish_high_risk(self, *, status: str, reason: str) -> dict[str, Any]:
        state = self.high_risk_state()
        state.update({"status": status, "resolution_reason": reason[:500], "ended_at": now_iso()})
        self.set_state("high_risk_state", state)
        return state

    @staticmethod
    def _stream_timestamp_conn(conn, run_id: str, offset_ms: int, fallback: str) -> str:
        """Map a media offset to wall-clock time when the run is a live stream."""
        row = conn.execute("SELECT started_at FROM virtual_camera_streams WHERE id=?", (run_id,)).fetchone()
        if not row:
            return fallback
        return (parse_dt(row["started_at"]) + timedelta(milliseconds=max(0, int(offset_ms)))).isoformat(timespec="milliseconds")

    def add_evidence(self, conn, offset_ms: int, run_id: str, source_type: str = "replay_frame", metadata: dict | None = None, offset_end_ms: int | None = None) -> str:
        evidence_id = make_id("evd")
        ts = now_iso()
        conn.execute("""INSERT INTO evidence(id,subject_id,source_type,source_uri,source_offset_start_ms,source_offset_end_ms,captured_at,metadata_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                     (evidence_id, self.settings.subject_id, source_type, f"{source_type}://{run_id}", offset_ms, offset_end_ms if offset_end_ms is not None else offset_ms,
                      ts, self.db.dumps(metadata or {"run_id": run_id}), ts))
        return evidence_id

    def add_model_call(self, conn, *, provider: str, model: str, purpose: str, input_hash: str, prompt_version: str,
                       schema_version: str, status: str, response: Any = None, latency_ms: int | None = None,
                       error_code: str | None = None, tokens_in: int | None = None, tokens_out: int | None = None) -> str:
        existing = conn.execute("""SELECT id FROM model_calls WHERE provider=? AND model=? AND purpose=? AND input_hash=? AND prompt_version=?""",
                                (provider, model, purpose, input_hash, prompt_version)).fetchone()
        if existing:
            return existing["id"]
        model_id = make_id("call")
        conn.execute("""INSERT INTO model_calls(id,provider,model,purpose,input_hash,prompt_version,schema_version,status,latency_ms,tokens_in,tokens_out,error_code,response_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (model_id, provider, model, purpose, input_hash, prompt_version, schema_version, status, latency_ms,
                      tokens_in, tokens_out, error_code, self.db.dumps(response) if response is not None else None, now_iso()))
        return model_id

    def start_agent_run(self, *, agent_name: str, trigger_type: str, trigger_id: str,
                        window_id: str | None, input_context: dict[str, Any], dedup_key: str) -> tuple[dict[str, Any], bool]:
        """Create an auditable main-agent run, or return the idempotent existing run."""
        existing = self.db.fetch_one("SELECT * FROM agent_runs WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("input_json", "analysis_json", "policy_json")), False
        run_id = make_id("agent")
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO agent_runs(
                id,subject_id,agent_name,trigger_type,trigger_id,window_id,status,decision,
                attention_level,risk_level,confidence,input_json,policy_json,config_version,
                started_at,created_at,dedup_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id, self.settings.subject_id, agent_name, trigger_type, trigger_id, window_id,
                "running", "insufficient_data", "none", "unknown", 0.0,
                self.db.dumps(input_context), "{}", self.settings.config_version, ts, ts, dedup_key,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM agent_runs WHERE id=?", (run_id,)),
                        ("input_json", "analysis_json", "policy_json")), True

    def finish_agent_run(self, run_id: str, *, status: str, judgment: dict[str, Any],
                         policy: dict[str, Any], model_call_id: str | None,
                         latency_ms: int | None, error_code: str | None = None) -> dict[str, Any]:
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("""UPDATE agent_runs SET status=?,decision=?,attention_level=?,risk_level=?,confidence=?,
                analysis_json=?,policy_json=?,model_call_id=?,error_code=?,latency_ms=?,completed_at=? WHERE id=?""", (
                status, policy.get("final_action", "silent"), policy.get("attention_level", "none"),
                policy.get("risk_level", judgment.get("risk_level", "unknown")),
                float(judgment.get("confidence", 0)), self.db.dumps(judgment), self.db.dumps(policy),
                model_call_id, error_code, latency_ms, ts, run_id,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM agent_runs WHERE id=?", (run_id,)),
                        ("input_json", "analysis_json", "policy_json"))

    def fail_agent_run(self, run_id: str, *, error_code: str, policy: dict[str, Any] | None = None,
                       latency_ms: int | None = None) -> dict[str, Any]:
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("""UPDATE agent_runs SET status='failed',decision='insufficient_data',attention_level='none',
                risk_level='unknown',error_code=?,latency_ms=?,policy_json=?,completed_at=? WHERE id=?""", (
                error_code, latency_ms, self.db.dumps(policy or {"final_action": "silent", "reason": "agent_failed"}), ts, run_id,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM agent_runs WHERE id=?", (run_id,)),
                        ("input_json", "analysis_json", "policy_json"))

    def agent_runs(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("input_json", "analysis_json", "policy_json"))
                for row in self.db.fetch_all("SELECT * FROM agent_runs WHERE subject_id=? ORDER BY created_at DESC LIMIT ?",
                                             (self.settings.subject_id, limit))]

    def latest_period_summary_end(self, summary_type: str | None = None) -> str | None:
        if summary_type:
            row = self.db.fetch_one("SELECT MAX(window_end) AS window_end FROM agent_period_summaries WHERE subject_id=? AND summary_type=?", (self.settings.subject_id, summary_type))
        else:
            row = self.db.fetch_one("SELECT MAX(window_end) AS window_end FROM agent_period_summaries WHERE subject_id=?", (self.settings.subject_id,))
        return row["window_end"] if row and row["window_end"] else None

    def period_summary_context(self, start: str, end: str) -> dict[str, Any]:
        """Build a bounded, log-derived context for the periodic main-agent digest."""
        def compact_event(item: dict[str, Any]) -> dict[str, Any]:
            attrs = item.get("attributes_json") or item.get("attributes") or {}
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except json.JSONDecodeError:
                    attrs = {}
            return {"id": item.get("id"), "event_type": item.get("event_type"), "label": item.get("label"),
                    "status": item.get("status"), "occurred_at": item.get("occurred_at"),
                    "confidence": item.get("confidence"), "source_offset_ms": item.get("source_offset_ms"),
                    "attributes": {key: attrs[key] for key in ("from_state", "to_state", "occurred_offset_ms", "confirmed_offset_ms", "session_status", "intent", "request_text", "reported_event_type", "reported_event_summary", "reminder_time", "reminder_text") if key in attrs}}

        events, _ = self.list_events(start=start, end=end, limit=100)
        gates = [row_json(row, ("change_reasons_json",)) for row in self.db.fetch_all(
            "SELECT * FROM change_gate_results WHERE subject_id=? AND end_offset_ms>=0 AND created_at>=? AND created_at<=? ORDER BY created_at ASC LIMIT 200",
            (self.settings.subject_id, start, end))]
        descriptions = [row_json(row, ("facts_json", "objects_json", "actions_json", "changes_json", "warnings_json", "unknowns_json")) for row in self.db.fetch_all(
            "SELECT * FROM visual_descriptions WHERE subject_id=? AND created_at>=? AND created_at<=? ORDER BY start_offset_ms ASC LIMIT 80",
            (self.settings.subject_id, start, end))]
        segments = [row_json(row, ("observed_actions_json", "not_observed_actions_json", "uncertainty_json", "source_description_ids_json")) for row in self.db.fetch_all(
            "SELECT * FROM time_segments WHERE subject_id=? AND created_at>=? AND created_at<=? ORDER BY start_offset_ms ASC LIMIT 80",
            (self.settings.subject_id, start, end))]
        runs = [row_json(row, ("analysis_json", "policy_json")) for row in self.db.fetch_all(
            "SELECT * FROM agent_runs WHERE subject_id=? AND created_at>=? AND created_at<=? ORDER BY created_at ASC LIMIT 80",
            (self.settings.subject_id, start, end))]
        transcripts = [dict(row) for row in self.db.fetch_all(
            "SELECT id,started_at,ended_at,text,language,confidence FROM transcripts WHERE subject_id=? AND started_at>=? AND started_at<=? ORDER BY started_at ASC LIMIT 80",
            (self.settings.subject_id, start, end))]
        logs = [row_json(row, ("context_json",)) for row in self.db.fetch_all(
            "SELECT id,ts,level,component,message,context_json FROM app_logs WHERE ts>=? AND ts<=? ORDER BY ts ASC LIMIT 160",
            (start, end))]

        compact_runs = []
        for run in runs:
            analysis = run.get("analysis_json") or {}
            policy = run.get("policy_json") or {}
            compact_runs.append({"id": run.get("id"), "created_at": run.get("created_at"), "status": run.get("status"),
                                 "decision": run.get("decision"), "window_id": run.get("window_id"),
                                 "situation_summary": analysis.get("situation_summary"), "situation_phase": analysis.get("situation_phase"),
                                 "observed_facts": (analysis.get("observed_facts") or [])[:6], "unknowns": (analysis.get("unknowns") or [])[:6],
                                 "decision_reasons": (analysis.get("decision_reasons") or [])[:6], "final_action": policy.get("final_action"),
                                 "risk_level": policy.get("risk_level") or run.get("risk_level"), "attention_level": policy.get("attention_level") or run.get("attention_level"),
                                 "confidence": run.get("confidence"), "error_code": run.get("error_code")})
        compact_logs = [{"ts": item.get("ts"), "level": item.get("level"), "component": item.get("component"), "message": item.get("message"),
                         "context": {key: (item.get("context_json") or {}).get(key) for key in ("window_id", "stream_id", "provider", "model", "error_code", "final_action", "attention_score") if key in (item.get("context_json") or {})}}
                        for item in logs]
        return {"window": {"start": start, "end": end}, "events": [compact_event(item) for item in events],
                "change_gates": [{key: item.get(key) for key in ("window_id", "start_offset_ms", "end_offset_ms", "changed", "change_score", "threshold", "change_reasons_json", "method")} for item in gates],
                "visual_descriptions": [{key: item.get(key) for key in ("window_id", "start_offset_ms", "end_offset_ms", "description_text", "actions_json", "changes_json", "warnings_json", "confidence", "warning_level")} for item in descriptions],
                "time_segments": [{key: item.get(key) for key in ("start_offset_ms", "end_offset_ms", "summary", "observed_actions_json", "not_observed_actions_json", "uncertainty_json")} for item in segments],
                "agent_runs": compact_runs, "transcripts": transcripts, "logs": compact_logs,
                "source_counts": {"events": len(events), "change_gates": len(gates), "visual_descriptions": len(descriptions),
                                   "time_segments": len(segments), "agent_runs": len(runs), "transcripts": len(transcripts), "logs": len(logs)},
                "rules": ["只保留重要事件、人物／物品動作、語音重點、警示與未知", "不要重新描述固定場景", "沒有證據就標記 unknown"]}

    def record_period_summary(self, *, window_start: str, window_end: str, summary: dict[str, Any],
                              source_counts: dict[str, Any], status: str, model_call_id: str | None,
                              summary_type: str = "ten_minute") -> dict[str, Any]:
        dedup_key = f"period-summary:{self.settings.subject_id}:{summary_type}:{window_start}:{window_end}"
        existing = self.db.fetch_one("SELECT * FROM agent_period_summaries WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("key_events_json", "action_timeline_json", "stable_states_json", "unknowns_json", "source_counts_json"))
        summary_id = make_id("period")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO agent_period_summaries(
                id,subject_id,window_start,window_end,summary_text,key_events_json,action_timeline_json,stable_states_json,
                unknowns_json,risk_level,confidence,requires_follow_up,follow_up_reason,source_counts_json,summary_type,status,model_call_id,created_at,dedup_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                summary_id, self.settings.subject_id, window_start, window_end, summary.get("summary_text", ""),
                self.db.dumps(summary.get("key_events", [])), self.db.dumps(summary.get("action_timeline", [])), self.db.dumps(summary.get("stable_states", [])),
                self.db.dumps(summary.get("unknowns", [])), summary.get("risk_level", "unknown"), float(summary.get("confidence", 0)),
                int(bool(summary.get("requires_follow_up", False))), summary.get("follow_up_reason", ""), self.db.dumps(source_counts), summary_type, status, model_call_id, now_iso(), dedup_key,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM agent_period_summaries WHERE id=?", (summary_id,)), ("key_events_json", "action_timeline_json", "stable_states_json", "unknowns_json", "source_counts_json"))

    def agent_period_summaries(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("key_events_json", "action_timeline_json", "stable_states_json", "unknowns_json", "source_counts_json"))
                for row in self.db.fetch_all("SELECT * FROM agent_period_summaries WHERE subject_id=? ORDER BY window_end DESC LIMIT ?", (self.settings.subject_id, limit))]

    def add_agent_run_event(self, agent_run_id: str, *, stage: str, event_type: str,
                            message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        event_id = make_id("agent_evt")
        occurred_at = now_iso()
        with self.db.transaction() as conn:
            sequence = int(conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM agent_run_events WHERE agent_run_id=?", (agent_run_id,)).fetchone()["next_sequence"])
            conn.execute("""INSERT INTO agent_run_events(id,agent_run_id,subject_id,stage,event_type,message,payload_json,sequence,occurred_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""", (event_id, agent_run_id, self.settings.subject_id, stage, event_type,
                                                            message, self.db.dumps(payload or {}), sequence, occurred_at))
        return row_json(self.db.fetch_one("SELECT * FROM agent_run_events WHERE id=?", (event_id,)), ("payload_json",))

    def agent_run_events(self, limit: int = 100) -> list[dict]:
        return [row_json(row, ("payload_json",)) for row in self.db.fetch_all(
            "SELECT * FROM agent_run_events WHERE subject_id=? ORDER BY occurred_at DESC, sequence DESC LIMIT ?",
            (self.settings.subject_id, limit))]

    def add_agent_note(self, *, layer: str, note_type: str, title: str, content: dict[str, Any],
                       source_agent: str, source_run_id: str | None, source_window_id: str | None,
                       status: str = "active", confidence: float = 0.0, importance: float = 0.5,
                       privacy_level: str = "local", requires_review: bool = False,
                       expires_at: str | None = None, parent_note_id: str | None = None,
                       target_layers: list[str] | None = None, dedup_key: str) -> dict[str, Any]:
        existing = self.db.fetch_one("SELECT * FROM agent_notes WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("content_json", "target_layers_json"))
        note_id = make_id("note")
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO agent_notes(
                id,subject_id,layer,note_type,title,content_json,source_agent,source_run_id,source_window_id,
                parent_note_id,target_layers_json,status,confidence,importance,privacy_level,requires_review,
                expires_at,created_at,updated_at,dedup_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                note_id, self.settings.subject_id, layer, note_type, title, self.db.dumps(content), source_agent,
                source_run_id, source_window_id, parent_note_id, self.db.dumps(target_layers or []), status,
                max(0.0, min(1.0, confidence)), max(0.0, min(1.0, importance)), privacy_level, int(requires_review),
                expires_at, ts, ts, dedup_key,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM agent_notes WHERE id=?", (note_id,)), ("content_json", "target_layers_json"))

    def agent_notes(self, *, layer: str | None = None, limit: int = 100) -> list[dict]:
        if layer:
            rows = self.db.fetch_all("SELECT * FROM agent_notes WHERE subject_id=? AND layer=? AND status NOT IN ('expired','rejected') ORDER BY created_at DESC LIMIT ?", (self.settings.subject_id, layer, limit))
        else:
            rows = self.db.fetch_all("SELECT * FROM agent_notes WHERE subject_id=? AND status NOT IN ('expired','rejected') ORDER BY created_at DESC LIMIT ?", (self.settings.subject_id, limit))
        return [row_json(row, ("content_json", "target_layers_json")) for row in rows]

    def record_scene_context(self, *, stream_id: str, scene: dict[str, Any], model_call_id: str | None,
                             started_at: str) -> dict[str, Any]:
        scene_id = make_id("scene")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO scene_contexts(id,subject_id,stream_id,location,description_text,objects_json,non_person_features_json,uncertainty_json,confidence,model_call_id,started_at,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (scene_id, self.settings.subject_id, stream_id,
                            scene.get("location", "unknown"), scene.get("scene_description", "unknown"),
                            self.db.dumps(scene.get("objects", [])), self.db.dumps(scene.get("non_person_features", [])),
                            self.db.dumps(scene.get("uncertainty_reasons", [])), float(scene.get("confidence", 0)),
                            model_call_id, started_at, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM scene_contexts WHERE id=?", (scene_id,)),
                        ("objects_json", "non_person_features_json", "uncertainty_json"))

    def record_visual_description(self, *, stream_id: str, window: dict[str, Any], description: dict[str, Any],
                                  model_call_id: str | None, scene_context_id: str | None) -> dict[str, Any]:
        description_id = make_id("desc")
        dedup_key = f"{stream_id}:{window['window_id']}:{description.get('schema_version', 'visual-description.v1')}"
        existing = self.db.fetch_one("SELECT * FROM visual_descriptions WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("facts_json", "objects_json", "actions_json", "changes_json", "warnings_json", "unknowns_json"))
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO visual_descriptions(id,subject_id,stream_id,description_type,window_id,start_offset_ms,end_offset_ms,description_text,facts_json,objects_json,actions_json,changes_json,warnings_json,unknowns_json,confidence,warning_level,risk_event_type,risk_confirmed,model_call_id,scene_context_id,created_at,dedup_key)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (description_id, self.settings.subject_id, stream_id,
                            window.get("description_type", "detail"), window["window_id"], int(window.get("start_offset_ms", 0)), int(window.get("end_offset_ms", 0)),
                            description["description"], self.db.dumps(description.get("observed_facts", [])), self.db.dumps(description.get("visible_objects", [])),
                            self.db.dumps(description.get("person_actions", [])), self.db.dumps(description.get("changes", [])),
                            self.db.dumps(description.get("warnings", [])), self.db.dumps(description.get("unknowns", [])),
                            float(description.get("confidence", 0)), description.get("warning_level", "none"),
                            description.get("risk_event_type", ""), int(bool(description.get("risk_confirmed", False))), model_call_id,
                            scene_context_id, now_iso(), dedup_key))
        return row_json(self.db.fetch_one("SELECT * FROM visual_descriptions WHERE id=?", (description_id,)),
                        ("facts_json", "objects_json", "actions_json", "changes_json", "warnings_json", "unknowns_json"))

    def record_focus_review(self, *, stream_id: str, window: dict[str, Any], focus: dict[str, Any],
                            model_call_id: str | None) -> dict[str, Any]:
        review_id = make_id("focus")
        dedup_key = f"{stream_id}:{window['window_id']}:{focus.get('schema_version', 'focus-review.v1')}"
        existing = self.db.fetch_one("SELECT * FROM focus_reviews WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("supporting_facts_json", "unknowns_json", "evidence_frame_indexes_json"))
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO focus_reviews(id,subject_id,stream_id,window_id,trigger_window_id,abnormal,warning_level,comparison_summary,description_text,supporting_facts_json,unknowns_json,evidence_frame_indexes_json,confidence,next_action,model_call_id,created_at,dedup_key)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (review_id, self.settings.subject_id, stream_id, window["window_id"], window.get("trigger_window_id"),
                            int(bool(focus.get("abnormal"))), focus.get("warning_level", "none"), focus["comparison_summary"], focus["description"],
                            self.db.dumps(focus.get("supporting_facts", [])), self.db.dumps(focus.get("unknowns", [])),
                            self.db.dumps(focus.get("evidence_frame_indexes", [])), float(focus.get("confidence", 0)), focus["next_action"], model_call_id, now_iso(), dedup_key))
        return row_json(self.db.fetch_one("SELECT * FROM focus_reviews WHERE id=?", (review_id,)),
                        ("supporting_facts_json", "unknowns_json", "evidence_frame_indexes_json"))

    def record_time_segment(self, *, stream_id: str, window: dict[str, Any], segment: dict[str, Any],
                            description_ids: list[str], main_agent_run_id: str) -> dict[str, Any]:
        segment_id = make_id("segment")
        dedup_key = f"{stream_id}:{window['window_id']}:segment"
        existing = self.db.fetch_one("SELECT * FROM time_segments WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("observed_actions_json", "not_observed_actions_json", "uncertainty_json", "source_description_ids_json"))
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO time_segments(id,subject_id,stream_id,start_offset_ms,end_offset_ms,summary,observed_actions_json,not_observed_actions_json,uncertainty_json,source_description_ids_json,main_agent_run_id,status,created_at,dedup_key)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (segment_id, self.settings.subject_id, stream_id,
                            int(window.get("start_offset_ms", 0)), int(window.get("end_offset_ms", 0)), segment["summary"],
                            self.db.dumps(segment.get("observed_actions", [])), self.db.dumps(segment.get("not_observed_actions", [])),
                            self.db.dumps(segment.get("uncertainty", [])), self.db.dumps(description_ids), main_agent_run_id, "observed", now_iso(), dedup_key))
        return row_json(self.db.fetch_one("SELECT * FROM time_segments WHERE id=?", (segment_id,)),
                        ("observed_actions_json", "not_observed_actions_json", "uncertainty_json", "source_description_ids_json"))

    def visual_descriptions(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("facts_json", "objects_json", "actions_json", "changes_json", "warnings_json", "unknowns_json"))
                for row in self.db.fetch_all("SELECT * FROM visual_descriptions WHERE subject_id=? ORDER BY created_at DESC LIMIT ?", (self.settings.subject_id, limit))]

    def scene_contexts(self, limit: int = 20) -> list[dict]:
        return [row_json(row, ("objects_json", "non_person_features_json", "uncertainty_json"))
                for row in self.db.fetch_all("SELECT * FROM scene_contexts WHERE subject_id=? ORDER BY created_at DESC LIMIT ?", (self.settings.subject_id, limit))]

    def focus_reviews(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("supporting_facts_json", "unknowns_json", "evidence_frame_indexes_json"))
                for row in self.db.fetch_all("SELECT * FROM focus_reviews WHERE subject_id=? ORDER BY created_at DESC LIMIT ?", (self.settings.subject_id, limit))]

    def time_segments(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("observed_actions_json", "not_observed_actions_json", "uncertainty_json", "source_description_ids_json"))
                for row in self.db.fetch_all("SELECT * FROM time_segments WHERE subject_id=? ORDER BY start_offset_ms DESC LIMIT ?", (self.settings.subject_id, limit))]

    def record_change_gate(self, *, stream_id: str, window: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
        window_id = str(window["window_id"])
        dedup_key = f"{stream_id}:{window_id}:change-gate.v1"
        existing = self.db.fetch_one("SELECT * FROM change_gate_results WHERE dedup_key=?", (dedup_key,))
        if existing:
            return row_json(existing, ("change_reasons_json",))
        gate_id = make_id("gate")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO change_gate_results(
                id,subject_id,stream_id,window_id,start_offset_ms,end_offset_ms,changed,change_score,threshold,
                change_summary,change_reasons_json,method,created_at,dedup_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                gate_id, self.settings.subject_id, stream_id, window_id,
                int(window.get("start_offset_ms", 0)), int(window.get("end_offset_ms", 0)),
                int(bool(gate.get("changed"))), gate.get("change_score"), float(gate.get("threshold", 0)),
                gate.get("change_summary", ""), self.db.dumps(gate.get("change_reasons", [])),
                gate.get("method", "unknown"), now_iso(), dedup_key,
            ))
        return row_json(self.db.fetch_one("SELECT * FROM change_gate_results WHERE id=?", (gate_id,)), ("change_reasons_json",))

    def change_gate_results(self, limit: int = 100) -> list[dict]:
        return [row_json(row, ("change_reasons_json",)) for row in self.db.fetch_all(
            "SELECT * FROM change_gate_results WHERE subject_id=? ORDER BY end_offset_ms DESC, created_at DESC LIMIT ?",
            (self.settings.subject_id, limit))]

    def process_observation(self, observation: VisionObservation, run_id: str, source_type: str = "replay", window_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist evidence, local output and the state-machine transition in one transaction."""
        ts = now_iso()
        obs_dict = observation.model_dump()
        window_metadata = window_metadata or {}
        audio_attributes = {"audio_present": observation.audio_present, "audio_events": observation.audio_events, "speaker_emotion": observation.speaker_emotion, "audio_confidence": observation.audio_confidence, "audio_uncertainty_reasons": observation.audio_uncertainty_reasons, "speech_detected": observation.speech_detected, "transcript_confidence": observation.transcript_confidence, "transcript_uncertainty_reasons": observation.transcript_uncertainty_reasons}
        changed: list[dict[str, Any]] = []
        recognition_events: list[dict[str, Any]] = []
        transcript: dict[str, Any] | None = None
        tracker_snapshot: dict[str, Any] = {"state": initial_state(), "transition": None}
        with self.db.transaction() as conn:
            evidence_id = self.add_evidence(conn, int(window_metadata.get("start_offset_ms", observation.observed_at_offset_ms)), run_id, f"{source_type}_window",
                                             {"frame_indexes": observation.supporting_frame_indexes, "frame_count": window_metadata.get("frame_count", 1), "window_id": window_metadata.get("window_id"), "window_start_offset_ms": window_metadata.get("start_offset_ms", observation.observed_at_offset_ms), "window_end_offset_ms": window_metadata.get("end_offset_ms", observation.observed_at_offset_ms), "run_id": run_id}, int(window_metadata.get("end_offset_ms", observation.observed_at_offset_ms)))
            model_name = self.settings.inference_model if self.settings.local_vlm_mode in {"vllm", "real"} else self.settings.local_vlm_model
            call_id = self.add_model_call(conn, provider=self.settings.inference_provider, model=model_name,
                                          purpose="vision_events", input_hash=json_hash({"run_id": run_id, "window": window_metadata, **obs_dict}),
                                          prompt_version="vision-events.nemotron-omni.v1", schema_version="vision-observation.v1",
                                          status="valid", response=obs_dict)
            observed_at = self._stream_timestamp_conn(conn, run_id, observation.observed_at_offset_ms, ts)
            observation_record = self._record_vision_observation_conn(conn, run_id, window_metadata, observation, call_id, observed_at)
            recognition_events = self._record_recognition_events_conn(conn, observation.event_candidates, call_id, run_id, window_metadata, observed_at)

            # VLM posture is an observation. The temporal tracker is the only
            # layer allowed to emit stand/sit transition events.
            tracker_key = f"posture_tracker:{run_id}"
            previous_tracker = self._state_in_conn(conn, tracker_key, initial_state())
            tracker_snapshot = update_state(previous_tracker, observation, window_metadata)
            self._upsert_state_conn(conn, tracker_key, tracker_snapshot["state"])
            transition = tracker_snapshot.get("transition")
            if transition:
                transition_offset = int(transition["occurred_offset_ms"])
                transition_time = self._stream_timestamp_conn(conn, run_id, transition_offset, observed_at)
                dedup_key = f"posture-transition:{self.settings.subject_id}:{run_id}:{transition['event_type']}:{transition_offset}"
                recognition_id = make_id("rec")
                attrs = {**transition, "run_id": run_id, "window": window_metadata}
                insert = conn.execute("""INSERT OR IGNORE INTO recognition_events(
                    id,subject_id,event_type,domain,label,status,occurred_at,confidence,attributes_json,window_id,model_call_id,dedup_key,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    recognition_id, self.settings.subject_id, transition["event_type"], "person", transition["label"],
                    "confirmed", transition_time, float(transition["confidence"]), self.db.dumps(attrs),
                    window_metadata.get("window_id"), call_id, dedup_key, ts, ts,
                ))
                row = conn.execute("SELECT * FROM recognition_events WHERE dedup_key=?", (dedup_key,)).fetchone()
                if insert.rowcount and row:
                    recognition_events.append(row_json(dict(row), ("attributes_json",)))

            fall_state = self._state_in_conn(conn, "fall_state", {"run_id": run_id, "candidate_event_id": None, "support": 0,
                                                                     "confidence_sum": 0.0, "recovery": 0, "last_offset": None})
            if fall_state.get("run_id") != run_id:
                fall_state = {"run_id": run_id, "candidate_event_id": None, "support": 0, "confidence_sum": 0.0, "recovery": 0, "last_offset": None}
            fall_signal = observation.person_visible and (observation.vertical_transition == "down" or observation.near_floor or observation.posture == "lying")
            if fall_signal:
                fall_state["support"] = int(fall_state.get("support", 0)) + 1
                fall_state["confidence_sum"] = float(fall_state.get("confidence_sum", 0)) + observation.confidence
                if not fall_state.get("candidate_event_id"):
                    event_id = make_id("evt")
                    fall_state["candidate_event_id"] = event_id
                    attributes = {"initial_posture": observation.posture, "final_posture": observation.posture,
                                  "near_floor": observation.near_floor, "confirmed_duration_ms": 0, "recovered_at": None,
                                  "alert_due_at": None, "run_id": run_id, "audio": audio_attributes}
                    conn.execute("""INSERT INTO events(id,subject_id,event_type,status,occurred_at,source_offset_ms,confidence,attributes_json,model_call_id,dedup_key,schema_version,created_at,updated_at)
                                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (event_id, self.settings.subject_id, "fall", "candidate", ts, observation.observed_at_offset_ms,
                                  observation.confidence, self.db.dumps(attributes), call_id, f"fall:{self.settings.subject_id}:{run_id}",
                                  "event.v1", ts, ts))
                else:
                    event_id = fall_state["candidate_event_id"]
                    row = conn.execute("SELECT attributes_json,occurred_at FROM events WHERE id=?", (event_id,)).fetchone()
                    attributes = json.loads(row["attributes_json"] or "{}")
                    attributes.update({"final_posture": observation.posture, "near_floor": attributes.get("near_floor", False) or observation.near_floor, "audio": audio_attributes})
                event_row = conn.execute("SELECT status,occurred_at,confidence,attributes_json FROM events WHERE id=?", (event_id,)).fetchone()
                status = event_row["status"]
                if status == "candidate" and fall_state["support"] >= 2 and fall_state["confidence_sum"] / fall_state["support"] >= self.settings.fall_min_confidence:
                    status = "confirmed"
                    occurred = parse_dt(event_row["occurred_at"])
                    attributes["confirmed_duration_ms"] = max(0, (parse_dt(ts) - occurred).total_seconds() * 1000)
                    alert_after = self.settings.demo_no_recovery_alert_sec if self.settings.demo_mode in {"replay", "simulated"} else self.settings.fall_no_recovery_alert_sec
                    attributes["alert_due_at"] = (occurred + timedelta(seconds=alert_after)).isoformat()
                elif status in {"confirmed", "recovering"} and observation.posture in {"standing", "sitting"}:
                    fall_state["recovery"] = int(fall_state.get("recovery", 0)) + 1
                    status = "resolved" if fall_state["recovery"] >= 2 else "recovering"
                    attributes["recovered_at"] = ts
                else:
                    attributes = attributes if "attributes" in locals() else json.loads(event_row["attributes_json"] or "{}")
                conn.execute("UPDATE events SET status=?,confidence=?,attributes_json=?,model_call_id=?,updated_at=? WHERE id=?",
                             (status, max(float(event_row["confidence"]), observation.confidence), self.db.dumps(attributes), call_id, ts, event_id))
                conn.execute("INSERT OR IGNORE INTO event_evidence(event_id,evidence_id,role) VALUES(?,?,?)", (event_id, evidence_id, "supporting"))
                changed.append(self.event_by_id_conn(conn, event_id))
            else:
                event_id = fall_state.get("candidate_event_id")
                if event_id:
                    row = conn.execute("SELECT status,attributes_json FROM events WHERE id=?", (event_id,)).fetchone()
                    if row and row["status"] == "candidate" and int(fall_state.get("support", 0)) < 2:
                        conn.execute("UPDATE events SET status='dismissed',updated_at=? WHERE id=?", (ts, event_id))
                        changed.append(self.event_by_id_conn(conn, event_id))
                        fall_state["candidate_event_id"] = None
                        fall_state["support"] = 0
            fall_state["last_offset"] = observation.observed_at_offset_ms
            self._upsert_state_conn(conn, "fall_state", fall_state)

            hydration_state = self._state_in_conn(conn, "hydration_state", {"run_id": run_id, "event_id": None, "support": 0, "last_drink_offset": None})
            if hydration_state.get("run_id") != run_id:
                hydration_state = {"run_id": run_id, "event_id": None, "support": 0, "last_drink_offset": None}
            drinking = observation.drink_container in {"cup", "bottle", "other"} and observation.container_near_mouth and observation.drinking_motion
            if drinking:
                dedup_key = f"hydration:{self.settings.subject_id}:{run_id}"
                existing = conn.execute("SELECT id,status,attributes_json FROM events WHERE dedup_key=?", (dedup_key,)).fetchone()
                hydration_state["support"] = int(hydration_state.get("support", 0)) + 1
                hydration_state["last_drink_offset"] = observation.observed_at_offset_ms
                if existing and existing["status"] == "resolved" and not hydration_state.get("event_id"):
                    # A replayed or retried completed session is a no-op by design.
                    hydration_state = {"run_id": run_id, "event_id": None, "support": 0, "last_drink_offset": None}
                elif not hydration_state.get("event_id"):
                    event_id = make_id("evt")
                    hydration_state["event_id"] = event_id
                    if existing:
                        event_id = existing["id"]
                        hydration_state["event_id"] = event_id
                        attrs = json.loads(existing["attributes_json"] or "{}")
                    else:
                        attrs = {"session_status": "suspect", "container": observation.drink_container, "run_id": run_id, "audio": audio_attributes}
                        conn.execute("""INSERT INTO events(id,subject_id,event_type,status,occurred_at,source_offset_ms,confidence,attributes_json,model_call_id,dedup_key,schema_version,created_at,updated_at)
                                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                     (event_id, self.settings.subject_id, "hydration", "candidate", ts, observation.observed_at_offset_ms,
                                      observation.confidence, self.db.dumps(attrs), call_id, dedup_key, "event.v1", ts, ts))
                else:
                    event_id = hydration_state["event_id"]
                    row = conn.execute("SELECT attributes_json FROM events WHERE id=?", (event_id,)).fetchone()
                    attrs = json.loads(row["attributes_json"] or "{}")
                    attrs["audio"] = audio_attributes
                if hydration_state.get("event_id"):
                    row = conn.execute("SELECT status FROM events WHERE id=?", (event_id,)).fetchone()
                    status = "confirmed" if hydration_state["support"] >= 2 else row["status"]
                    attrs["session_status"] = "active" if status == "confirmed" else "suspect"
                    conn.execute("UPDATE events SET status=?,confidence=max(confidence,?),attributes_json=?,model_call_id=?,updated_at=? WHERE id=?",
                                 (status, observation.confidence, self.db.dumps(attrs), call_id, ts, event_id))
                    conn.execute("INSERT OR IGNORE INTO event_evidence(event_id,evidence_id,role) VALUES(?,?,?)", (event_id, evidence_id, "supporting"))
                    changed.append(self.event_by_id_conn(conn, event_id))
            elif hydration_state.get("event_id") and hydration_state.get("last_drink_offset") is not None:
                if observation.observed_at_offset_ms - int(hydration_state["last_drink_offset"]) >= self.settings.hydration_session_close_sec * 1000:
                    event_id = hydration_state["event_id"]
                    row = conn.execute("SELECT status,occurred_at,attributes_json FROM events WHERE id=?", (event_id,)).fetchone()
                    if row and row["status"] == "confirmed":
                        attrs = json.loads(row["attributes_json"] or "{}")
                        attrs["session_status"] = "completed"
                        conn.execute("UPDATE events SET status='resolved',ended_at=?,attributes_json=?,updated_at=? WHERE id=?", (ts, self.db.dumps(attrs), ts, event_id))
                        session_id = make_id("hyd")
                        conn.execute("""INSERT OR IGNORE INTO hydration_sessions(id,event_id,subject_id,started_at,ended_at,estimated_ml,estimation_method,estimation_confidence,created_at)
                                       VALUES(?,?,?,?,?,?,?,?,?)""",
                                     (session_id, event_id, self.settings.subject_id, row["occurred_at"], ts, self.settings.estimated_ml_per_session,
                                      "configured_serving", min(0.9, float(row["confidence"] if "confidence" in row.keys() else 0.75)), ts))
                        changed.append(self.event_by_id_conn(conn, event_id))
                    hydration_state = {"run_id": run_id, "event_id": None, "support": 0, "last_drink_offset": None}
            self._upsert_state_conn(conn, "hydration_state", hydration_state)
            transcript_text = observation.speech_transcript.strip()
            if observation.speech_detected and transcript_text:
                transcript_id = make_id("txt")
                transcript_confidence = float(observation.transcript_confidence if observation.transcript_confidence is not None else observation.audio_confidence or 0.0)
                started_at = parse_dt(ts)
                ended_at = started_at
                retention_until = (started_at + timedelta(minutes=self.settings.transcript_retention_minutes)).isoformat()
                linked_event_id = next((item.get("id") for item in reversed(changed) if item.get("event_type") in {"fall", "hydration"}), None)
                conn.execute("""INSERT INTO transcripts(id,subject_id,event_id,started_at,ended_at,text,language,confidence,retention_until,model_call_id,created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (transcript_id, self.settings.subject_id, linked_event_id,
                                                                    started_at.isoformat(), ended_at.isoformat(), transcript_text,
                                                                    "zh-TW", transcript_confidence, retention_until, call_id, ts))
                transcript = {"id": transcript_id, "subject_id": self.settings.subject_id, "event_id": linked_event_id,
                              "started_at": started_at.isoformat(), "ended_at": ended_at.isoformat(), "text": transcript_text,
                              "language": "zh-TW", "confidence": transcript_confidence, "retention_until": retention_until,
                              "model_call_id": call_id}
        return {"evidence_id": evidence_id, "model_call_id": call_id, "observation": observation_record, "events": changed, "recognition_events": recognition_events,
                "transcript": transcript, "state_tracker": tracker_snapshot}

    def _record_vision_observation_conn(self, conn, stream_id: str, window: dict[str, Any],
                                        observation: VisionObservation, model_call_id: str | None,
                                        observed_at: str) -> dict[str, Any]:
        window_id = str(window.get("window_id") or f"{stream_id}:{observed_at}")
        dedup_key = f"vision-observation:{stream_id}:{window_id}:v1"
        existing = conn.execute("SELECT * FROM vision_observations WHERE dedup_key=?", (dedup_key,)).fetchone()
        if existing:
            return row_json(dict(existing), ("observation_json",))
        observation_id = make_id("obs")
        conn.execute("""INSERT INTO vision_observations(
            id,subject_id,stream_id,window_id,start_offset_ms,end_offset_ms,observed_at,summary_text,
            warning_signal,observation_json,model_call_id,created_at,dedup_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            observation_id, self.settings.subject_id, stream_id, window_id,
            int(window.get("start_offset_ms", observation.observed_at_offset_ms)),
            int(window.get("end_offset_ms", observation.observed_at_offset_ms)), observed_at,
            observation.change_summary[:240], observation.warning_signal,
            self.db.dumps(observation.model_dump()), model_call_id, now_iso(), dedup_key,
        ))
        return row_json(dict(conn.execute("SELECT * FROM vision_observations WHERE id=?", (observation_id,)).fetchone()), ("observation_json",))

    def vision_observations(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("observation_json",)) for row in self.db.fetch_all(
            "SELECT * FROM vision_observations WHERE subject_id=? ORDER BY observed_at DESC, end_offset_ms DESC LIMIT ?",
            (self.settings.subject_id, limit))]

    @staticmethod
    def _state_in_conn(conn, key: str, default: Any) -> Any:
        row = conn.execute("SELECT value_json FROM runtime_state WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value_json"])
        except json.JSONDecodeError:
            return default

    def _upsert_state_conn(self, conn, key: str, value: Any) -> None:
            conn.execute("""INSERT INTO runtime_state(key,value_json,version,updated_at) VALUES(?,?,1,?)
                       ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,version=runtime_state.version+1,updated_at=excluded.updated_at""",
                     (key, self.db.dumps(value), now_iso()))

    @staticmethod
    def event_by_id_conn(conn, event_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return row_json(dict(row), ("attributes_json",)) if row else {}

    def _record_recognition_events_conn(self, conn, candidates: Iterable[Any], model_call_id: str, run_id: str,
                                        window_metadata: dict[str, Any], occurred_at: str) -> list[dict[str, Any]]:
        """Persist only exceptional model candidates; fall/hydration use the existing state machine."""
        recorded: list[dict[str, Any]] = []
        cooldowns = {"person_present": 60, "person_walking": 30, "person_sitting": 60, "person_lying": 30, "person_inactive": 120,
                     "door_open": 30, "door_closed": 30, "fridge_open": 30, "fridge_closed": 30, "speech_activity": 30,
                     "impact_sound": 10, "alarm_sound": 10, "smoke": 10, "fire": 10}
        for candidate in candidates:
            if candidate.event_type in {"fall", "hydration"} or candidate.confidence < 0.55:
                continue
            cooldown = cooldowns.get(candidate.event_type, 30)
            bucket = int(parse_dt(occurred_at).timestamp() // cooldown)
            label = candidate.label.strip().lower()
            dedup = f"recognition:{self.settings.subject_id}:{candidate.event_type}:{label}:{bucket}"
            attrs = {**candidate.attributes, "state": candidate.state, "evidence_frame_indexes": candidate.evidence_frame_indexes,
                     "uncertainty_reasons": candidate.uncertainty_reasons, "window": window_metadata, "run_id": run_id}
            recognition_id = make_id("rec")
            insert = conn.execute("""INSERT OR IGNORE INTO recognition_events(id,subject_id,event_type,domain,label,status,occurred_at,confidence,attributes_json,window_id,model_call_id,dedup_key,created_at,updated_at)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (recognition_id, self.settings.subject_id, candidate.event_type, candidate.domain, candidate.label, "observed", occurred_at,
                                  candidate.confidence, self.db.dumps(attrs), window_metadata.get("window_id"), model_call_id, dedup, now_iso(), now_iso()))
            row = conn.execute("SELECT * FROM recognition_events WHERE dedup_key=?", (dedup,)).fetchone()
            if insert.rowcount and row:
                recorded.append(row_json(dict(row), ("attributes_json",)))
        return recorded

    def list_events(self, event_type: str | None = None, status: str | None = None, start: str | None = None,
                    end: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if event_type:
            clauses.append("event_type=?"); params.append(event_type)
        if status:
            clauses.append("status=?"); params.append(status)
        if start:
            clauses.append("occurred_at>=?"); params.append(start)
        if end:
            clauses.append("occurred_at<=?"); params.append(end)
        where = " AND ".join(clauses)
        canonical = [row_json(row, ("attributes_json",)) for row in self.db.fetch_all(f"SELECT * FROM events WHERE {where}", tuple(params))]
        recognition_clauses, recognition_params = ["subject_id=?"], [self.settings.subject_id]
        if event_type:
            recognition_clauses.append("event_type=?"); recognition_params.append(event_type)
        if status:
            recognition_clauses.append("status=?"); recognition_params.append(status)
        if start:
            recognition_clauses.append("occurred_at>=?"); recognition_params.append(start)
        if end:
            recognition_clauses.append("occurred_at<=?"); recognition_params.append(end)
        rec_where = " AND ".join(recognition_clauses)
        recognition = []
        for row in self.db.fetch_all(f"SELECT * FROM recognition_events WHERE {rec_where}", tuple(recognition_params)):
            item = row_json(row, ("attributes_json",)); item["source"] = "recognition"; recognition.append(item)
        merged = sorted(canonical + recognition, key=lambda item: item.get("occurred_at", ""), reverse=True)
        return merged[offset:offset + limit], len(merged)

    def event_detail(self, event_id: str) -> dict | None:
        row = self.db.fetch_one("SELECT * FROM events WHERE id=? AND subject_id=?", (event_id, self.settings.subject_id))
        if not row:
            recognition = self.db.fetch_one("SELECT * FROM recognition_events WHERE id=? AND subject_id=?", (event_id, self.settings.subject_id))
            if not recognition:
                return None
            event = row_json(recognition, ("attributes_json",)); event["source"] = "recognition"; event["evidence"] = []; event["model_call"] = None; event["actions"] = []
            return event
        event = row_json(row, ("attributes_json",))
        event["evidence"] = self.db.fetch_all("""SELECT e.* , ee.role FROM evidence e JOIN event_evidence ee ON ee.evidence_id=e.id WHERE ee.event_id=? ORDER BY e.source_offset_start_ms""", (event_id,))
        event["model_call"] = self.db.fetch_one("SELECT id,provider,model,purpose,prompt_version,schema_version,status,latency_ms,error_code,response_json,created_at FROM model_calls WHERE id=?", (row["model_call_id"],)) if row["model_call_id"] else None
        if event["model_call"]:
            event["model_call"] = row_json(event["model_call"], ("response_json",))
        event["actions"] = [row_json(x, ("payload_json",)) for x in self.db.fetch_all("SELECT * FROM actions WHERE event_id=? ORDER BY created_at DESC", (event_id,))]
        return event

    def create_action(self, event_id: str, action_type: str, payload: dict, policy_version: str = "policy.v1") -> dict:
        key = f"{event_id}:{policy_version}:{action_type}"
        action = self.db.fetch_one("SELECT * FROM actions WHERE idempotency_key=?", (key,))
        if action:
            return row_json(action, ("payload_json",))
        action_id = make_id("act")
        ts = now_iso()
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO actions(id,event_id,action_type,status,policy_version,idempotency_key,payload_json,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (action_id, event_id, action_type, "triggered", policy_version, key, self.db.dumps(payload), ts, ts))
        return self.db.fetch_one("SELECT * FROM actions WHERE id=?", (action_id,)) | {"payload_json": payload}

    def add_health_scenario(self, scenario: str) -> dict:
        profiles = {
            "normal": (72, 98, 2400, "active"),
            "elevated_hr": (112, 96, 420, "inactive"),
            "low_spo2": (78, 91, 700, "resting"),
            "inactive": (68, 98, 120, "inactive"),
        }
        hr, spo2, steps, activity = profiles[scenario]
        ts = now_iso()
        samples = [("heart_rate_bpm", hr, "bpm"), ("spo2_percent", spo2, "%"), ("steps", steps, "steps")]
        with self.db.transaction() as conn:
            for metric, value, unit in samples:
                conn.execute("INSERT INTO health_samples(id,subject_id,metric,value_num,unit,measured_at,source,quality,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (make_id("health"), self.settings.subject_id, metric, value, unit, ts, "fake", "valid", ts))
            conn.execute("INSERT INTO health_samples(id,subject_id,metric,value_text,measured_at,source,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (make_id("health"), self.settings.subject_id, "activity", activity, ts, "fake", "valid", ts))
            self._upsert_state_conn(conn, "health_scenario", scenario)
        return self.health_snapshot()

    def health_snapshot(self, at: str | None = None, lookback_minutes: int = 1440) -> dict[str, Any]:
        end = parse_dt(at) if at else datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_minutes)
        rows = self.db.fetch_all("""SELECT h.* FROM health_samples h JOIN (SELECT metric, MAX(measured_at) latest FROM health_samples
                              WHERE subject_id=? AND measured_at BETWEEN ? AND ? GROUP BY metric) x ON x.metric=h.metric AND x.latest=h.measured_at
                              WHERE h.subject_id=?""", (self.settings.subject_id, start.isoformat(), end.isoformat(), self.settings.subject_id))
        result: dict[str, Any] = {"subject_id": self.settings.subject_id, "simulated": True, "quality": "missing", "measured_at": None}
        for row in rows:
            result[row["metric"]] = row["value_num"] if row["value_num"] is not None else row["value_text"]
            result["measured_at"] = max(result["measured_at"] or row["measured_at"], row["measured_at"])
            result["quality"] = row["quality"]
        return result

    def hydration_summary(self, start: str, end: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT COUNT(*) count, COALESCE(SUM(estimated_ml),0) total_ml, MAX(ended_at) last_at FROM hydration_sessions WHERE subject_id=? AND ended_at>=? AND ended_at<=?",
                                (self.settings.subject_id, start, end))
        count = int(row["count"] or 0)
        total = float(row["total_ml"] or 0)
        return {"confirmed_sessions": count, "estimated_ml": total, "target_ml": self.settings.hydration_target_ml,
                "completion_ratio": min(1.0, total / self.settings.hydration_target_ml) if self.settings.hydration_target_ml else 0,
                "last_at": row["last_at"], "coverage": {"source": "replay_or_live", "quality": "simulated"}}

    def event_summary(self, start: str, end: str) -> dict[str, Any]:
        rows = self.db.fetch_all("SELECT event_type,status,COUNT(*) count FROM events WHERE subject_id=? AND occurred_at>=? AND occurred_at<=? GROUP BY event_type,status",
                                 (self.settings.subject_id, start, end))
        summary = {"fall": {"confirmed": 0, "unresolved": 0, "resolved": 0}, "hydration": self.hydration_summary(start, end)}
        for row in rows:
            if row["event_type"] == "fall":
                if row["status"] == "confirmed": summary["fall"]["confirmed"] += row["count"]
                if row["status"] in {"candidate", "recovering"}: summary["fall"]["unresolved"] += row["count"]
                if row["status"] == "resolved": summary["fall"]["resolved"] += row["count"]
        return summary

    def add_analysis(self, summary: dict, result: dict, window_start: str, window_end: str, model_call_id: str | None, risk_level: str) -> dict:
        analysis_id = make_id("ana")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO analyses(id,subject_id,analysis_type,window_start,window_end,input_summary_json,result_json,risk_level,model_call_id,config_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (analysis_id, self.settings.subject_id, "health_risk", window_start, window_end, self.db.dumps(summary), self.db.dumps(result), risk_level, model_call_id, self.settings.config_version, now_iso()))
        row = self.db.fetch_one("SELECT * FROM analyses WHERE id=?", (analysis_id,))
        return row_json(row, ("input_summary_json", "result_json"))

    def recent_transcripts(self) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=self.settings.transcript_retention_minutes)).isoformat()
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM transcripts WHERE retention_until IS NOT NULL AND retention_until<?", (now_iso(),))
        rows = self.db.fetch_all("SELECT * FROM transcripts WHERE subject_id=? AND (retention_until IS NULL OR retention_until>=?) ORDER BY started_at DESC", (self.settings.subject_id, cutoff))
        return rows

    def add_transcript(self, text: str, started_at: datetime, duration_sec: float, confidence: float) -> dict:
        start = started_at.astimezone(timezone.utc) if started_at.tzinfo else started_at.replace(tzinfo=timezone.utc)
        end = start + timedelta(seconds=duration_sec)
        retention = end + timedelta(minutes=self.settings.transcript_retention_minutes)
        transcript_id = make_id("trn")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO transcripts(id,subject_id,started_at,ended_at,text,language,confidence,retention_until,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         (transcript_id, self.settings.subject_id, start.isoformat(), end.isoformat(), text, "zh", confidence, retention.isoformat(), now_iso()))
        return self.db.fetch_one("SELECT * FROM transcripts WHERE id=?", (transcript_id,))

    def tool_calls(self, limit: int = 100) -> list[dict]:
        return self.db.fetch_all("SELECT * FROM tool_calls ORDER BY created_at DESC LIMIT ?", (limit,))

    def record_tool_call(self, agent_name: str, tool_name: str, arguments: dict, result: dict | list | None,
                         *, event_id: str | None = None, analysis_id: str | None = None,
                         status: str = "completed", latency_ms: int | None = None) -> dict:
        key = f"{agent_name}:{tool_name}:{json_hash(arguments)}:{analysis_id or event_id or 'global'}"
        existing = self.db.fetch_one("SELECT * FROM tool_calls WHERE idempotency_key=?", (key,))
        if existing:
            return row_json(existing, ("arguments_json", "result_json"))
        call_id = make_id("tool")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO tool_calls(id,agent_name,tool_name,event_id,analysis_id,arguments_json,result_json,status,latency_ms,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (call_id, agent_name, tool_name, event_id, analysis_id, self.db.dumps(arguments), self.db.dumps(result) if result is not None else None,
                          status, latency_ms, key, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM tool_calls WHERE id=?", (call_id,)), ("arguments_json", "result_json"))

    def logs(self, limit: int = 100) -> list[dict]:
        return self.db.fetch_all("SELECT * FROM app_logs ORDER BY id DESC LIMIT ?", (limit,))

    # --- Resident Interaction Agent persistence (two driver layers) ---
    def record_resident_run(self, *, driver: str, trigger_type: str, trigger_id: str,
                            conversation_id: str | None, status: str, action: str,
                            input_json: dict[str, Any], output_json: dict[str, Any] | None = None,
                            provider: str = "", model: str = "", latency_ms: int | None = None,
                            error_code: str | None = None, dedup_key: str | None = None) -> dict:
        run_id = make_id("resrun")
        now = now_iso()
        dedup_key = dedup_key or f"{driver}:{trigger_type}:{conversation_id or 'default'}:{self.settings.config_version}"
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM resident_agent_runs WHERE dedup_key=?", (dedup_key,)).fetchone():
                return self.resident_run_by_id(conn.execute("SELECT id FROM resident_agent_runs WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()["id"])
            conn.execute("INSERT INTO resident_agent_runs(id,subject_id,conversation_id,driver,trigger_type,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, status, action,
                          self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,
                          provider, model, latency_ms, error_code, now, now, dedup_key))
        return row_json(self.db.fetch_one("SELECT * FROM resident_agent_runs WHERE id=?", (run_id,)),
                        ("input_json", "output_json"))

    def resident_run_by_id(self, run_id: str) -> dict | None:
        row = self.db.fetch_one("SELECT * FROM resident_agent_runs WHERE id=?", (run_id,))
        return row_json(row, ("input_json", "output_json")) if row else None

    def finish_resident_run(self, run_id: str, *, status: str, action: str,
                            output_json: dict[str, Any] | None = None, error_code: str | None = None,
                            latency_ms: int | None = None) -> dict | None:
        now = now_iso()
        with self.db.transaction() as conn:
            conn.execute("UPDATE resident_agent_runs SET status=?, action=?, output_json=?, error_code=?, latency_ms=?, completed_at=? WHERE id=?",
                         (status, action, self.db.dumps(output_json) if output_json is not None else None, error_code, latency_ms, now, run_id))
        return self.resident_run_by_id(run_id)

    def resident_runs(self, *, driver: str | None = None, limit: int = 100) -> list[dict]:
        where, params = ["subject_id=?"], [self.settings.subject_id]
        if driver:
            where.append("driver=?"); params.append(driver)
        sql = "SELECT * FROM resident_agent_runs WHERE " + " AND ".join(where) + f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("input_json", "output_json")) for r in self.db.fetch_all(sql, tuple(params))]

    def add_resident_message(self, *, conversation_id: str, role: str, text: str,
                             intent: str | None = None, run_id: str | None = None,
                             asr_status: str | None = None, tts_artifact_id: str | None = None) -> dict:
        msg_id = make_id("resmsg")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO resident_messages(id,subject_id,conversation_id,role,text,intent,run_id,asr_status,tts_artifact_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (msg_id, self.settings.subject_id, conversation_id, role, text, intent, run_id, asr_status, tts_artifact_id, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM resident_messages WHERE id=?", (msg_id,)), ())

    def record_resident_request(self, *, conversation_id: str, run_id: str, text: str,
                                intent: str, confidence: float, extra: dict[str, Any] | None = None) -> dict | None:
        """Record an explicit resident request in the shared event timeline.

        Ordinary conversation is deliberately excluded. The event is an
        observed interaction request, not a completed action or a clinical
        conclusion; downstream policy must decide whether anything happens.
        """
        labels = {
            "question": "使用者詢問", "reminder": "使用者要求提醒", "confirmation": "使用者要求確認",
            "clarification": "使用者要求澄清", "repeat": "使用者要求重複", "stop": "使用者要求停止",
            "forget": "使用者要求忘記／刪除", "memory_query": "使用者查詢記憶", "help": "使用者要求協助",
            "event_report": "使用者陳述事件", "preference_statement": "使用者陳述偏好",
            "schedule_reminder": "使用者設定提醒", "proactive_settings": "使用者調整主動互動設定",
        }
        if intent not in labels or not text.strip():
            return None
        occurred_at = now_iso()
        request_text = " ".join(text.split())[:1000]
        event_id = make_id("rec")
        attrs = {
            "reason": f"{labels[intent]}：{request_text}", "request_text": request_text,
            "intent": intent, "conversation_id": conversation_id, "run_id": run_id,
            "source": "resident_interaction", "action_executed": False,
        }
        if extra:
            attrs.update({key: value for key, value in extra.items() if value not in (None, "")})
        dedup_key = f"resident-request:{self.settings.subject_id}:{run_id}"
        with self.db.transaction() as conn:
            conn.execute("""INSERT OR IGNORE INTO recognition_events(
                id,subject_id,event_type,domain,label,status,occurred_at,confidence,attributes_json,
                window_id,model_call_id,dedup_key,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                event_id, self.settings.subject_id, "user_request", "resident_interaction", labels[intent],
                "observed", occurred_at, min(1.0, max(0.0, float(confidence))), self.db.dumps(attrs),
                conversation_id, None, dedup_key, occurred_at, occurred_at,
            ))
        row = self.db.fetch_one("SELECT * FROM recognition_events WHERE dedup_key=?", (dedup_key,))
        return row_json(row, ("attributes_json",)) if row else None

    def add_resident_reminder(self, *, conversation_id: str, message: str, schedule_text: str,
                              source_run_id: str) -> dict[str, Any]:
        reminder_id = make_id("rem")
        now = now_iso()
        next_trigger_at = _parse_reminder_time(schedule_text)
        dedup_key = f"resident-reminder:{self.settings.subject_id}:{source_run_id}"
        with self.db.transaction() as conn:
            conn.execute("""INSERT OR IGNORE INTO resident_reminders(
                id,subject_id,conversation_id,message,schedule_text,next_trigger_at,status,source_run_id,triggered_at,created_at,updated_at,dedup_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                reminder_id, self.settings.subject_id, conversation_id, message[:600], schedule_text[:120],
                next_trigger_at, "pending", source_run_id, None, now, now, dedup_key,
            ))
        row = self.db.fetch_one("SELECT * FROM resident_reminders WHERE dedup_key=?", (dedup_key,))
        return dict(row) if row else {}

    def resident_reminders(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        where, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            where.append("status=?"); params.append(status)
        sql = "SELECT * FROM resident_reminders WHERE " + " AND ".join(where) + f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return self.db.fetch_all(sql, tuple(params))

    def due_resident_reminders(self, *, at: str | None = None, limit: int = 20) -> list[dict]:
        now = at or now_iso()
        return self.db.fetch_all("SELECT * FROM resident_reminders WHERE subject_id=? AND status='pending' AND next_trigger_at IS NOT NULL AND next_trigger_at<=? ORDER BY next_trigger_at ASC LIMIT ?", (self.settings.subject_id, now, limit))

    def mark_resident_reminder_triggered(self, reminder_id: str) -> dict | None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE resident_reminders SET status='triggered',triggered_at=?,updated_at=? WHERE id=? AND subject_id=?", (now_iso(), now_iso(), reminder_id, self.settings.subject_id))
        return self.db.fetch_one("SELECT * FROM resident_reminders WHERE id=?", (reminder_id,))

    def resident_messages(self, *, conversation_id: str | None = None, limit: int = 200) -> list[dict]:
        where, params = ["subject_id=?"], [self.settings.subject_id]
        if conversation_id:
            where.append("conversation_id=?"); params.append(conversation_id)
        sql = "SELECT * FROM resident_messages WHERE " + " AND ".join(where) + f" ORDER BY created_at ASC LIMIT {int(limit)}"
        return self.db.fetch_all(sql, tuple(params))

    def upsert_resident_memory(self, *, memory_type: str, title: str, content: str, confidence: float,
                               requires_confirmation: bool = True, source_driver: str = "understanding",
                               source_run_id: str | None = None) -> dict:
        dedup_key = f"{source_driver}:{title}:{content[:200]}"
        existing = self.db.fetch_one("SELECT * FROM resident_memories WHERE subject_id=? AND dedup_key=?", (self.settings.subject_id, dedup_key))
        now = now_iso()
        status = "pending" if requires_confirmation else "confirmed"
        if existing:
            mem_id = existing["id"]
            with self.db.transaction() as conn:
                conn.execute("UPDATE resident_memories SET confidence=?, memory_type=?, content_text=?, status=?, requires_confirmation=?, updated_at=? WHERE id=?",
                             (confidence, memory_type, content, status, 0 if not requires_confirmation else 1, now, mem_id))
        else:
            mem_id = make_id("resmem")
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO resident_memories(id,subject_id,memory_type,title,content_text,attributes_json,confidence,status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mem_id, self.settings.subject_id, memory_type, title, content, self.db.dumps({}), confidence, status, 0 if not requires_confirmation else 1, source_driver, source_run_id, None, None, now, now, dedup_key))
        return self.resident_memory_by_id(mem_id)

    def resolve_resident_memory(self, memory_id: str, action: str) -> dict | None:
        mem = self.db.fetch_one("SELECT * FROM resident_memories WHERE id=? AND subject_id=?", (memory_id, self.settings.subject_id))
        if not mem:
            return None
        now = now_iso()
        with self.db.transaction() as conn:
            if action == "confirm":
                conn.execute("UPDATE resident_memories SET status='confirmed', requires_confirmation=0, confirmed_at=?, updated_at=? WHERE id=?", (now, now, memory_id))
            elif action == "invalidate":
                conn.execute("UPDATE resident_memories SET status='invalidated', invalidated_at=?, updated_at=? WHERE id=?", (now, now, memory_id))
        return self.resident_memory_by_id(memory_id)

    def resident_memory(self, *, status: str | None = None, source_driver: str | None = None, limit: int = 100) -> list[dict]:
        where, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            where.append("status=?"); params.append(status)
        if source_driver:
            where.append("source_driver=?"); params.append(source_driver)
        sql = "SELECT * FROM resident_memories WHERE " + " AND ".join(where) + f" ORDER BY updated_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("attributes_json",)) for r in self.db.fetch_all(sql, tuple(params))]

    def resident_memory_by_id(self, memory_id: str) -> dict | None:
        row = self.db.fetch_one("SELECT * FROM resident_memories WHERE id=?", (memory_id,))
        return row_json(row, ("attributes_json",)) if row else None

    def record_understanding_insight(self, *, run_id: str, observed_pattern: str, user_perspective: str,
                                     preference_hypotheses: list[str] | None = None, state_hypotheses: list[str] | None = None,
                                     should_initiate: bool = False, suggested_message: str = "", initiation_reasons: list[str] | None = None,
                                     confidence: float, policy_json: dict[str, Any] | None = None, status: str = "proposed") -> dict:
        ins_id = make_id("resins")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO resident_understanding_insights(id,subject_id,run_id,observed_pattern,user_perspective,preference_hypotheses_json,state_hypotheses_json,should_initiate,suggested_message,initiation_reasons_json,confidence,policy_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (ins_id, self.settings.subject_id, run_id, observed_pattern, user_perspective,
                          self.db.dumps(preference_hypotheses or []), self.db.dumps(state_hypotheses or []),
                          1 if should_initiate else 0, suggested_message, self.db.dumps(initiation_reasons or []), confidence,
                          self.db.dumps(policy_json or {}), status, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM resident_understanding_insights WHERE id=?", (ins_id,)),
                        ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))

    def understanding_insights(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        where, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            where.append("status=?"); params.append(status)
        sql = "SELECT * FROM resident_understanding_insights WHERE " + " AND ".join(where) + f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))
                for r in self.db.fetch_all(sql, tuple(params))]

    def _frigate_decision(self, detections: list[dict[str, Any]], explicit: bool | None = None) -> tuple[bool, str]:
        if explicit is not None:
            return explicit, "frigate_explicit_decision"
        labels = {str(d.get("label", "")).lower() for d in detections}
        if labels.intersection(self.settings.frigate_noteworthy_labels):
            return True, "label_policy:" + ",".join(sorted(labels.intersection(self.settings.frigate_noteworthy_labels)))
        if self.settings.frigate_noteworthy_zones:
            for detection in detections:
                zones = {str(x).lower() for x in detection.get("zones", [])}
                if zones.intersection(self.settings.frigate_noteworthy_zones) and float(detection.get("score", 0)) >= 0.5:
                    return True, "zone_policy:" + ",".join(sorted(zones.intersection(self.settings.frigate_noteworthy_zones)))
        return False, "no_noteworthy_detection"

    def record_frigate_event(self, *, frigate_event_id: str, camera_id: str, update_type: str, label: str,
                             zones: list[str], received_at: str, snapshot_uri: str | None = None,
                             clip_uri: str | None = None, score: float | None = None,
                             explicit_noteworthy: bool | None = None) -> dict[str, Any]:
        detection = {"label": label, "score": score, "zones": zones, "snapshot_available": bool(snapshot_uri), "clip_available": bool(clip_uri)}
        noteworthy, reason = self._frigate_decision([detection], explicit_noteworthy)
        excerpt = f"[{('NOTEWORTHY' if noteworthy else 'ignored')}] camera={camera_id} label={label}"
        if score is not None:
            excerpt += f" score={score:.2f}"
        if zones:
            excerpt += f" zones={','.join(zones)}"
        excerpt += f" event={frigate_event_id} update={update_type} reason={reason}"
        log_id = make_id("frigate")
        with self.db.transaction() as conn:
            insert = conn.execute("""INSERT OR IGNORE INTO frigate_log_snippets(id,camera_id,frigate_event_id,update_type,received_at,labels_json,detections_json,noteworthy,reason,decision_source,log_excerpt,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (log_id, camera_id, frigate_event_id, update_type, received_at, self.db.dumps([label]), self.db.dumps([detection]), int(noteworthy), reason,
                                  "frigate_event_policy", excerpt, now_iso()))
            row = conn.execute("SELECT * FROM frigate_log_snippets WHERE frigate_event_id=? AND update_type=? AND camera_id=?", (frigate_event_id, update_type, camera_id)).fetchone()
            if insert.rowcount:
                conn.execute("INSERT INTO app_logs(ts,level,component,message,context_json) VALUES(?,?,?,?,?)",
                             (received_at, "warning" if noteworthy else "info", "frigate", "Frigate noteworthy detection" if noteworthy else "Frigate event ignored", self.db.dumps({"snippet_id": row["id"], "noteworthy": noteworthy, "log_excerpt": row["log_excerpt"]})))
        return row_json(dict(row), ("labels_json", "detections_json"))

    def record_frame_log(self, *, camera_id: str, received_at: str, frame_sha256: str, width: int | None,
                         height: int | None, detections: list[dict[str, Any]], decision_source: str,
                         explicit_noteworthy: bool | None = None, reason_override: str | None = None) -> dict[str, Any]:
        noteworthy, reason = self._frigate_decision(detections, explicit_noteworthy)
        if reason_override:
            reason = reason_override
        labels = sorted({str(d.get("label", "")).lower() for d in detections if d.get("label")})
        excerpt = f"[{('NOTEWORTHY' if noteworthy else 'ignored')}] camera={camera_id} frame_sha256={frame_sha256[:16]} labels={','.join(labels) or 'none'} reason={reason}"
        log_id = make_id("frigate")
        with self.db.transaction() as conn:
            conn.execute("""INSERT INTO frigate_log_snippets(id,camera_id,received_at,frame_sha256,width,height,labels_json,detections_json,noteworthy,reason,decision_source,log_excerpt,created_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (log_id, camera_id, received_at, frame_sha256, width, height, self.db.dumps(labels), self.db.dumps(detections), int(noteworthy), reason, decision_source, excerpt, now_iso()))
            conn.execute("INSERT INTO app_logs(ts,level,component,message,context_json) VALUES(?,?,?,?,?)",
                         (received_at, "warning" if noteworthy else "info", "frigate", "Frigate frame noteworthy" if noteworthy else "Frigate frame received", self.db.dumps({"snippet_id": log_id, "noteworthy": noteworthy, "decision_source": decision_source, "log_excerpt": excerpt})))
        return row_json(self.db.fetch_one("SELECT * FROM frigate_log_snippets WHERE id=?", (log_id,)), ("labels_json", "detections_json"))

    def frigate_logs(self, noteworthy_only: bool = False, limit: int = 100) -> list[dict]:
        if noteworthy_only:
            rows = self.db.fetch_all("SELECT * FROM frigate_log_snippets WHERE noteworthy=1 ORDER BY received_at DESC LIMIT ?", (limit,))
        else:
            rows = self.db.fetch_all("SELECT * FROM frigate_log_snippets ORDER BY received_at DESC LIMIT ?", (limit,))
        return [row_json(row, ("labels_json", "detections_json")) for row in rows]

    def recognition_logs(self, limit: int = 100) -> list[dict]:
        """Return one compact feed for the dashboard while Frigate is bypassed."""
        logs = self.frigate_logs(False, limit)
        transition_rows = self.db.fetch_all("""SELECT id,event_type,status,occurred_at,confidence,attributes_json,window_id
                                  FROM recognition_events
                                  WHERE subject_id=? AND event_type IN ('person_stood_up','person_sat_down','person_lay_down','person_got_up')
                                  ORDER BY occurred_at DESC LIMIT ?""", (self.settings.subject_id, limit))
        for row in transition_rows:
            try:
                attrs = json.loads(row["attributes_json"] or "{}")
            except json.JSONDecodeError:
                attrs = {}
            logs.append({"id": row["id"], "camera_id": "vllm", "received_at": row["occurred_at"],
                         "noteworthy": 1, "reason": "temporal_posture_state_tracker", "decision_source": "state_tracker",
                         "labels_json": [row["event_type"]], "detections_json": [], "status": row["status"],
                         "event_type": row["event_type"], "source_offset_ms": attrs.get("occurred_offset_ms"),
                         "log_excerpt": f"[EVENT] {row['event_type']} {attrs.get('from_state', '?')} → {attrs.get('to_state', '?')} "
                                        f"occurred_offset_ms={attrs.get('occurred_offset_ms', 'n/a')} confirmed_offset_ms={attrs.get('confirmed_offset_ms', 'n/a')} "
                                        f"confidence={float(row['confidence']):.2f} status={row['status']}"})
        rows = self.db.fetch_all("""SELECT id,model,status,latency_ms,response_json,created_at
                                  FROM model_calls WHERE purpose='vision_events'
                                  ORDER BY created_at DESC LIMIT ?""", (limit,))
        for row in rows:
            try:
                observation = json.loads(row["response_json"] or "{}")
            except json.JSONDecodeError:
                observation = {}
            logs.append({"id": f"vlm_{row['id']}", "camera_id": "vllm", "received_at": row["created_at"], "noteworthy": 0,
                         "reason": "vision_observation", "decision_source": "local_vllm", "labels_json": [observation.get("posture", "unknown")],
                         "detections_json": [], "log_excerpt": f"[VLM] model={row['model']} person={observation.get('person_visible', 'unknown')} posture={observation.get('posture', 'unknown')} transition={observation.get('vertical_transition', 'unknown')} audio={observation.get('audio_present', False)} sounds={','.join(observation.get('audio_events', [])) or 'none'} emotion={observation.get('speaker_emotion', 'unknown')} confidence={observation.get('confidence', 'unknown')} status={row['status']} latency_ms={row.get('latency_ms') or 'n/a'}"})
        return sorted(logs, key=lambda item: item.get("received_at", ""), reverse=True)[:limit]

    def observer_run(self, end_date: date | None = None) -> dict[str, Any]:
        target = end_date or datetime.now().date()
        summaries = []
        for days_ago in range(30, -1, -1):
            day = target - timedelta(days=days_ago)
            start = datetime.combine(day, time.min, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            event_counts = self.event_summary(start.isoformat(), end.isoformat())
            health_rows = self.db.fetch_all("SELECT metric,MIN(value_num) min_value,MAX(value_num) max_value,AVG(value_num) avg_value FROM health_samples WHERE subject_id=? AND measured_at>=? AND measured_at<? AND value_num IS NOT NULL GROUP BY metric",
                                            (self.settings.subject_id, start.isoformat(), end.isoformat()))
            health = {r["metric"]: {"min": r["min_value"], "max": r["max_value"], "avg": r["avg_value"]} for r in health_rows}
            coverage = {"health_samples": min(1.0, sum(1 for _ in health_rows) / 3), "camera": 1.0 if event_counts["fall"]["confirmed"] or event_counts["hydration"]["confirmed_sessions"] else 0.5}
            hydration = event_counts["hydration"]
            payload = (event_counts, hydration, health, coverage)
            with self.db.transaction() as conn:
                conn.execute("""INSERT OR REPLACE INTO daily_summaries(subject_id,summary_date,event_counts_json,hydration_json,health_json,coverage_json,config_version,created_at)
                               VALUES(?,?,?,?,?,?,?,?)""", (self.settings.subject_id, day.isoformat(), self.db.dumps(event_counts["fall"]), self.db.dumps(hydration), self.db.dumps(health), self.db.dumps(coverage), self.settings.config_version, now_iso()))
            summaries.append({"summary_date": day.isoformat(), "event_counts": event_counts["fall"], "hydration": hydration, "health": health, "coverage": coverage})
        current = summaries[-1]
        previous = [s for s in summaries[:-1] if s["coverage"]["health_samples"] > 0]
        baseline_ml = sum(s["hydration"]["estimated_ml"] for s in previous[-7:]) / max(1, len(previous[-7:]))
        finding = None
        if previous and current["hydration"]["estimated_ml"] < baseline_ml * 0.75:
            statement = f"近期估算飲水量為 {current['hydration']['estimated_ml']:.0f} ml，低於近 7 日個人基準 {baseline_ml:.0f} ml；此為待觀察行為變化，非醫療診斷。"
            evidence = {"baseline_days": [s["summary_date"] for s in previous[-7:]], "current": current, "baseline_ml": baseline_ml}
            existing = self.db.fetch_one("SELECT * FROM observer_findings WHERE subject_id=? AND finding_type=? AND window_end=?", (self.settings.subject_id, "hydration_decline", target.isoformat()))
            if existing:
                finding = row_json(existing, ("evidence_json",))
            else:
                finding_id = make_id("finding")
                with self.db.transaction() as conn:
                    conn.execute("INSERT INTO observer_findings(id,subject_id,window_start,window_end,finding_type,statement,evidence_json,confidence,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                 (finding_id, self.settings.subject_id, (target - timedelta(days=30)).isoformat(), target.isoformat(), "hydration_decline", statement, self.db.dumps(evidence), 0.72, "proposed", now_iso()))
                finding = row_json(self.db.fetch_one("SELECT * FROM observer_findings WHERE id=?", (finding_id,)), ("evidence_json",))
        return {"summaries": summaries, "finding": finding, "baseline": {"estimated_ml_7d": baseline_ml, "window_days": 30}}

    def list_findings(self, limit: int = 50) -> list[dict]:
        return [row_json(row, ("evidence_json",)) for row in self.db.fetch_all("SELECT * FROM observer_findings WHERE subject_id=? ORDER BY window_end DESC LIMIT ?", (self.settings.subject_id, limit))]

    def seed_history(self, days: int = 30) -> dict[str, Any]:
        created = 0
        today = datetime.now(timezone.utc).date()
        with self.db.transaction() as conn:
            for days_ago in range(days, 0, -1):
                day = today - timedelta(days=days_ago)
                ts = datetime.combine(day, time(hour=12), tzinfo=timezone.utc).isoformat()
                for metric, value, unit in (("heart_rate_bpm", 70 + (days_ago % 5), "bpm"), ("spo2_percent", 98, "%"), ("steps", 1800 + days_ago * 10, "steps")):
                    conn.execute("INSERT INTO health_samples(id,subject_id,metric,value_num,unit,measured_at,source,quality,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                 (make_id("health"), self.settings.subject_id, metric, value, unit, ts, "fake_seed", "valid", now_iso()))
                if days_ago > 7:
                    continue
                start = datetime.combine(day, time(hour=9), tzinfo=timezone.utc).isoformat()
                end = datetime.combine(day, time(hour=9, minute=1), tzinfo=timezone.utc).isoformat()
                dedup = f"seed-hydration:{self.settings.subject_id}:{day.isoformat()}"
                existing = conn.execute("SELECT id FROM events WHERE dedup_key=?", (dedup,)).fetchone()
                event_id = existing["id"] if existing else make_id("evt")
                if not existing:
                    conn.execute("INSERT INTO events(id,subject_id,event_type,status,occurred_at,ended_at,confidence,attributes_json,dedup_key,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                 (event_id, self.settings.subject_id, "hydration", "resolved", start, end, 0.86, self.db.dumps({"session_status": "completed", "seed": True}), dedup, "event.v1", start, end))
                    conn.execute("INSERT OR IGNORE INTO hydration_sessions(id,event_id,subject_id,started_at,ended_at,estimated_ml,estimation_method,estimation_confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (make_id("hyd"), event_id, self.settings.subject_id, start, end, 400 if days_ago > 2 else 200, "configured_serving", 0.8, now_iso()))
                if not existing:
                    created += 1
        return {"health_days": days, "hydration_sessions": created}

    def setup_status(self) -> dict[str, Any]:
        return {"completed": bool(self.get_state("setup_completed", False)), "config_version": self.settings.config_version,
                "steps": {"runtime": True, "vision_model": self.settings.local_vlm_mode in {"vllm", "real"}, "main_agent": self.settings.main_agent_enabled and self.settings.local_vlm_mode in {"vllm", "real"}, "speech_model": False,
                           "frigate": bool(self.settings.active_source == "replay" or self.settings.active_source == "simulated"),
                           "minimax": self.settings.minimax_configured, "telegram": self.settings.telegram_configured}}
