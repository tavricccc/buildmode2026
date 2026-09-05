-- Persisted operator trace and isolated-debug run metadata.

CREATE TABLE IF NOT EXISTS pipeline_steps (
  step_id          TEXT PRIMARY KEY,
  run_id           TEXT NOT NULL,
  event_id         TEXT,
  step             TEXT NOT NULL,
  status           TEXT NOT NULL
      CHECK(status IN ('waiting','running','succeeded','skipped','degraded','failed')),
  summary          TEXT NOT NULL DEFAULT '',
  reason_codes_json TEXT NOT NULL DEFAULT '[]',
  input_json       TEXT NOT NULL DEFAULT '{}',
  output_json      TEXT NOT NULL DEFAULT '{}',
  mode             TEXT NOT NULL DEFAULT 'live',
  started_at_ms    INTEGER NOT NULL,
  completed_at_ms  INTEGER,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pipeline_steps_run ON pipeline_steps(run_id, started_at_ms);
CREATE INDEX IF NOT EXISTS idx_pipeline_steps_active ON pipeline_steps(status, started_at_ms DESC);

CREATE TABLE IF NOT EXISTS simulation_runs (
  simulation_id    TEXT PRIMARY KEY,
  kind             TEXT NOT NULL,
  profile          TEXT NOT NULL,
  mode             TEXT NOT NULL CHECK(mode IN ('contract','evaluation')),
  seed             INTEGER NOT NULL,
  status           TEXT NOT NULL,
  parameters_json  TEXT NOT NULL DEFAULT '{}',
  generated_rows   INTEGER NOT NULL DEFAULT 0,
  started_at_ms    INTEGER NOT NULL,
  completed_at_ms  INTEGER,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_simulation_runs_started ON simulation_runs(started_at_ms DESC);
