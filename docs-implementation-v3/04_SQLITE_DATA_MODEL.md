# 04 · SQLite 資料模型與查詢

## 1. 初始化

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
```

所有 schema 變更使用 migration；正式程式不得在啟動時任意刪表重建。Demo reset 走明確的開發端點，且只清除 Demo 資料。

## 2. 核心資料表

```sql
CREATE TABLE evidence (
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

CREATE TABLE model_calls (
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
  UNIQUE(provider, model, purpose, input_hash, prompt_version)
);

CREATE TABLE events (
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

CREATE TABLE event_evidence (
  event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
  role TEXT NOT NULL,
  PRIMARY KEY(event_id, evidence_id, role)
);

CREATE TABLE hydration_sessions (
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

CREATE TABLE health_samples (
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

CREATE TABLE analyses (
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

CREATE TABLE actions (
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

CREATE TABLE app_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  level TEXT NOT NULL,
  component TEXT NOT NULL,
  event_id TEXT,
  message TEXT NOT NULL,
  context_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE transcripts (
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

CREATE TABLE memories (
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

CREATE TABLE runtime_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  version INTEGER NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE tool_calls (
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

CREATE TABLE daily_summaries (
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

CREATE TABLE observer_findings (
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

CREATE TABLE notification_deliveries (
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
```

## 3. 索引

```sql
CREATE INDEX idx_events_subject_type_time
  ON events(subject_id, event_type, occurred_at);
CREATE INDEX idx_events_status_time ON events(status, occurred_at);
CREATE INDEX idx_hydration_subject_time
  ON hydration_sessions(subject_id, ended_at);
CREATE INDEX idx_health_subject_metric_time
  ON health_samples(subject_id, metric, measured_at);
CREATE INDEX idx_analyses_subject_window
  ON analyses(subject_id, window_end);
CREATE INDEX idx_logs_time ON app_logs(ts);
CREATE INDEX idx_transcripts_subject_time
  ON transcripts(subject_id, started_at);
CREATE INDEX idx_tool_calls_event_time
  ON tool_calls(event_id, created_at);
CREATE INDEX idx_findings_subject_window
  ON observer_findings(subject_id, window_end);
CREATE INDEX idx_notification_status_time
  ON notification_deliveries(status, created_at);
```

## 4. AI 可用的唯讀查詢工具

MiniMax 不取得 SQL 字串工具，只能呼叫參數化函式：

- `get_event_counts(subject_id, event_types, start, end)`
- `get_hydration_summary(subject_id, start, end)`
- `get_recent_fall_events(subject_id, start, end, limit)`
- `get_health_snapshot(subject_id, at, lookback_minutes)`
- `get_health_series_summary(subject_id, metrics, start, end)`

`get_hydration_summary` 至少回傳 confirmed session count、estimated total ml、daily target、完成比例、最後飲水時間及資料 coverage。這使 AI 讀固定大小摘要，避免 token 隨事件數線性增加。
