# 04 · SQLite 資料模型與查詢

> **v3 amendment：** `events` 仍是 fall/hydration canonical ledger；新增資料盡量進 `attributes_json`。無法用既有事件表達的 sound/person/object/scene 才進 `recognition_events`，並保留同樣的 provenance、window、confidence、model call 與 dedup 語意。

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

CREATE TABLE recognition_events (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  domain TEXT NOT NULL CHECK(domain IN ('sound','person','object','scene')),
  label TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'observed',
  occurred_at TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  attributes_json TEXT NOT NULL DEFAULT '{}',
  window_id TEXT NOT NULL,
  model_call_id TEXT REFERENCES model_calls(id),
  dedup_key TEXT NOT NULL UNIQUE,
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

CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  trigger_type TEXT NOT NULL,
  trigger_id TEXT NOT NULL,
  window_id TEXT,
  status TEXT NOT NULL,
  decision TEXT NOT NULL,
  attention_level TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  confidence REAL NOT NULL,
  input_json TEXT NOT NULL,
  analysis_json TEXT,
  policy_json TEXT NOT NULL DEFAULT '{}',
  model_call_id TEXT REFERENCES model_calls(id),
  error_code TEXT,
  latency_ms INTEGER,
  config_version TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE
);

CREATE TABLE agent_run_events (
  id TEXT PRIMARY KEY,
  agent_run_id TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  sequence INTEGER NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE TABLE agent_notes (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  layer TEXT NOT NULL CHECK(layer IN ('decision','abstraction','research')),
  note_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content_json TEXT NOT NULL,
  source_agent TEXT NOT NULL,
  source_run_id TEXT,
  source_window_id TEXT,
  parent_note_id TEXT,
  target_layers_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  confidence REAL NOT NULL,
  importance REAL NOT NULL DEFAULT 0.5,
  privacy_level TEXT NOT NULL DEFAULT 'local',
  requires_review INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE
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
CREATE INDEX idx_recognition_events_subject_time
  ON recognition_events(subject_id, occurred_at);
CREATE INDEX idx_recognition_events_domain_time
  ON recognition_events(subject_id, domain, occurred_at);
CREATE INDEX idx_agent_runs_subject_time ON agent_runs(subject_id, created_at);
CREATE INDEX idx_agent_runs_status_time ON agent_runs(status, created_at);
CREATE INDEX idx_agent_run_events_run_sequence ON agent_run_events(agent_run_id, sequence);
CREATE INDEX idx_agent_run_events_subject_time ON agent_run_events(subject_id, occurred_at);
CREATE INDEX idx_agent_notes_subject_layer_time ON agent_notes(subject_id, layer, created_at);
CREATE INDEX idx_agent_notes_expiry ON agent_notes(status, expires_at);
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

## 5. v3 實作對照

- `events`：目前 canonical 的 `fall`／`hydration`；欄位不足時先擴充 `attributes_json`。
- `recognition_events`：目前已用於 sound/person/object/scene 例外候選，包含 `window_id`、`model_call_id`、confidence、dedup 與 `attributes_json`。
- multimodal attributes 至少可保存 `audio_present`、`audio_events`、`speaker_emotion`、`audio_confidence`、`audio_uncertainty_reasons`、`frame_count`、`window_seconds` 與 source status。
- `evidence`／`model_calls`／`app_logs`／recognition logs 共同形成 provenance；raw video、raw WebM 與 raw WAV 不屬於預設永久資料。
- World State、Inquiry、privacy aggregation 的專用表仍是下一階段 migration；在此之前不得把尚未存在的欄位寫成已完成能力。
- `agent_runs` 是目前 Main Agent 的 audit ledger；它保存 judgment 與 deterministic policy，不代表 action 已執行。
- `agent_run_events` 保存每輪的 stage trace；`agent_notes` 提供 decision／abstraction／research 三層小型記憶文件，Research note 可透過 `target_layers_json` 提出注意事項，但必須 review 才能影響決策。
