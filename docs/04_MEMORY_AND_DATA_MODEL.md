# 04 · Memory 與資料模型

## 1. 目的

資料模型必須回答三件事：發生了什麼、系統如何知道、現在允許採取什麼行動。Raw Evidence、Fact、Observation、Interpretation、Risk 與 Hypothesis 必須分層，避免一次模型輸出污染長期病史。

## 2. 記憶層與資料生命週期

| 類型 | 定義 | 來源 | 寫入規則 | 留存方向 |
|---|---|---|---|---|
| Raw Evidence | 影片、音訊、frame、原始 sensor payload | Camera、Mic、Wearable、Frigate | 不可變，使用 hash | 短 TTL，依同意與政策 |
| Sensor Event | 感測器觸發的事件候選 | Frigate、device gateway | 可追加 evidence，不覆寫 | 事件留存政策 |
| Observation | 可追溯的單模態或資料事實描述 | ASR、VLM、Audio、FHIR、人工 | 版本化，不能加入未觀察內容 | 依照護價值 |
| Interpretation | 對多筆 Observation 的語意組合 | Event Understanding | 必須引用 supporting refs | 可重算、保留版本 |
| Risk Assessment | 對當前風險與不確定性的評估 | Risk Agent、policy inputs | 不等同診斷 | 需可審計 |
| Intervention | 實際允許、發送與結果 | Policy、Channel、人工 | 狀態追加，不重複執行 | 依責任與稽核要求 |
| Hypothesis | 尚未確認的趨勢或模式假設 | Observer、Consolidation | 可反駁、可衰減、不可當 Fact | 直到確認／反證／封存 |
| Baseline | 個人、時段、情境的歷史分布 | Observer、健康資料 | 版本化，有資料窗口 | 長期摘要 |
| Watchlist | 值得觀察的條件與問題 | Watchlist Agent、人工、政策 | candidate/active 分離 | 保留變更歷史 |
| Medical Context | 病史、用藥、過敏、CarePlan、FHIR 索引 | 授權外部來源、人工 | Agent 只讀或提出修改 | 依來源撤回與保留政策 |

~~舊版原型曾把 transcript 當成一般長期記憶保存。~~ 新方案將 transcript 視為 conversation-window evidence：短期存在、到期刪除；只有長輩明確確認的內容，才轉成帶來源的 Fact、Preference 或 Reminder。

Caregiver projection 是另一個資料層：由 detailed events 經 purpose、角色與 payload level 過濾後產生，不反向修改原始 Event Ledger。

## 3. 共用欄位

所有核心實體至少包含：

```text
id, subject_id, occurred_at, recorded_at,
source_ref[], provenance[], confidence, confidence_method,
data_quality, schema_version, created_by, model_version,
policy_version, correlation_id, supersedes_id?,
retention_class, consent_scope, created_at
```

`occurred_at` 是現象發生時間，`recorded_at` 是系統收到時間；離線設備與跨時區資料不可混用。`source_ref` 指向 evidence、外部資料或人工操作；`provenance` 說明轉換鏈。

## 4. Fact 與 Hypothesis 分離

Fact 只表示已被系統定義為可信的來源資料或經人工確認的照護資訊。Hypothesis 代表模型或 Observer 的暫時解釋，例如「近 14 天夜間離床頻率高於個人基線」。

Hypothesis 必須包含：

- `statement`：可被反駁的敘述，而非診斷名稱。
- `evidence_refs`：支持與反對的事件、資料窗口或人工回饋。
- `confidence`：模型在當前資料上的信心。
- `time_window` 與 `baseline_version`。
- `status`：proposed、active、confirmed、rejected、expired。
- `confirmation_required`、確認者與確認時間。
- `next_test`：下一次要觀察的資料或條件。

人工確認不刪除原始 Hypothesis；系統新增 `confirmed_fact` 或 `context_update`，並以 `supersedes_id` 保留關係。

## 5. 主要資料契約

### Observation

```json
{
  "id": "obs_video_01",
  "type": "observation",
  "subject_id": "resident_001",
  "event_id": "evt_20260904_000123",
  "claim": "person posture appears horizontal",
  "modality": "video",
  "evidence_refs": ["object://evidence/clip.mp4#t=12.4"],
  "confidence": 0.64,
  "data_quality": {"clock_sync_ms": 42, "missing": false},
  "provenance": [{"source": "local_vlm", "model_version": "vlm-0.3"}],
  "schema_version": "observation.v1"
}
```

### Risk Assessment

```json
{
  "id": "risk_01",
  "type": "risk_assessment",
  "event_id": "evt_20260904_000123",
  "level": "high",
  "uncertainty": "medium",
  "reason_codes": ["impact", "floor_posture", "no_recovery_observed"],
  "supporting_refs": ["obs_video_01", "obs_audio_01"],
  "policy_candidates": ["policy_check_in_v2", "policy_caregiver_alert_v1"],
  "model_version": "risk-local-0.2",
  "policy_version": "policy-set-7",
  "schema_version": "risk_assessment.v1"
}
```

### Watchlist

Watchlist item 必須標記 `origin`（human、policy、agent_suggested）、`status`（candidate、active、paused、expired）、觀察窗口、觸發條件、禁止的升級行為與審核資訊。`agent_suggested` 不能直接是 active L4 policy。

## 6. Provenance、confidence 與版本

Confidence 不是疾病機率，也不是行動授權。每次模型或規則重跑都建立新版本，記錄輸入證據 hash、model ID/version、prompt 或 policy version、時間、延遲、輸出 schema、人工回饋與資料品質。跨資料源合併時，不可丟棄原始來源。

## 7. 寫入與查詢規範

- 大型影音放 object store；Ledger 保存 URI、hash、時間、權限與 TTL。
- 使用 `subject_id + occurred_at + event_id` 做主要查詢索引，使用 `correlation_id` 追踪跨 Agent 工作。
- 所有重要 record append-only；更正用新版本，刪除依 retention policy 產生可稽核 tombstone。
- 每一筆 Observation/Interpretation/Risk 都必須能反查 evidence；不能反查的資料標為 invalid，不得進入介入。
- Context snapshot 固定查詢當下版本，避免同一事件因後來脈絡改變而無法重現。
