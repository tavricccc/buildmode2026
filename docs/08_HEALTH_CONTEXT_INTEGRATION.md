# 08 · Health Context Integration

## 1. 目的與邊界

Health context 用來補充 event understanding、personal baseline、coverage 與照護偏好，不用來自動診斷。Agent 每次只取得與 situation 相關的最小 snapshot；原始外部資料、canonical context 與輸出摘要分開保存。

## 2. Context snapshot

```json
{
  "subject_id": "resident_demo",
  "at": "2026-09-04T17:32:00+08:00",
  "known": {"activity": "inactive"},
  "unknown": ["current_zone"],
  "health": {"heart_rate_bpm": 78, "spo2_percent": 97, "quality": "valid"},
  "care_preferences": {"default_mode": "silent", "reminder_limit_per_day": 1},
  "coverage": {"camera": 0.9, "audio": 0.8}
}
```

`simulated`、`stale`、`unobservable` 必須顯式保留。缺健康資料不能推出低風險。

## 3. Normalization

流程：`authorized source → connector → identity/time/unit normalizer → canonical context → fixed snapshot → Agent query`。需處理時區、裝置時鐘、重複、缺值、撤回、延遲、source priority 與 coverage；解析錯誤要進 data-quality log。

## 4. Watchlist 與 uncertainty

Watchlist 是觀察策略。每項包含 origin（human/policy/agent_suggested）、窗口、資料源、confidence、trigger、stop condition、審核狀態與 privacy level。Agent-suggested item 只能是 candidate，不可直接成為 emergency rule。

## 5. Active Inquiry context

Sentinel 要能提出「值得知道但目前不知道」的 gap，例如 `items_added_to_fridge=unknown`、`current_location=unknown`。只有 value、urgency、consent、interruptibility 與 channel 都通過 policy，Interaction Agent 才能詢問；回答以 `resident_confirmed` provenance 寫回 memory。

## 6. 同意與最小化

影像、音訊、逐字稿、health、分享給 caregiver、通知與詢問是可分項撤回的 consent。Caregiver 預設讀 aggregate；Level 3 raw evidence 需明確事件 scope。不得把服務需求、疾病名稱或量表分數由模型直接生成為事實。

## 7. current status

目前 Fake Health snapshot、事件 aggregate 與基本 coverage 已有實作；真實 HealthKit/FHIR/wearable connector、context compiler、preference/interruptibility store 與完整 privacy aggregation 仍是後續階段。
