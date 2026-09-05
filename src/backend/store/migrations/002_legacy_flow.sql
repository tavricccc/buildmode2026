-- Compatibility records for the original Longcare flow.
-- These are additive: pipeline_runs remains the cascade audit source,
-- while these tables hold bounded Main Agent, memory and interaction state.

ALTER TABLE pipeline_runs ADD COLUMN change_detected INTEGER NOT NULL DEFAULT 1;
ALTER TABLE pipeline_runs ADD COLUMN change_score REAL;
ALTER TABLE pipeline_runs ADD COLUMN change_reasons TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS agent_runs (
  agent_run_id     TEXT PRIMARY KEY,
  subject_id       TEXT NOT NULL,
  agent_name       TEXT NOT NULL,
  trigger_type     TEXT NOT NULL,
  trigger_id       TEXT,
  window_id        TEXT,
  status           TEXT NOT NULL,
  input_context_json TEXT NOT NULL DEFAULT '{}',
  output_json      TEXT NOT NULL DEFAULT '{}',
  error_code       TEXT,
  provider         TEXT NOT NULL DEFAULT 'local_vllm',
  model            TEXT NOT NULL DEFAULT '',
  latency_ms       INTEGER,
  dedup_key        TEXT NOT NULL UNIQUE,
  created_at       TEXT NOT NULL,
  completed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_created ON agent_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_trigger ON agent_runs(trigger_type, created_at DESC);

CREATE TABLE IF NOT EXISTS memories (
  memory_id        TEXT PRIMARY KEY,
  subject_id       TEXT NOT NULL,
  memory_type      TEXT NOT NULL,
  title            TEXT NOT NULL,
  content          TEXT NOT NULL,
  confidence       REAL NOT NULL DEFAULT 0,
  status           TEXT NOT NULL DEFAULT 'pending',
  requires_confirmation INTEGER NOT NULL DEFAULT 1,
  source_agent_run_id TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(subject_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS interaction_messages (
  message_id       TEXT PRIMARY KEY,
  subject_id       TEXT NOT NULL,
  conversation_id  TEXT NOT NULL,
  role             TEXT NOT NULL,
  text             TEXT NOT NULL,
  intent           TEXT NOT NULL DEFAULT 'unknown',
  agent_run_id     TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interaction_messages ON interaction_messages(conversation_id, created_at DESC);
