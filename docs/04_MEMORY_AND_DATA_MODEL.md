# 04 · Memory 與資料模型

## 1. 三層記憶

```text
Event Ledger       發生過什麼、來源、時間、信心、證據
Semantic Memory    值得長期記住的偏好、習慣、已確認生活資訊
Scheduled Memory   未來何時再檢查、提醒或詢問
```

三者不可混成一個 vector store。Event Ledger 是可回溯的 canonical history；semantic/scheduled memory 必須有來源事件、版本、同意與失效條件。

## 2. Observation layer

Observation 是模型、sensor、人工或 health adapter 對當下資料的結構化描述，不是 Interpretation。Nemotron multimodal observation 盡量沿用既有 visual/audio fields：

```json
{
  "person_visible": true,
  "posture": "sitting",
  "vertical_transition": "none",
  "near_floor": false,
  "drink_container": "none",
  "drinking_motion": false,
  "audio_present": true,
  "audio_events": ["door_knock"],
  "speaker_emotion": "neutral",
  "event_candidates": [],
  "confidence": 0.82,
  "uncertainty_reasons": []
}
```

`event_candidates` 只有在既有 `fall`／`hydration` 無法表達的 sound/person/object/scene 例外才使用。

## 3. Known / Unknown / Hypothesis

```json
{
  "known": [{"key": "last_observed_zone", "value": "kitchen", "confidence": 0.84}],
  "unknown": [{"key": "current_zone", "reason": "resident left camera view"}],
  "hypotheses": [{"statement": "resident may have stored groceries", "confidence": 0.31}],
  "next_action": "silent"
}
```

Unknown 不能被記憶成「沒有」。Hypothesis 必須引用 supporting observations，並有 expiry/review condition。

## 4. Event fields

既有 `events` 欄位優先：`id`、`subject_id`、`event_type`、`status`、`occurred_at`、`ended_at`、`confidence`、`attributes_json`、`model_call_id`、`dedup_key`、`schema_version`、`created_at`、`updated_at`。窗口資訊、audio、uncertainty、privacy level 與 hypothesis 放在 `attributes_json`，不任意複製另一套 event envelope。

只有 exception recognition event 才使用 `recognition_events`，欄位形狀仍保持相同語意：id、subject、type、domain、label、status、time、confidence、attributes、window、model call、dedup。

住民互動中的明確要求（詢問、提醒、確認、澄清、重複、停止、忘記／刪除、記憶查詢、求助）也以 `event_type=user_request` 寫入 `recognition_events`，`domain=resident_interaction`。事件只代表「使用者提出了要求」，`action_executed=false`；實際提醒、刪除、通知或其他行動仍須通過後端 policy。普通寒暄與無法辨識的語句不建立要求事件。

## 5. Provenance 與 retention

- 每筆 Observation 反查 `evidence`、window offsets、model、prompt/schema version。
- 原始 browser media 不進 SQLite；VLM audio 暫存 WAV 只供單次 request，完成即刪除。
- transcript 只在明確 consent/conversation window 內存在，TTL 到期移除內容。
- semantic memory 不能覆寫原始事件；更新建立新 version，保留 invalidation reason。
- Caregiver 讀 aggregated summary；raw Level 3 evidence 必須逐事件、逐權限核准。
- Main Agent judgment 另存 `agent_runs`：包含 input context、analysis、policy gates、score components、decision、model call、latency、config version 與 dedup key；`action_executed=false` 才表示目前沒有執行外部 action。
- `scene_contexts` 保存每個 camera session 的前 5 秒場景註腳；`visual_descriptions` 保存 change/warning 觸發的 5 FPS 2 秒描述；`focus_reviews` 保存 2 FPS 10 秒二次檢查。
- `time_segments` 保存 Main Agent 對無警告時間段的 observed actions、not observed actions 與 uncertainty。
- rolling raw WebM 僅保留最近 60 秒，資料表只保存 path、retention 與 metadata；一般 Main Agent 不取得 raw media。

## 6. 範例：冰箱事件

```text
fridge_open → person_near_fridge → bag_detected → fridge_closed
```

若模型辨識不到內容，保存：`possible_grocery_storage`、`items=unknown`、confidence=0.31、information gap。若 policy 判定值得知道，Interaction Agent 在可打擾時詢問；居民回答後才建立 `food_added` semantic memory，並標示 `source=resident_confirmed`、`estimated_use_window`，不偽造 expiry date。

## 7. 查詢原則

Agent 只能呼叫固定參數函式，不取得任意 SQL。每個查詢都帶 subject、time window、privacy scope；缺 coverage 以 `unobservable` 返回。任何不能反查 provenance 的資料標記 invalid，不進 intervention。
