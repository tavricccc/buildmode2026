# 04 · SQLite 資料模型

事件、evidence、hydration、health、analyses、actions、transcripts、memories、tool calls、daily summaries、findings 與 Telegram delivery schema 沿用 v3。

v4 在 `model_calls` 增加 `model_endpoint_id`、`config_version`、`capability`；provider/model 欄位仍保存呼叫當時快照。另新增：

```sql
CREATE TABLE model_endpoints (
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

CREATE TABLE installed_models (
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

CREATE TABLE config_versions (
  id TEXT PRIMARY KEY,
  base_version TEXT,
  settings_json TEXT NOT NULL,
  changed_keys_json TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  activated_at TEXT,
  rolled_back_from TEXT
);
```

本地 artifact 只能引用 backend catalog 管理的 model-store ID，不能保存前端傳入的任意 path。Secret 放在獨立 secret store；settings、logs、model calls 不得含原值。刪除 endpoint/model 不可破壞舊 audit reference。
