-- Care Agent v4 — initial schema
-- v3 14 tables preserved; v4 adds model_endpoints, installed_models, config_versions
-- and extends model_calls with model_endpoint_id / config_version / capability.

PRAGMA foreign_keys = ON;

-- v3 tables (subset of columns used by the v4 backend)
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_uri TEXT,
  source_offset_start_ms INTEGER,
  source_offset_end_ms INTEGER,
  captured_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  purpose TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  tokens_in INTEGER,
  tokens_out INTEGER,
  error_code TEXT,
  response_json TEXT,
  created_at TEXT NOT NULL,
  -- v4 additions
  model_endpoint_id TEXT,
  config_version TEXT,
  capability TEXT,
  UNIQUE(provider, model, purpose, input_hash, prompt_version)
);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('fall','hydration')),
  status TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  ended_at TEXT,
  source_offset_ms INTEGER,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  attributes_json TEXT NOT NULL DEFAULT '{}',
  model_call_id TEXT REFERENCES model_calls(id),
  dedup_key TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_evidence (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
  role TEXT NOT NULL,
  PRIMARY KEY(event_id, evidence_id, role)
);

CREATE TABLE IF NOT EXISTS hydration_sessions (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL UNIQUE REFERENCES events(id),
  subject_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  estimated_ml REAL NOT NULL,
  estimation_method TEXT NOT NULL,
  estimation_confidence REAL NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_samples (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  metric TEXT NOT NULL,
  value_num REAL,
  value_text TEXT,
  unit TEXT,
  measured_at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'fake',
  quality TEXT NOT NULL DEFAULT 'valid',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  analysis_type TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  input_summary_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  model_call_id TEXT REFERENCES model_calls(id),
  config_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,
  event_id TEXT REFERENCES events(id),
  analysis_id TEXT REFERENCES analyses(id),
  action_type TEXT NOT NULL,
  status TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS app_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  component TEXT NOT NULL,
  event_id TEXT,
  message TEXT NOT NULL,
  context_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  event_id TEXT REFERENCES events(id),
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  text TEXT,
  language TEXT,
  confidence REAL,
  retention_until TEXT,
  model_call_id TEXT REFERENCES model_calls(id),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  memory_type TEXT NOT NULL,
  content_json TEXT NOT NULL,
  source_event_id TEXT REFERENCES events(id),
  status TEXT NOT NULL,
  version INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  version INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  event_id TEXT REFERENCES events(id),
  analysis_id TEXT REFERENCES analyses(id),
  arguments_json TEXT NOT NULL,
  result_json TEXT,
  status TEXT NOT NULL,
  latency_ms INTEGER,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_summaries (
  subject_id TEXT NOT NULL,
  summary_date TEXT NOT NULL,
  event_counts_json TEXT NOT NULL,
  hydration_json TEXT NOT NULL,
  health_json TEXT NOT NULL,
  coverage_json TEXT NOT NULL,
  config_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(subject_id, summary_date, config_version)
);

CREATE TABLE IF NOT EXISTS observer_findings (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  finding_type TEXT NOT NULL,
  statement TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  confidence REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL REFERENCES actions(id),
  channel TEXT NOT NULL CHECK(channel = 'telegram'),
  recipient_ref TEXT NOT NULL,
  provider_message_id TEXT,
  status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  sent_at TEXT,
  acknowledged_at TEXT,
  acknowledged_by TEXT,
  acknowledgement_type TEXT,
  last_error_code TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- v4 new tables
CREATE TABLE IF NOT EXISTS model_endpoints (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  deployment_type TEXT NOT NULL CHECK(deployment_type IN ('local','cloud')),
  base_url TEXT NOT NULL,
  adapter_mode TEXT NOT NULL,
  secret_ref TEXT,
  runtime_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS installed_models (
  id TEXT PRIMARY KEY,
  endpoint_id TEXT NOT NULL REFERENCES model_endpoints(id),
  remote_model_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  capability TEXT NOT NULL CHECK(capability IN ('vision','analysis','transcription','speech','embedding')),
  source_type TEXT NOT NULL CHECK(source_type IN ('local_catalog','cloud_provider')),
  local_artifact_ref TEXT,
  probe_status TEXT NOT NULL,
  capability_json TEXT NOT NULL,
  installed_at TEXT NOT NULL,
  last_probed_at TEXT,
  UNIQUE(endpoint_id, remote_model_id, capability)
);

CREATE TABLE IF NOT EXISTS config_versions (
  id TEXT PRIMARY KEY,
  base_version TEXT,
  settings_json TEXT NOT NULL,
  changed_keys_json TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  activated_at TEXT,
  rolled_back_from TEXT
);

CREATE TABLE IF NOT EXISTS active_models (
  capability TEXT PRIMARY KEY,
  installed_model_id TEXT NOT NULL REFERENCES installed_models(id),
  config_version TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- v3 indexes
CREATE INDEX IF NOT EXISTS idx_events_subject_type_time
  ON events(subject_id, event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_status_time ON events(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_hydration_subject_time
  ON hydration_sessions(subject_id, ended_at);
CREATE INDEX IF NOT EXISTS idx_health_subject_metric_time
  ON health_samples(subject_id, metric, measured_at);
CREATE INDEX IF NOT EXISTS idx_analyses_subject_window
  ON analyses(subject_id, window_end);
CREATE INDEX IF NOT EXISTS idx_logs_time ON app_logs(ts);
CREATE INDEX IF NOT EXISTS idx_transcripts_subject_time
  ON transcripts(subject_id, started_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_event_time
  ON tool_calls(event_id, created_at);
CREATE INDEX IF NOT EXISTS idx_findings_subject_window
  ON observer_findings(subject_id, window_end);
CREATE INDEX IF NOT EXISTS idx_notification_status_time
  ON notification_deliveries(status, created_at);

-- v4 indexes
CREATE INDEX IF NOT EXISTS idx_model_calls_endpoint
  ON model_calls(model_endpoint_id);
CREATE INDEX IF NOT EXISTS idx_installed_capability
  ON installed_models(capability);
CREATE INDEX IF NOT EXISTS idx_config_versions_activated
  ON config_versions(activated_at);
