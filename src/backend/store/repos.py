"""Repositories over the schema (docs/02_DATA_AND_POLICY.md).

One facade rather than a class per table: the interesting logic in this
system lives in the cascade and the state machines, and a dozen
near-identical repository classes would add ceremony without adding a
single guarantee. What *is* worth isolating is here — dedup on event
identity, the JSON column boundary, and the daily rollups.
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.enums import EventStatus, EventType
from ..domain.ids import new_id
from ..domain.model_call import ModelCall
from ..domain.pipeline_run import PipelineRun
from ..domain.timeutil import day_key, iso, now_ms
from .db import Database


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _row(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class Repositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- model calls -----------------------------------------------------

    def save_model_call(self, call: ModelCall) -> str:
        self.db.execute(
            """INSERT OR REPLACE INTO model_calls
               (call_id, layer, provider, model, purpose, prompt_version, schema_version,
                status, latency_ms, prompt_tokens, output_tokens, total_tokens, attempts,
                error_code, error_message, input_hash, response_text, evidence_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.call_id, call.layer, call.provider, call.model, call.purpose,
                call.prompt_version, call.schema_version, call.status, call.latency_ms,
                call.prompt_tokens, call.output_tokens, call.total_tokens, call.attempts,
                call.error_code, call.error_message, call.input_hash, call.response_text,
                call.evidence_id, call.created_at,
            ),
        )
        return call.call_id

    def recent_model_calls(self, layer: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if layer:
            rows = self.db.query(
                "SELECT * FROM model_calls WHERE layer=? ORDER BY created_at DESC LIMIT ?",
                (layer, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM model_calls ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]

    # -- evidence --------------------------------------------------------

    def save_evidence(
        self,
        subject_id: str,
        kind: str,
        uri: str | None,
        mime_type: str | None,
        started_at_ms: int,
        duration_sec: float = 0.0,
        frame_count: int = 0,
        size_bytes: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        evidence_id = new_id("ev")
        self.db.execute(
            """INSERT INTO evidence
               (evidence_id, subject_id, kind, uri, mime_type, started_at_ms,
                duration_sec, frame_count, size_bytes, metadata_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (evidence_id, subject_id, kind, uri, mime_type, started_at_ms,
             duration_sec, frame_count, size_bytes, _json(metadata or {}), iso()),
        )
        return evidence_id

    # -- observation history --------------------------------------------

    def save_observation(self, run_id: str, subject_id: str, observed_at_ms: int,
                         summary: str, confidence: float,
                         payload: dict[str, Any]) -> str:
        observation_id = new_id("obs")
        self.db.execute(
            """INSERT OR REPLACE INTO observations
               (observation_id, run_id, subject_id, observed_at_ms, summary,
                confidence, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (observation_id, run_id, subject_id, observed_at_ms, summary[:1200],
             max(0.0, min(1.0, float(confidence))), _json(payload), iso()),
        )
        return observation_id

    def list_observations(self, subject_id: str, limit: int = 12) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM observations WHERE subject_id=? "
            "ORDER BY observed_at_ms DESC, created_at DESC LIMIT ?",
            (subject_id, limit),
        )
        out = []
        for row in rows:
            item = _row(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                item["payload"] = {}
            out.append(item)
        return out

    # -- pipeline runs ---------------------------------------------------

    def save_run(self, run: PipelineRun) -> str:
        placeholders = ",".join("?" for _ in range(34))
        self.db.execute(
            f"""INSERT OR REPLACE INTO pipeline_runs
               (run_id, subject_id, window_started_at_ms, window_ended_at_ms, config_version,
                l1_decision, l1_confidence, l1_detector_id, l1_latency_ms, l1_health,
                l2_outcome, l2_reason, l2_model, l2_call_id, l2_latency_ms, l2_repaired,
                l2_escalation_required, l2_escalation_reasons, l2_error,
                l3_outcome, l3_reason, l3_model, l3_call_id, l3_latency_ms, l3_risk_level, l3_error,
                evidence_id, clip_path, change_detected, change_score, change_reasons,
                event_ids, action_ids, created_at)
               VALUES ({placeholders})""",
            (
                run.run_id, run.subject_id, run.window_started_at_ms, run.window_ended_at_ms,
                run.config_version,
                run.l1_decision, run.l1_confidence, run.l1_detector_id, run.l1_latency_ms, run.l1_health,
                run.l2_outcome, run.l2_reason, run.l2_model, run.l2_call_id, run.l2_latency_ms,
                int(run.l2_repaired), int(run.l2_escalation_required),
                _json(run.l2_escalation_reasons), run.l2_error,
                run.l3_outcome, run.l3_reason, run.l3_model, run.l3_call_id, run.l3_latency_ms,
                run.l3_risk_level, run.l3_error,
                run.evidence_id, run.clip_path, int(run.change_detected), run.change_score,
                _json(run.change_reasons), _json(run.event_ids), _json(run.action_ids),
                run.created_at,
            ),
        )
        for event_id in run.event_ids:
            self.db.execute(
                "INSERT OR IGNORE INTO event_runs(event_id, run_id) VALUES (?,?)",
                (event_id, run.run_id),
            )
        return run.run_id

    def list_runs(self, limit: int = 50, offset: int = 0,
                  l2_outcome: str | None = None) -> list[dict[str, Any]]:
        clause, params = "", []
        if l2_outcome:
            clause = "WHERE l2_outcome = ?"
            params.append(l2_outcome)
        rows = self.db.query(
            # Ordered by when the window *closed*: a skipped window is
            # stamped at the decision instant while a processed one starts
            # a full span earlier, so ordering by the start interleaves them.
            f"SELECT * FROM pipeline_runs {clause} "
            "ORDER BY window_ended_at_ms DESC, created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return [self._decode_run(_row(r)) for r in rows]

    def runs_for_event(self, event_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT p.* FROM pipeline_runs p JOIN event_runs e ON e.run_id = p.run_id "
            "WHERE e.event_id = ? ORDER BY p.window_started_at_ms ASC",
            (event_id,),
        )
        return [self._decode_run(_row(r)) for r in rows]

    @staticmethod
    def _decode_run(row: dict[str, Any]) -> dict[str, Any]:
        for column in ("l2_escalation_reasons", "change_reasons", "event_ids", "action_ids"):
            try:
                row[column] = json.loads(row.get(column) or "[]")
            except json.JSONDecodeError:
                row[column] = []
        row["l2_repaired"] = bool(row.get("l2_repaired"))
        row["l2_escalation_required"] = bool(row.get("l2_escalation_required"))
        row["change_detected"] = bool(row.get("change_detected", 1))
        return row

    def run_stats(self, since_ms: int) -> dict[str, Any]:
        """The counters the Dashboard's three-layer panel renders (docs/03_API_AND_FRONTEND.md)."""
        row = self.db.query_one(
            """SELECT
                 COUNT(*)                                                        AS windows,
                 SUM(l2_outcome = 'skipped_l1')                                  AS skipped_by_l1,
                 SUM(l2_outcome IN ('called','heartbeat','forced_high_risk'))     AS l2_calls,
                 SUM(l2_outcome = 'heartbeat')                                   AS heartbeats,
                 SUM(l2_outcome = 'forced_high_risk')                            AS forced,
                 SUM(l2_outcome = 'failed')                                      AS l2_failures,
                 SUM(l2_escalation_required)                                     AS escalations,
                 SUM(l3_outcome IN ('called','degraded_text_only'))              AS l3_calls,
                 SUM(l3_outcome = 'degraded_text_only')                          AS l3_degraded,
                 SUM(l3_outcome = 'failed')                                      AS l3_failures,
                 AVG(NULLIF(l2_latency_ms, 0))                                   AS l2_latency_avg,
                 MAX(l2_latency_ms)                                              AS l2_latency_max,
                 AVG(NULLIF(l3_latency_ms, 0))                                   AS l3_latency_avg
               FROM pipeline_runs WHERE window_started_at_ms >= ?""",
            (since_ms,),
        )
        stats = {k: (v or 0) for k, v in _row(row).items()}
        windows = stats.get("windows", 0)
        stats["skip_ratio"] = round(stats.get("skipped_by_l1", 0) / windows, 4) if windows else 0.0
        return stats

    # -- events ----------------------------------------------------------

    def upsert_event(
        self,
        subject_id: str,
        event_type: EventType,
        status: EventStatus,
        dedup_key: str,
        occurred_at_ms: int,
        confidence: float,
        attributes: dict[str, Any],
        schema_version: str,
        ended_at_ms: int | None = None,
    ) -> tuple[str, bool]:
        """Insert or update by ``dedup_key``. Returns ``(event_id, created)``.

        Replaying the same footage must not create a second event
        (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 11), so identity is the dedup key, never the row id.
        """
        existing = self.db.query_one("SELECT event_id FROM events WHERE dedup_key = ?", (dedup_key,))
        stamp = now_ms()
        if existing is not None:
            event_id = existing["event_id"]
            self.db.execute(
                """UPDATE events SET status=?, updated_at_ms=?, ended_at_ms=?,
                       confidence=?, attributes_json=? WHERE event_id=?""",
                (status.value, stamp, ended_at_ms, confidence, _json(attributes), event_id),
            )
            return event_id, False

        event_id = new_id("evt")
        self.db.execute(
            """INSERT INTO events
               (event_id, subject_id, event_type, status, occurred_at_ms, updated_at_ms,
                ended_at_ms, confidence, attributes_json, dedup_key, schema_version, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (event_id, subject_id, event_type.value, status.value, occurred_at_ms, stamp,
             ended_at_ms, confidence, _json(attributes), dedup_key, schema_version, iso()),
        )
        return event_id, True

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM events WHERE event_id = ?", (event_id,))
        if row is None:
            return None
        event = _row(row)
        event["attributes"] = json.loads(event.pop("attributes_json") or "{}")
        return event

    def list_events(self, limit: int = 50, event_type: str | None = None,
                    status: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.db.query(
            f"SELECT * FROM events {where} ORDER BY occurred_at_ms DESC LIMIT ?", (*params, limit)
        )
        out = []
        for row in rows:
            event = _row(row)
            event["attributes"] = json.loads(event.pop("attributes_json") or "{}")
            out.append(event)
        return out

    def open_event(self, subject_id: str, event_type: EventType) -> dict[str, Any] | None:
        """The event currently being tracked for this type, if any."""
        terminal = ("resolved", "completed", "dismissed", "idle")
        placeholders = ",".join("?" for _ in terminal)
        row = self.db.query_one(
            f"""SELECT * FROM events WHERE subject_id=? AND event_type=?
                AND status NOT IN ({placeholders})
                ORDER BY occurred_at_ms DESC LIMIT 1""",
            (subject_id, event_type.value, *terminal),
        )
        if row is None:
            return None
        event = _row(row)
        event["attributes"] = json.loads(event.pop("attributes_json") or "{}")
        return event

    # -- hydration -------------------------------------------------------

    def save_hydration_session(self, event_id: str, subject_id: str, started_at_ms: int,
                               ended_at_ms: int, estimated_ml: float) -> str:
        session_id = new_id("hyd")
        self.db.execute(
            """INSERT OR IGNORE INTO hydration_sessions
               (session_id, event_id, subject_id, started_at_ms, ended_at_ms,
                estimated_ml, method, day_key, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (session_id, event_id, subject_id, started_at_ms, ended_at_ms, estimated_ml,
             "fixed_container_volume", day_key(ended_at_ms), iso()),
        )
        return session_id

    def hydration_summary(self, day: str | None = None) -> dict[str, Any]:
        target = day or day_key()
        row = self.db.query_one(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(estimated_ml),0) AS total_ml,
                      MAX(ended_at_ms) AS last_at_ms
               FROM hydration_sessions WHERE day_key = ?""",
            (target,),
        )
        return {"day": target, **{k: (v or 0) for k, v in _row(row).items()}}

    # -- analyses / actions ----------------------------------------------

    def save_analysis(self, event_id: str | None, run_id: str | None, call_id: str | None,
                      trigger: str, reason_codes: list[str], degraded: bool,
                      payload: dict[str, Any]) -> str:
        analysis_id = new_id("ana")
        self.db.execute(
            """INSERT INTO analyses
               (analysis_id, event_id, run_id, call_id, trigger, reason_codes, degraded,
                risk_level, recommendation, supports_l2, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (analysis_id, event_id, run_id, call_id, trigger, _json(reason_codes), int(degraded),
             payload.get("risk_level"), payload.get("recommendation"),
             int(payload.get("supports_l2", True)), _json(payload), iso()),
        )
        return analysis_id

    def save_action(self, decision: Any, run_id: str | None) -> str:
        self.db.execute(
            """INSERT INTO actions
               (action_id, event_id, run_id, kind, rule, reason, severity,
                suppressed, suppressed_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (decision.action_id, decision.event_id or None, run_id, decision.kind.value,
             decision.rule, decision.reason, decision.severity, int(decision.suppressed),
             decision.suppressed_reason, iso()),
        )
        return decision.action_id

    def list_actions(self, limit: int = 50) -> list[dict[str, Any]]:
        return [_row(r) for r in
                self.db.query("SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,))]

    def last_notification_ms(self, subject_id: str) -> int | None:
        row = self.db.query_one(
            """SELECT a.created_at FROM actions a
               WHERE a.kind = 'notify_telegram' AND a.suppressed = 0
               ORDER BY a.created_at DESC LIMIT 1"""
        )
        if row is None:
            return None
        from ..domain.timeutil import parse_iso

        try:
            return parse_iso(row["created_at"])
        except ValueError:
            return None

    # -- notifications ---------------------------------------------------

    def save_delivery(self, action_id: str, recipient: str, callback_token: str,
                      channel: str = "telegram") -> str:
        delivery_id = new_id("dlv")
        self.db.execute(
            """INSERT INTO notification_deliveries
               (delivery_id, action_id, channel, recipient, status, callback_token, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (delivery_id, action_id, channel, recipient, "pending", callback_token, iso()),
        )
        return delivery_id

    def update_delivery(self, delivery_id: str, status: str, provider_msg_id: str | None = None,
                        error: str | None = None) -> None:
        column = "sent_at" if status == "sent" else "responded_at"
        self.db.execute(
            f"""UPDATE notification_deliveries
                SET status=?, provider_msg_id=COALESCE(?, provider_msg_id),
                    error=?, {column}=? WHERE delivery_id=?""",
            (status, provider_msg_id, error, iso(), delivery_id),
        )

    def delivery_by_token(self, token: str) -> dict[str, Any] | None:
        return _row(self.db.query_one(
            "SELECT * FROM notification_deliveries WHERE callback_token = ?", (token,)
        )) or None

    # -- health / transcripts --------------------------------------------

    def save_health_sample(self, subject_id: str, metric: str, value: float,
                           unit: str, source: str, observed_at_ms: int) -> str:
        sample_id = new_id("hs")
        self.db.execute(
            """INSERT INTO health_samples
               (sample_id, subject_id, metric, value, unit, source, observed_at_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (sample_id, subject_id, metric, value, unit, source, observed_at_ms, iso()),
        )
        return sample_id

    def latest_health(self, subject_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT metric, value, unit, source, MAX(observed_at_ms) AS observed_at_ms
               FROM health_samples WHERE subject_id = ? GROUP BY metric""",
            (subject_id,),
        )
        return [_row(r) for r in rows]

    def save_transcript(self, subject_id: str, text: str, started_at_ms: int,
                        ended_at_ms: int, confidence: float, ttl_sec: int) -> str:
        transcript_id = new_id("tr")
        self.db.execute(
            """INSERT INTO transcripts
               (transcript_id, subject_id, text, started_at_ms, ended_at_ms,
                confidence, expires_at_ms, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (transcript_id, subject_id, text, started_at_ms, ended_at_ms, confidence,
             ended_at_ms + ttl_sec * 1000, iso()),
        )
        return transcript_id

    def recent_transcript(self, subject_id: str, since_ms: int) -> str:
        rows = self.db.query(
            """SELECT text FROM transcripts WHERE subject_id=? AND ended_at_ms >= ?
               AND expires_at_ms > ? ORDER BY started_at_ms ASC""",
            (subject_id, since_ms, now_ms()),
        )
        return " ".join(r["text"] for r in rows)

    def sweep_transcripts(self) -> int:
        return self.db.execute("DELETE FROM transcripts WHERE expires_at_ms <= ?", (now_ms(),))

    # -- observer --------------------------------------------------------

    def upsert_daily_summary(self, day: str, subject_id: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            """INSERT INTO daily_summaries
                 (day_key, subject_id, hydration_ml, hydration_sessions, fall_events,
                  l2_calls, l2_skipped, l3_calls, coverage_ratio, payload_json,
                  created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(day_key) DO UPDATE SET
                 hydration_ml=excluded.hydration_ml,
                 hydration_sessions=excluded.hydration_sessions,
                 fall_events=excluded.fall_events,
                 l2_calls=excluded.l2_calls, l2_skipped=excluded.l2_skipped,
                 l3_calls=excluded.l3_calls, coverage_ratio=excluded.coverage_ratio,
                 payload_json=excluded.payload_json, updated_at=excluded.updated_at""",
            (day, subject_id, payload.get("hydration_ml", 0), payload.get("hydration_sessions", 0),
             payload.get("fall_events", 0), payload.get("l2_calls", 0), payload.get("l2_skipped", 0),
             payload.get("l3_calls", 0), payload.get("coverage_ratio", 0.0), _json(payload),
             iso(), iso()),
        )

    def daily_summaries(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = [_row(r) for r in self.db.query(
            "SELECT * FROM daily_summaries ORDER BY day_key DESC LIMIT ?", (limit,))]
        for row in rows:
            try:
                row["payload"] = json.loads(row.pop("payload_json") or "{}")
            except json.JSONDecodeError:
                row["payload"] = {}
        return rows

    def save_finding(self, subject_id: str, day: str, kind: str, headline: str,
                     detail: str, severity: str, call_id: str | None,
                     payload: dict[str, Any]) -> str:
        finding_id = new_id("fnd")
        self.db.execute(
            """INSERT INTO observer_findings
               (finding_id, subject_id, day_key, kind, headline, detail, severity,
                call_id, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (finding_id, subject_id, day, kind, headline, detail, severity, call_id,
             _json(payload), iso()),
        )
        return finding_id

    def list_findings(self, limit: int = 30) -> list[dict[str, Any]]:
        return [_row(r) for r in self.db.query(
            "SELECT * FROM observer_findings ORDER BY created_at DESC LIMIT ?", (limit,))]

    def save_observer_run(self, subject_id: str, window_started_at_ms: int,
                          window_ended_at_ms: int, status: str, headline: str,
                          detail: str, confidence: float, data_completeness: float,
                          mode: str, call_id: str | None, metrics: dict[str, Any],
                          anomaly_codes: list[str]) -> str:
        run_id = new_id("obs")
        self.db.execute(
            """INSERT INTO observer_runs
               (observer_run_id, subject_id, window_started_at_ms, window_ended_at_ms,
                status, headline, detail, confidence, data_completeness, mode, call_id,
                metrics_json, anomaly_codes_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, subject_id, window_started_at_ms, window_ended_at_ms, status,
             headline, detail, max(0.0, min(1.0, confidence)),
             max(0.0, min(1.0, data_completeness)), mode, call_id,
             _json(metrics), _json(anomaly_codes), iso()),
        )
        return run_id

    def list_observer_runs(self, subject_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = [_row(r) for r in self.db.query(
            "SELECT * FROM observer_runs WHERE subject_id=? "
            "ORDER BY window_ended_at_ms DESC LIMIT ?", (subject_id, limit))]
        for row in rows:
            for source, target, fallback in (
                ("metrics_json", "metrics", {}),
                ("anomaly_codes_json", "anomaly_codes", []),
            ):
                try:
                    row[target] = json.loads(row.pop(source) or _json(fallback))
                except json.JSONDecodeError:
                    row[target] = fallback
        return rows

    def observer_status_counts(self, subject_id: str, since_ms: int) -> dict[str, int]:
        rows = self.db.query(
            "SELECT status, COUNT(*) AS n FROM observer_runs "
            "WHERE subject_id=? AND window_ended_at_ms>=? GROUP BY status",
            (subject_id, since_ms),
        )
        return {str(row["status"]): int(row["n"]) for row in rows}
    # -- original Longcare flow: agent / memory / interaction ------------

    def save_agent_run(self, subject_id: str, agent_name: str, trigger_type: str,
                       trigger_id: str | None, window_id: str | None,
                       input_context: dict[str, Any], dedup_key: str,
                       provider: str = "local_vllm", model: str = "",
                       status: str = "running") -> tuple[str, bool]:
        existing = self.db.query_one(
            "SELECT agent_run_id, status FROM agent_runs WHERE dedup_key=?", (dedup_key,))
        if existing is not None:
            return str(existing["agent_run_id"]), False
        agent_run_id = new_id("agent")
        self.db.execute(
            """INSERT INTO agent_runs
               (agent_run_id, subject_id, agent_name, trigger_type, trigger_id,
                window_id, status, input_context_json, provider, model,
                dedup_key, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (agent_run_id, subject_id, agent_name, trigger_type, trigger_id,
             window_id, status, _json(input_context), provider, model,
             dedup_key, iso()),
        )
        return agent_run_id, True

    def finish_agent_run(self, agent_run_id: str, status: str,
                         output: dict[str, Any] | None = None,
                         error_code: str | None = None,
                         latency_ms: int | None = None) -> None:
        self.db.execute(
            """UPDATE agent_runs SET status=?, output_json=?, error_code=?,
               latency_ms=?, completed_at=? WHERE agent_run_id=?""",
            (status, _json(output or {}), error_code, latency_ms, iso(), agent_run_id),
        )

    def list_agent_runs(self, limit: int = 50, agent_name: str | None = None) -> list[dict[str, Any]]:
        if agent_name:
            rows = self.db.query(
                "SELECT * FROM agent_runs WHERE agent_name=? ORDER BY created_at DESC LIMIT ?",
                (agent_name, limit),
            )
        else:
            rows = self.db.query("SELECT * FROM agent_runs ORDER BY created_at DESC LIMIT ?", (limit,))
        out = []
        for row in rows:
            item = _row(row)
            for column in ("input_context_json", "output_json"):
                try:
                    item[column.removesuffix("_json")] = json.loads(item.pop(column) or "{}")
                except json.JSONDecodeError:
                    item[column.removesuffix("_json")] = {}
            out.append(item)
        return out

    def save_memory(self, subject_id: str, memory_type: str, title: str,
                    content: str, confidence: float, source_agent_run_id: str | None,
                    requires_confirmation: bool = True) -> str:
        memory_id = new_id("mem")
        stamp = iso()
        self.db.execute(
            """INSERT INTO memories
               (memory_id, subject_id, memory_type, title, content, confidence,
                status, requires_confirmation, source_agent_run_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (memory_id, subject_id, memory_type[:40], title[:120], content[:600],
             max(0.0, min(1.0, float(confidence))),
             "pending" if requires_confirmation else "confirmed",
             int(requires_confirmation), source_agent_run_id, stamp, stamp),
        )
        return memory_id

    def list_memories(self, subject_id: str, status: str | None = None,
                      limit: int = 50) -> list[dict[str, Any]]:
        if status:
            rows = self.db.query(
                "SELECT * FROM memories WHERE subject_id=? AND status=? "
                "ORDER BY updated_at DESC LIMIT ?", (subject_id, status, limit))
        else:
            rows = self.db.query(
                "SELECT * FROM memories WHERE subject_id=? ORDER BY updated_at DESC LIMIT ?",
                (subject_id, limit))
        return [_row(row) for row in rows]

    def set_memory_status(self, memory_id: str, status: str) -> bool:
        if status not in {"pending", "confirmed", "invalidated"}:
            return False
        return self.db.execute(
            "UPDATE memories SET status=?, updated_at=? WHERE memory_id=?",
            (status, iso(), memory_id),
        ) > 0

    def add_interaction_message(self, subject_id: str, conversation_id: str,
                                role: str, text: str, intent: str,
                                agent_run_id: str | None) -> str:
        message_id = new_id("msg")
        self.db.execute(
            """INSERT INTO interaction_messages
               (message_id, subject_id, conversation_id, role, text, intent,
                agent_run_id, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (message_id, subject_id, conversation_id, role, text[:4000],
             intent[:80], agent_run_id, iso()),
        )
        return message_id

    def interaction_messages(self, subject_id: str, conversation_id: str,
                              limit: int = 40) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT * FROM interaction_messages
               WHERE subject_id=? AND conversation_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (subject_id, conversation_id, limit),
        )
        return [_row(row) for row in reversed(rows)]

    # -- config ----------------------------------------------------------

    def save_config_version(self, version: str, payload: dict[str, Any], note: str = "",
                            activate: bool = True) -> str:
        with self.db.transaction() as tx:
            tx.execute(
                """INSERT OR REPLACE INTO config_versions
                   (version, payload_json, note, is_active, created_at) VALUES (?,?,?,?,?)""",
                (version, _json(payload), note, 0, iso()),
            )
            if activate:
                tx.execute("UPDATE config_versions SET is_active = 0")
                tx.execute("UPDATE config_versions SET is_active = 1 WHERE version = ?", (version,))
        return version

    def activate_config_version(self, version: str) -> bool:
        row = self.db.query_one("SELECT version FROM config_versions WHERE version = ?", (version,))
        if row is None:
            return False
        with self.db.transaction() as tx:
            tx.execute("UPDATE config_versions SET is_active = 0")
            tx.execute("UPDATE config_versions SET is_active = 1 WHERE version = ?", (version,))
        return True

    def active_config(self) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM config_versions WHERE is_active = 1 LIMIT 1")
        if row is None:
            return None
        payload = _row(row)
        payload["payload"] = json.loads(payload.pop("payload_json") or "{}")
        return payload

    def list_config_versions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT version, note, is_active, created_at FROM config_versions "
            "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]

    # -- logs ------------------------------------------------------------

    def log(self, level: str, source: str, message: str, context: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "INSERT INTO app_logs(log_id, level, source, message, context_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (new_id("log"), level, source, message[:2000], _json(context or {}), iso()),
        )

    def recent_logs(self, limit: int = 100, level: str | None = None) -> list[dict[str, Any]]:
        if level:
            rows = self.db.query(
                "SELECT * FROM app_logs WHERE level=? ORDER BY created_at DESC LIMIT ?", (level, limit))
        else:
            rows = self.db.query("SELECT * FROM app_logs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows]

    def prune_logs(self, keep: int = 5000) -> int:
        return self.db.execute(
            "DELETE FROM app_logs WHERE log_id NOT IN "
            "(SELECT log_id FROM app_logs ORDER BY created_at DESC LIMIT ?)", (keep,))
