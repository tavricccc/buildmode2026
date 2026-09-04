# 02 · Event、Agent 與 Policy 契約

## 1. 共用事件信封

```json
{
  "event_id": "evt_01J...",
  "subject_id": "resident_demo",
  "event_type": "fall",
  "status": "candidate",
  "occurred_at": "2026-09-04T14:32:10+08:00",
  "source_offset_ms": 18340,
  "confidence": 0.78,
  "evidence_ids": ["evd_01J..."],
  "attributes": {},
  "model_id": "local-vlm",
  "model_version": "configured-at-runtime",
  "prompt_version": "vision-events.v1",
  "schema_version": "event.v1",
  "dedup_key": "sha256:..."
}
```

合法 `status`：`candidate`、`confirmed`、`recovering`、`resolved`、`dismissed`、`invalid`。

## 2. Logical Agents

Agent 是同一 backend 裡具明確 contract 的工作單元，不代表獨立 process，也不必並行。

### Event Understanding Agent

- 輸入：confirmed event、local observations、必要 evidence refs。
- 輸出：事件摘要、支持與反對證據、uncertainty。
- 可用工具：事件查詢、證據 metadata、MiniMax（選用）。
- 禁止：修改事件計數、直接發 alert。

### Health Context Agent

- 輸入：使用者指定時間窗、目前 health snapshot、SQL aggregates。
- 輸出：資料摘要、值得注意的組合、缺失資料、可行建議。
- 可用工具：`get_health_snapshot`、`get_event_summary`、MiniMax。
- 禁止：診斷疾病、任意 SQL、取得未要求的原始影片。

### Risk Agent

- 輸入：event understanding、health analysis、近期事件統計、policy settings。
- 輸出：`risk_level`、reason codes、時間窗、uncertainty、proposed actions。
- 禁止：直接執行 proposed action、修改 policy threshold。

### Intervention Agent

- 輸入：Policy Gateway 核准的 action。
- P0 工具：`dashboard_alert`。
- 完整架構工具：`system_tts`、`telegram_notify`。
- 禁止：未經核准擴大 action 或收件人。

L3 只代表通知照護者，不代表自動緊急服務。Telegram Bot 是 L3 的實作 channel；L4 不存在於本版可執行 action enum。

## 3. Deterministic Policy Gateway

Policy Gateway 不呼叫模型，只讀已驗證欄位與設定。例如：

```yaml
fall:
  confirm_window_sec: 8
  no_recovery_alert_sec: 120
  demo_no_recovery_alert_sec: 10
  min_confidence: 0.70
hydration:
  target_ml_per_day: 1600
  reminder_window_hours: 4
  min_confirmed_sessions: 1
analysis:
  default_window: 24h
  allowed_windows: [1h, 6h, 24h, 7d, 30d]
```

數值是初始 Demo 設定，不是醫療標準；必須可由設定覆蓋並保存使用中的 config version。

## 4. Idempotency 與順序

1. Evidence 先建立。
2. Local observation 寫入。
3. State machine 以 transaction 更新 event/session。
4. Transaction commit 後才發 WebSocket。
5. Agent 分析可重試；使用 `event_id + agent_name + input_hash + version` 去重。
6. Intervention 使用 `event_id + policy_version + action_type` 去重。
