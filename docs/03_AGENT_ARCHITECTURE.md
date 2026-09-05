# 03 · Agent 架構

## 1. 三個邏輯 Agent

Agent 是同一 backend 內具權限邊界的 logical unit，不是三個獨立模型服務。共用本機 Nemotron 時，仍必須分開 system prompt、context scope、tools、output schema 與 policy。

## 2. Context Sentinel / Situation Awareness

責任：回答「現在知道什麼、不知道什麼、哪個缺口值得補」。

輸入：correlated situation、最近 observations、source quality、個人 baseline、care preferences。

輸出：Known facts、Unknown fields、Hypothesis、information gap、value of asking、urgency、suggested next action。

禁止：把模型猜測寫成 Fact、直接通知、修改 threshold、取得無關 raw media。

## 3. Resident Interaction Agent

這不是 AI 伴侶；它是日常助理、提醒與必要的短對話。狀態預設為：

```text
SILENT → OBSERVE → SILENT / ASK / REMIND / WARN / CHAT → SILENT
```

任何 `ASK` 都要檢查 uncertainty value、urgency、interruptibility、最近互動、resident preference、consent 與 cooldown。`expect_reply=true` 才開啟對話窗；回答只存必要摘要，原始 transcript 依 TTL 清除。

## 4. Caregiver Agent

只讀 Privacy Aggregator 輸出的日／週摘要、baseline comparison、finding 與必要證據索引。輸出接近照護紀錄：活動、飲食、生活節律、coverage、需要人工確認的地方。不得從缺資料推出「沒有發生」。

## 5. Shared tools

| Tool | 可做 | 不可做 |
|---|---|---|
| `state_get/update` | 讀寫版本化 World State | 覆寫 provenance 或政策 |
| `memory_search/save/update/invalidate` | 依 consent 寫 semantic/scheduled memory | 將 hypothesis 當永久 fact |
| `health_read` | 讀固定 snapshot/aggregate | 任意 SQL、診斷 |
| `frontend_update` | 更新 Known/Unknown/Next action/timeline | 成為 canonical state |
| `speak` | 在 policy 核准後短句輸出 | 自行開啟對話窗 |
| `notify` | 呼叫已核准 channel/recipient | 擴大收件人或升級 L4 |

每次 tool call 保存 agent、tool、arguments hash、result、status、latency、idempotency key。

## 6. 協作順序

```text
Event Correlator
  → Context Sentinel
  → Event Understanding / Observation
  → Risk + Attention Policy
  → Resident Interaction or Caregiver Agent
  → Memory / Dashboard / delivery trace
```

Context Sentinel 不一定每次都叫 Resident Interaction；`SILENT` 是有效輸出。

## 7. Current Main Agent：分析與判斷流程

目前先用同一個 Nemotron Omni vLLM 實作 Main Agent。每個完成的 multimodal window 會以獨立 task 非同步執行，與其他窗口並行，但所有 Omni request 共用 bounded semaphore；`VLLM_MAX_CONCURRENCY` 控制同時 request 數，`VLLM_MAX_PENDING_WINDOWS` 防止排隊無界增長。

Main Agent 收到 10-frame + audio window、typed Observation、既有 `fall`／`hydration` event、exception `recognition_events` 與最近 12 筆事件摘要，依固定順序產生 `MainAgentJudgment`：

1. `observed_facts`：只列出影像／音訊可直接支持的事實。
2. `temporal_assessment` + `situation_phase`：說明跨 frame 變化，不以單張 `lying` 確認跌倒。
3. Existing-first mapping：先判斷是否支持既有 event state，再處理 sound/person/object/scene 例外。
4. `unknowns`／`hypotheses`／`uncertainty_reasons`：保留不可觀測與待確認部分。
5. 提出 risk、attention、`proposed_action` 與 `next_action`；模型 action 只是建議，不是工具呼叫。

接著由 `MainAgentPolicy` deterministic 裁決。它計算：

```text
attention_score = 15 × model_confidence
               + 10 × visual_confidence
               + 75 × event_signal
               - uncertainty_penalty
```

`event_signal = event_confidence × event_type_weight`；例行 `person_present`／家電事件權重低，`fall`／`impact`／`alarm`／`fire` 權重高。正常 observation 即使信心很高，只要沒有值得注意的 event signal，仍應落在低分並保持 `silent`。再套用 confidence/evidence/existing-first gates，以及 fall recovery deadline、fire/smoke/alarm、distressed audio 等 critical override。低信心或證據不足必須 `insufficient_data → silent`；只有政策通過才可得到 `observe`、`ask`、`remind` 或 `dashboard_alert`。目前只保存與顯示判斷，`action_executed=false`，不自動執行外部通知。

每次執行保存 `agent_runs`、`model_calls`、policy gates、score components、reasons、latency、model/prompt/schema/config version 與 dedup key，前端可由 `/api/agent/runs` 查詢。

## 8. Detail 與 Focus 兩段式影像理解

第一層 observation 回傳 `change_detected`、`change_confidence`、`change_reasons` 與 `warning_signal`。Backend 同時 deterministic 檢查 person 出現／離開、新 memorable audio/candidate、既有事件狀態與新 persisted event；這些欄位只作觸發 gate，不等於最終警告。觸發後由預熱的 5 FPS sampler 送出 2 秒滑動窗口，產生並保存 `visual_descriptions`；Main Agent 先用描述判斷是否需要深入。

只有 Main Agent 回傳 `needs_further_attention=true` 時，才從 2 FPS buffer 取連續 10 秒做 `focus_review`，對照先前 descriptions、scene footnote、events、transcript 與 memory。Focus review 的 `abnormal`／`warning_level` 才形成 warning proposal；目前仍不執行通知或其他外部 action。

## 9. Agent 目前與下一階段

目前已具備 VLM Observation、並行 Main Agent judgment、deterministic policy trace、事件候選、SQLite agent run 與 Dashboard。尚待完成的是正式 Context Sentinel schema、information-gap evaluator、Resident Interaction 的 consent/interruptibility gate，以及 Caregiver privacy summary；這些完成後才進入完整 Gate 3 Demo。
