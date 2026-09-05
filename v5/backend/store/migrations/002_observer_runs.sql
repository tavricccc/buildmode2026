-- Persistent, periodic Long-term Observer audit records.
-- One row is written for every scheduled pass, including stable/no-alert passes.

CREATE TABLE IF NOT EXISTS observer_runs (
  observer_run_id       TEXT PRIMARY KEY,
  subject_id            TEXT NOT NULL,
  window_started_at_ms  INTEGER NOT NULL,
  window_ended_at_ms    INTEGER NOT NULL,
  status                TEXT NOT NULL
      CHECK(status IN ('stable','attention','insufficient_evidence','anomaly','failed')),
  headline              TEXT NOT NULL,
  detail                TEXT NOT NULL DEFAULT '',
  confidence            REAL NOT NULL DEFAULT 0 CHECK(confidence BETWEEN 0 AND 1),
  data_completeness     REAL NOT NULL DEFAULT 0 CHECK(data_completeness BETWEEN 0 AND 1),
  mode                  TEXT NOT NULL CHECK(mode IN ('deterministic','l3_narrative')),
  call_id               TEXT REFERENCES model_calls(call_id),
  metrics_json          TEXT NOT NULL DEFAULT '{}',
  anomaly_codes_json    TEXT NOT NULL DEFAULT '[]',
  created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_observer_runs_subject_time
  ON observer_runs(subject_id, window_ended_at_ms DESC);
CREATE INDEX IF NOT EXISTS idx_observer_runs_status_time
  ON observer_runs(status, window_ended_at_ms DESC);
