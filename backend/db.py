from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, source_type TEXT NOT NULL, source_uri TEXT,
  source_offset_start_ms INTEGER, source_offset_end_ms INTEGER, captured_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_calls (
  id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL,
  input_hash TEXT NOT NULL, prompt_version TEXT NOT NULL, schema_version TEXT NOT NULL,
  status TEXT NOT NULL, latency_ms INTEGER, tokens_in INTEGER, tokens_out INTEGER,
  error_code TEXT, response_json TEXT, created_at TEXT NOT NULL,
  UNIQUE(provider, model, purpose, input_hash, prompt_version)
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, event_type TEXT NOT NULL CHECK(event_type IN ('fall','hydration')),
  status TEXT NOT NULL, occurred_at TEXT NOT NULL, ended_at TEXT, source_offset_ms INTEGER,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1), attributes_json TEXT NOT NULL DEFAULT '{}',
  model_call_id TEXT REFERENCES model_calls(id), dedup_key TEXT NOT NULL UNIQUE, schema_version TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_evidence (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
  role TEXT NOT NULL, PRIMARY KEY(event_id, evidence_id, role)
);
CREATE TABLE IF NOT EXISTS hydration_sessions (
  id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE REFERENCES events(id), subject_id TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT NOT NULL, estimated_ml REAL NOT NULL,
  estimation_method TEXT NOT NULL, estimation_confidence REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health_samples (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, metric TEXT NOT NULL, value_num REAL, value_text TEXT,
  unit TEXT, measured_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'fake', quality TEXT NOT NULL DEFAULT 'valid', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, analysis_type TEXT NOT NULL, window_start TEXT NOT NULL,
  window_end TEXT NOT NULL, input_summary_json TEXT NOT NULL, result_json TEXT NOT NULL, risk_level TEXT NOT NULL,
  model_call_id TEXT REFERENCES model_calls(id), config_version TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, agent_name TEXT NOT NULL,
  trigger_type TEXT NOT NULL, trigger_id TEXT NOT NULL, window_id TEXT,
  status TEXT NOT NULL, decision TEXT NOT NULL, attention_level TEXT NOT NULL,
  risk_level TEXT NOT NULL, confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  input_json TEXT NOT NULL, analysis_json TEXT, policy_json TEXT NOT NULL DEFAULT '{}',
  model_call_id TEXT REFERENCES model_calls(id), error_code TEXT, latency_ms INTEGER,
  config_version TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
  created_at TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_subject_time ON agent_runs(subject_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_time ON agent_runs(status, created_at);
CREATE TABLE IF NOT EXISTS agent_run_events (
  id TEXT PRIMARY KEY, agent_run_id TEXT NOT NULL, subject_id TEXT NOT NULL,
  stage TEXT NOT NULL, event_type TEXT NOT NULL, message TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}', sequence INTEGER NOT NULL,
  occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_sequence ON agent_run_events(agent_run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_agent_run_events_subject_time ON agent_run_events(subject_id, occurred_at);
CREATE TABLE IF NOT EXISTS agent_notes (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL,
  layer TEXT NOT NULL CHECK(layer IN ('decision','abstraction','research')),
  note_type TEXT NOT NULL, title TEXT NOT NULL, content_json TEXT NOT NULL,
  source_agent TEXT NOT NULL, source_run_id TEXT, source_window_id TEXT,
  parent_note_id TEXT, target_layers_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active', confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  importance REAL NOT NULL DEFAULT 0.5 CHECK(importance >= 0 AND importance <= 1),
  privacy_level TEXT NOT NULL DEFAULT 'local', requires_review INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_agent_notes_subject_layer_time ON agent_notes(subject_id, layer, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_notes_expiry ON agent_notes(status, expires_at);
CREATE TABLE IF NOT EXISTS scene_contexts (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, stream_id TEXT NOT NULL,
  location TEXT NOT NULL, description_text TEXT NOT NULL,
  objects_json TEXT NOT NULL DEFAULT '[]', non_person_features_json TEXT NOT NULL DEFAULT '[]',
  uncertainty_json TEXT NOT NULL DEFAULT '[]', confidence REAL NOT NULL,
  model_call_id TEXT REFERENCES model_calls(id), started_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scene_contexts_stream ON scene_contexts(stream_id, created_at);
CREATE TABLE IF NOT EXISTS visual_descriptions (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, stream_id TEXT NOT NULL,
  description_type TEXT NOT NULL CHECK(description_type IN ('detail','focus')),
  window_id TEXT NOT NULL, start_offset_ms INTEGER NOT NULL, end_offset_ms INTEGER NOT NULL,
  description_text TEXT NOT NULL, facts_json TEXT NOT NULL DEFAULT '[]', objects_json TEXT NOT NULL DEFAULT '[]',
  actions_json TEXT NOT NULL DEFAULT '[]', changes_json TEXT NOT NULL DEFAULT '[]', warnings_json TEXT NOT NULL DEFAULT '[]',
  unknowns_json TEXT NOT NULL DEFAULT '[]', confidence REAL NOT NULL, warning_level TEXT NOT NULL DEFAULT 'none',
  model_call_id TEXT REFERENCES model_calls(id), scene_context_id TEXT REFERENCES scene_contexts(id),
  created_at TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_visual_descriptions_stream_time ON visual_descriptions(stream_id, start_offset_ms);
CREATE TABLE IF NOT EXISTS focus_reviews (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, stream_id TEXT NOT NULL,
  window_id TEXT NOT NULL, trigger_window_id TEXT, abnormal INTEGER NOT NULL,
  warning_level TEXT NOT NULL, comparison_summary TEXT NOT NULL, description_text TEXT NOT NULL,
  supporting_facts_json TEXT NOT NULL DEFAULT '[]', unknowns_json TEXT NOT NULL DEFAULT '[]',
  evidence_frame_indexes_json TEXT NOT NULL DEFAULT '[]', confidence REAL NOT NULL,
  next_action TEXT NOT NULL, model_call_id TEXT REFERENCES model_calls(id), created_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_focus_reviews_stream_time ON focus_reviews(stream_id, created_at);
CREATE TABLE IF NOT EXISTS time_segments (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, stream_id TEXT NOT NULL,
  start_offset_ms INTEGER NOT NULL, end_offset_ms INTEGER NOT NULL, summary TEXT NOT NULL,
  observed_actions_json TEXT NOT NULL DEFAULT '[]', not_observed_actions_json TEXT NOT NULL DEFAULT '[]',
  uncertainty_json TEXT NOT NULL DEFAULT '[]', source_description_ids_json TEXT NOT NULL DEFAULT '[]',
  main_agent_run_id TEXT, status TEXT NOT NULL DEFAULT 'observed', created_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_time_segments_stream_time ON time_segments(stream_id, start_offset_ms);
CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY, event_id TEXT REFERENCES events(id), analysis_id TEXT REFERENCES analyses(id),
  action_type TEXT NOT NULL, status TEXT NOT NULL, policy_version TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS app_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, level TEXT NOT NULL, component TEXT NOT NULL,
  event_id TEXT, message TEXT NOT NULL, context_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, event_id TEXT REFERENCES events(id), started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL, text TEXT, language TEXT, confidence REAL, retention_until TEXT,
  model_call_id TEXT REFERENCES model_calls(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, memory_type TEXT NOT NULL, content_json TEXT NOT NULL,
  source_event_id TEXT REFERENCES events(id), status TEXT NOT NULL, version INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_state (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, tool_name TEXT NOT NULL, event_id TEXT REFERENCES events(id),
  analysis_id TEXT REFERENCES analyses(id), arguments_json TEXT NOT NULL, result_json TEXT, status TEXT NOT NULL,
  latency_ms INTEGER, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_summaries (
  subject_id TEXT NOT NULL, summary_date TEXT NOT NULL, event_counts_json TEXT NOT NULL,
  hydration_json TEXT NOT NULL, health_json TEXT NOT NULL, coverage_json TEXT NOT NULL,
  config_version TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(subject_id, summary_date, config_version)
);
CREATE TABLE IF NOT EXISTS observer_findings (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
  finding_type TEXT NOT NULL, statement TEXT NOT NULL, evidence_json TEXT NOT NULL,
  confidence REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
  id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES actions(id), channel TEXT NOT NULL CHECK(channel = 'telegram'),
  recipient_ref TEXT NOT NULL, provider_message_id TEXT, status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
  sent_at TEXT, acknowledged_at TEXT, acknowledged_by TEXT, acknowledgement_type TEXT,
  last_error_code TEXT, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value_json TEXT NOT NULL, config_version TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_installations (
  id TEXT PRIMARY KEY, model_id TEXT NOT NULL, quantization TEXT NOT NULL, revision TEXT NOT NULL,
  status TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, path TEXT, is_active INTEGER NOT NULL DEFAULT 0,
  installed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_download_jobs (
  id TEXT PRIMARY KEY, model_id TEXT NOT NULL, quantization TEXT NOT NULL, status TEXT NOT NULL,
  progress REAL NOT NULL DEFAULT 0, bytes_done INTEGER NOT NULL DEFAULT 0, bytes_total INTEGER NOT NULL DEFAULT 0,
  error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_sources (
  id TEXT PRIMARY KEY, display_name TEXT NOT NULL, event_type TEXT NOT NULL, duration_ms INTEGER NOT NULL,
  source_uri TEXT, allowlisted INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS frigate_log_snippets (
  id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, frigate_event_id TEXT, update_type TEXT,
  received_at TEXT NOT NULL, frame_sha256 TEXT, width INTEGER, height INTEGER,
  labels_json TEXT NOT NULL DEFAULT '[]', detections_json TEXT NOT NULL DEFAULT '[]',
  noteworthy INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL, decision_source TEXT NOT NULL,
  log_excerpt TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(frigate_event_id, update_type, camera_id)
);
CREATE INDEX IF NOT EXISTS idx_frigate_logs_time ON frigate_log_snippets(received_at);
CREATE INDEX IF NOT EXISTS idx_frigate_logs_noteworthy ON frigate_log_snippets(noteworthy, received_at);
CREATE TABLE IF NOT EXISTS virtual_camera_streams (
  id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, media_type TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT, bytes_received INTEGER NOT NULL DEFAULT 0,
  chunks_received INTEGER NOT NULL DEFAULT 0, bridge_status TEXT NOT NULL,
  rtsp_target TEXT, media_path TEXT, media_retention_seconds INTEGER NOT NULL DEFAULT 60,
  error_code TEXT, vlm_status TEXT NOT NULL DEFAULT 'disabled',
  vlm_frames INTEGER NOT NULL DEFAULT 0, vlm_windows INTEGER NOT NULL DEFAULT 0,
  vlm_window_frames INTEGER NOT NULL DEFAULT 0, audio_status TEXT NOT NULL DEFAULT 'disabled',
  audio_bytes INTEGER NOT NULL DEFAULT 0, audio_windows INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_virtual_camera_streams_time ON virtual_camera_streams(started_at);
CREATE TABLE IF NOT EXISTS change_gate_results (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, stream_id TEXT NOT NULL,
  window_id TEXT NOT NULL, start_offset_ms INTEGER NOT NULL, end_offset_ms INTEGER NOT NULL,
  changed INTEGER NOT NULL, change_score REAL, threshold REAL NOT NULL,
  change_summary TEXT NOT NULL, change_reasons_json TEXT NOT NULL DEFAULT '[]',
  method TEXT NOT NULL, created_at TEXT NOT NULL, dedup_key TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_change_gate_stream_time ON change_gate_results(stream_id, start_offset_ms);
CREATE TABLE IF NOT EXISTS recognition_events (
  id TEXT PRIMARY KEY, subject_id TEXT NOT NULL, event_type TEXT NOT NULL,
  domain TEXT NOT NULL, label TEXT NOT NULL, status TEXT NOT NULL,
  occurred_at TEXT NOT NULL, confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  attributes_json TEXT NOT NULL DEFAULT '{}', window_id TEXT, model_call_id TEXT REFERENCES model_calls(id),
  dedup_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recognition_events_type_time ON recognition_events(subject_id, event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_recognition_events_domain_time ON recognition_events(subject_id, domain, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_subject_type_time ON events(subject_id, event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_status_time ON events(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_hydration_subject_time ON hydration_sessions(subject_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_health_subject_metric_time ON health_samples(subject_id, metric, measured_at);
CREATE INDEX IF NOT EXISTS idx_analyses_subject_window ON analyses(subject_id, window_end);
CREATE INDEX IF NOT EXISTS idx_logs_time ON app_logs(ts);
CREATE INDEX IF NOT EXISTS idx_transcripts_subject_time ON transcripts(subject_id, started_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_event_time ON tool_calls(event_id, created_at);
CREATE INDEX IF NOT EXISTS idx_findings_subject_window ON observer_findings(subject_id, window_end);
CREATE INDEX IF NOT EXISTS idx_notification_status_time ON notification_deliveries(status, created_at);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def initialize(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(virtual_camera_streams)").fetchall()}
            if "vlm_status" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN vlm_status TEXT NOT NULL DEFAULT 'disabled'")
            if "vlm_frames" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN vlm_frames INTEGER NOT NULL DEFAULT 0")
            if "vlm_windows" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN vlm_windows INTEGER NOT NULL DEFAULT 0")
            if "vlm_window_frames" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN vlm_window_frames INTEGER NOT NULL DEFAULT 0")
            if "audio_status" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN audio_status TEXT NOT NULL DEFAULT 'disabled'")
            if "audio_bytes" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN audio_bytes INTEGER NOT NULL DEFAULT 0")
            if "audio_windows" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN audio_windows INTEGER NOT NULL DEFAULT 0")
            if "media_path" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN media_path TEXT")
            if "media_retention_seconds" not in columns:
                conn.execute("ALTER TABLE virtual_camera_streams ADD COLUMN media_retention_seconds INTEGER NOT NULL DEFAULT 60")
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, datetime('now'))")
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = self.connect()
        try:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        conn = self.connect()
        try:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
