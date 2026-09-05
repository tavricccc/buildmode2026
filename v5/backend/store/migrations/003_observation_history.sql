-- Every accepted L2 observation is retained as a bounded, queryable record.
CREATE TABLE IF NOT EXISTS observations (
  observation_id  TEXT PRIMARY KEY,
  run_id          TEXT NOT NULL UNIQUE REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
  subject_id      TEXT NOT NULL,
  observed_at_ms  INTEGER NOT NULL,
  summary         TEXT NOT NULL DEFAULT '',
  confidence      REAL NOT NULL DEFAULT 0,
  payload_json    TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_time ON observations(subject_id, observed_at_ms DESC);
