# 07 · MiniMax 健康與風險分析

> **v3 amendment：** MiniMax 只處理固定大小 health/event aggregate 與 caregiver context；local Nemotron 負責 current multimodal observation。任何 cloud analysis 都必須經 Privacy Aggregator，不取得完整生活 raw stream。

## 1. 呼叫邊界

MiniMax-M3 負責整合健康快照、事件摘要與時間窗統計，輸出結構化觀察、風險候選與建議。它不直接查 SQLite、不持有通知工具、不修改 threshold，也不把輸出當作醫療診斷。

MVP 預設不將完整影片交給 MiniMax。單一事件需要視覺二次判讀時，最多傳必要的事件影格或短窗口，並與健康分析 purpose 分開記錄。

## 2. 輸入摘要

```json
{
  "subject_id": "resident_demo",
  "window": {
    "start": "2026-09-04T00:00:00+08:00",
    "end": "2026-09-04T14:30:00+08:00"
  },
  "health_snapshot": {
    "heart_rate_bpm": 112,
    "spo2_percent": 96,
    "steps": 420,
    "activity": "inactive",
    "measured_at": "...",
    "quality": "valid"
  },
  "event_summary": {
    "fall": {"confirmed": 0, "unresolved": 0},
    "hydration": {
      "confirmed_sessions": 2,
      "estimated_ml": 400,
      "target_ml": 1600,
      "last_at": "..."
    }
  },
  "data_limitations": ["health values are simulated", "hydration volume is estimated"]
}
```

## 3. 輸出 schema

```json
{
  "summary_zh_tw": "目前飲水紀錄低於設定目標，且最近活動量偏低。",
  "risk_level": "normal|watch|elevated|urgent|unknown",
  "reason_codes": ["hydration_below_target", "low_activity"],
  "supporting_facts": [
    {"key": "estimated_hydration_ml", "value": 400, "window": "24h"}
  ],
  "uncertainties": ["飲水量由每次設定容量估算"],
  "recommendations": ["提醒補充水分並持續觀察"],
  "proposed_actions": ["dashboard_reminder"],
  "analysis_window": "24h",
  "schema_version": "health-risk.v1"
}
```

## 4. 成本與快取

- 相同 subject、window、health snapshot hash、event summary hash、prompt version 命中時重用分析。
- 新 confirmed fall、hydration session 或 health scenario 變更時才使相關 cache 失效。
- 自動分析使用短摘要；UI 手動 refresh 可強制新呼叫，但需防連點。
- 保存 token、latency、status、input hash，不在 log 保存 secret。

## 5. Timeout 與降級

- timeout：預設 30 秒，可設定。
- retry：只對 retryable transport／429 錯誤最多重試 2 次，使用 exponential backoff + jitter。
- schema invalid：最多進行一次 repair request；仍失敗則標記 invalid。
- degraded 時本地 SQL 統計與 deterministic reminders 照常運作，UI 顯示 MiniMax 暫不可用。

## 6. 啟動時 Capability Probe

開發第一步以實際 endpoint 驗證：

1. `GET /v1/models` 是否能找到設定的 `MiniMax-M3`。
2. 純文字 structured output。
3. tool calling。
4. image input。
5. video input（非 P0 依賴）。
6. streaming、timeout 與錯誤格式。

Probe 結果保存為本地開發報告，不把未驗證能力寫成 runtime 假設。

