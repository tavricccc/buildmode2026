-- Care Agent v5 — initial schema (v5 02 §Data, Event, Policy 與稽核)
--
-- Carried over from v4: events, evidence, hydration_sessions,
-- health_samples, analyses, actions, transcripts, daily_summaries,
-- observer_findings, notification_deliveries.
--
-- New in v5: pipeline_runs — one row per vision window, carrying the
-- whole L1 -> L2 -> L3 -> policy path required by v5 00 item 10.

-- ---------------------------------------------------------------------
-- Provenance
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_calls (
  call_id         TEXT PRIMARY KEY,
  layer           TEXT NOT NULL CHECK(layer IN ('l1_person_gate','l2_gemini','l3_minimax')),
  provider        TEXT NOT NULL,
  model           TEXT NOT NULL,
  purpose         TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  schema_version  TEXT NOT NULL,
  -- 'invalid' is a first-class outcome, not an error: v5 01 requires an
  -- unparseable observation to be recorded and to leave event state alone.
  status          TEXT NOT NULL CHECK(status IN ('ok','repaired','invalid','failed')),
  latency_ms      INTEGER NOT NULL DEFAULT 0,
  prompt_tokens   INTEGER,
  output_tokens   INTEGER,
  total_tokens    INTEGER,
  attempts        INTEGER NOT NULL DEFAULT 1,
  error_code      TEXT,
  error_message   TEXT,
  input_hash      TEXT NOT NULL DEFAULT '',
  response_text   TEXT,            -- redacted before insert
  evidence_id     TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_calls_created ON model_calls(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_calls_layer ON model_calls(layer, status);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id     TEXT PRIMARY KEY,
  subject_id      TEXT NOT NULL,
  kind            TEXT NOT NULL,   -- 'clip' | 'frame' | 'audio'
  uri             TEXT,
  mime_type       TEXT,
  started_at_ms   INTEGER NOT NULL,
  duration_sec    REAL NOT NULL DEFAULT 0,
  frame_count     INTEGER NOT NULL DEFAULT 0,
  size_bytes      INTEGER NOT NULL DEFAULT 0,
  metadata_json   TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_started ON evidence(started_at_ms DESC);

-- ---------------------------------------------------------------------
-- The v5 cascade audit row
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id                  TEXT PRIMARY KEY,
  subject_id              TEXT NOT NULL,
  window_started_at_ms    INTEGER NOT NULL,
  window_ended_at_ms      INTEGER NOT NULL,
  config_version          TEXT NOT NULL,

  l1_decision             TEXT NOT NULL
      CHECK(l1_decision IN ('person_present','no_person','stale','unavailable')),
  l1_confidence           REAL NOT NULL DEFAULT 0,
  l1_detector_id          TEXT NOT NULL DEFAULT 'none',
  l1_latency_ms           INTEGER NOT NULL DEFAULT 0,
  l1_health               TEXT NOT NULL DEFAULT 'unknown',

  l2_outcome              TEXT NOT NULL
      CHECK(l2_outcome IN ('called','skipped_l1','heartbeat','forced_high_risk','failed')),
  l2_reason               TEXT NOT NULL DEFAULT '',
  l2_model                TEXT,
  l2_call_id              TEXT REFERENCES model_calls(call_id),
  l2_latency_ms           INTEGER,
  l2_repaired             INTEGER NOT NULL DEFAULT 0,
  l2_escalation_required  INTEGER NOT NULL DEFAULT 0,
  l2_escalation_reasons   TEXT NOT NULL DEFAULT '[]',
  l2_error                TEXT,

  l3_outcome              TEXT NOT NULL
      CHECK(l3_outcome IN ('not_required','called','degraded_text_only','failed')),
  l3_reason               TEXT NOT NULL DEFAULT '',
  l3_model                TEXT,
  l3_call_id              TEXT REFERENCES model_calls(call_id),
  l3_latency_ms           INTEGER,
  l3_risk_level           TEXT,
  l3_error                TEXT,

  evidence_id             TEXT REFERENCES evidence(evidence_id),
  clip_path               TEXT,
  event_ids               TEXT NOT NULL DEFAULT '[]',
  action_ids              TEXT NOT NULL DEFAULT '[]',
  created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_window ON pipeline_runs(window_started_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_runs_l2 ON pipeline_runs(l2_outcome);
CREATE INDEX IF NOT EXISTS idx_runs_l3 ON pipeline_runs(l3_outcome);

-- ---------------------------------------------------------------------
-- Events
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS events (
  event_id        TEXT PRIMARY KEY,
  subject_id      TEXT NOT NULL,
  event_type      TEXT NOT NULL CHECK(event_type IN ('fall','hydration')),
  status          TEXT NOT NULL,
  occurred_at_ms  INTEGER NOT NULL,
  updated_at_ms   INTEGER NOT NULL,
  ended_at_ms     INTEGER,
  confidence      REAL NOT NULL DEFAULT 0 CHECK(confidence BETWEEN 0 AND 1),
  attributes_json TEXT NOT NULL DEFAULT '{}',
  -- the same replayed footage must not create a second event (v5 00 item 11)
  dedup_key       TEXT NOT NULL UNIQUE,
  schema_version  TEXT NOT NULL,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_events_open ON events(event_type, status);

CREATE TABLE IF NOT EXISTS event_runs (
  event_id  TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
  run_id    TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
  PRIMARY KEY(event_id, run_id)
);

CREATE TABLE IF NOT EXISTS hydration_sessions (
  session_id      TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
  subject_id      TEXT NOT NULL,
  started_at_ms   INTEGER NOT NULL,
  ended_at_ms     INTEGER NOT NULL,
  estimated_ml    REAL NOT NULL,
  method          TEXT NOT NULL DEFAULT 'fixed_container_volume',
  day_key         TEXT NOT NULL,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hydration_day ON hydration_sessions(day_key);

-- ---------------------------------------------------------------------
-- Analyses, actions, notifications
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analyses (
  analysis_id     TEXT PRIMARY KEY,
  event_id        TEXT REFERENCES events(event_id) ON DELETE SET NULL,
  run_id          TEXT REFERENCES pipeline_runs(run_id) ON DELETE SET NULL,
  call_id         TEXT REFERENCES model_calls(call_id),
  trigger         TEXT NOT NULL,
  reason_codes    TEXT NOT NULL DEFAULT '[]',
  degraded        INTEGER NOT NULL DEFAULT 0,
  risk_level      TEXT,
  recommendation  TEXT,
  supports_l2     INTEGER NOT NULL DEFAULT 1,
  payload_json    TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at DESC);

CREATE TABLE IF NOT EXISTS actions (
  action_id           TEXT PRIMARY KEY,
  event_id            TEXT REFERENCES events(event_id) ON DELETE SET NULL,
  run_id              TEXT REFERENCES pipeline_runs(run_id) ON DELETE SET NULL,
  kind                TEXT NOT NULL,
  rule                TEXT NOT NULL,
  reason              TEXT NOT NULL DEFAULT '',
  severity            TEXT NOT NULL DEFAULT 'info',
  suppressed          INTEGER NOT NULL DEFAULT 0,
  suppressed_reason   TEXT NOT NULL DEFAULT '',
  created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_created ON actions(created_at DESC);

CREATE TABLE IF NOT EXISTS notification_deliveries (
  delivery_id     TEXT PRIMARY KEY,
  action_id       TEXT NOT NULL REFERENCES actions(action_id) ON DELETE CASCADE,
  channel         TEXT NOT NULL DEFAULT 'telegram',
  recipient       TEXT NOT NULL,
  status          TEXT NOT NULL CHECK(status IN ('pending','sent','acknowledged','false_alarm','failed')),
  -- opaque, single-use: the callback token never encodes the event id
  callback_token  TEXT UNIQUE,
  provider_msg_id TEXT,
  error           TEXT,
  sent_at         TEXT,
  responded_at    TEXT,
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_status ON notification_deliveries(status);

-- ---------------------------------------------------------------------
-- Health, transcripts, observer
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS health_samples (
  sample_id     TEXT PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  metric        TEXT NOT NULL,
  value         REAL NOT NULL,
  unit          TEXT NOT NULL DEFAULT '',
  source        TEXT NOT NULL DEFAULT 'fake',
  observed_at_ms INTEGER NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_metric ON health_samples(metric, observed_at_ms DESC);

CREATE TABLE IF NOT EXISTS transcripts (
  transcript_id TEXT PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  text          TEXT NOT NULL,
  started_at_ms INTEGER NOT NULL,
  ended_at_ms   INTEGER NOT NULL,
  confidence    REAL NOT NULL DEFAULT 0,
  -- retention TTL (v5 01 §Audio); the sweeper deletes past this instant
  expires_at_ms INTEGER NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transcripts_expiry ON transcripts(expires_at_ms);

CREATE TABLE IF NOT EXISTS daily_summaries (
  day_key           TEXT PRIMARY KEY,
  subject_id        TEXT NOT NULL,
  hydration_ml      REAL NOT NULL DEFAULT 0,
  hydration_sessions INTEGER NOT NULL DEFAULT 0,
  fall_events       INTEGER NOT NULL DEFAULT 0,
  l2_calls          INTEGER NOT NULL DEFAULT 0,
  l2_skipped        INTEGER NOT NULL DEFAULT 0,
  l3_calls          INTEGER NOT NULL DEFAULT 0,
  coverage_ratio    REAL NOT NULL DEFAULT 0,
  payload_json      TEXT NOT NULL DEFAULT '{}',
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observer_findings (
  finding_id    TEXT PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  day_key       TEXT NOT NULL,
  kind          TEXT NOT NULL,
  headline      TEXT NOT NULL,
  detail        TEXT NOT NULL DEFAULT '',
  severity      TEXT NOT NULL DEFAULT 'info',
  call_id       TEXT REFERENCES model_calls(call_id),
  payload_json  TEXT NOT NULL DEFAULT '{}',
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_findings_day ON observer_findings(day_key DESC);

-- ---------------------------------------------------------------------
-- Configuration and logs
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS config_versions (
  version       TEXT PRIMARY KEY,
  payload_json  TEXT NOT NULL,
  note          TEXT NOT NULL DEFAULT '',
  is_active     INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_config_active ON config_versions(is_active, created_at DESC);

CREATE TABLE IF NOT EXISTS app_logs (
  log_id      TEXT PRIMARY KEY,
  level       TEXT NOT NULL,
  source      TEXT NOT NULL,
  message     TEXT NOT NULL,
  context_json TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON app_logs(created_at DESC);
