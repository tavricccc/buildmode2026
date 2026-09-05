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

目前實作為同一個 Resident Interaction Agent 的兩個驅動層，而不是兩個互相獨立的 agent：

- **Interaction driver**：接收文字或已同意的語音，透過 allowlist tool 讀取主 Agent 的結構化紀錄，產生短回覆；目前由瀏覽器本機 Web Speech API 朗讀，避免 TTS 先依賴模型。停止、忘記、提醒、確認、重複、澄清與記憶查詢都先落成可稽核 run；明確的使用者要求另寫入 `recognition_events`。
- **Understanding／motivation driver**：週期性讀取事件、主 Agent 摘要、互動紀錄與已確認記憶，輸出「我觀察到……」與「如果我是使用者……」的 hypothesis，以及是否值得主動關心的提案。它不直接讀 raw media、不直接 ASR、不直接 TTS；所有記憶候選都必須人工確認。

兩層共享 agent identity、conversation history 與 memory store，但使用不同 prompt、output schema、觸發器與權限。主動說話預設關閉，只有理解層提出提案，並通過 consent、confidence、stop state 與 cooldown 後，才可交由 interaction driver 發聲。

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

目前先用同一個 Nemotron Omni vLLM 實作 Main Agent。一般 Observation 不會主動叫醒 Main Agent；只有 5 FPS 確認高風險事件後，才以獨立 task 非同步執行 Focus／Main Agent 判斷。所有影像與文字模型 request 共用 bounded semaphore；`VLLM_MAX_CONCURRENCY` 控制同時 request 數，媒體窗口與 Main Agent 都有 pending 上限。

Main Agent 收到 2 FPS、10 秒 Focus review、typed Observation、既有 `fall`／`hydration` event、exception `recognition_events` 與最近 12 筆事件摘要，依固定順序產生 `MainAgentJudgment`：

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

## 7.1 10 分鐘小節與 1 小時摘要

週期摘要器仍屬主 Agent 的文字工作，但不讀 raw media，也不在高風險期間搶占 Focus 資源。它以 `AGENT_SUMMARY_INTERVAL_SECONDS=600` 產生 10 分鐘小節，以 `AGENT_HOURLY_SUMMARY_INTERVAL_SECONDS=3600` 產生 1 小時紀錄；每次讀取上一個摘要窗口以來的 events、change gates、action-only visual descriptions、time segments、transcripts、Agent judgments 與重要 logs，輸出 `main-agent-period-summary.v1`：

- 全天需要保留的 key events
- 帶時間／offset 的人物或物品 action timeline
- 持續狀態
- Unknown 與資料限制
- risk、confidence、是否需要後續確認

摘要保存於 `agent_period_summaries.summary_type`（`ten_minute`／`hourly`），前端由 `/api/agent/periodic-summaries` 恢復；10 分鐘小節保留「8:00–8:10 人物起身移動一次」或「8:10–8:20 無事件發生」，1 小時紀錄再對一小時動向做保守推測，不直接執行通知或其他外部 action。

## 8. Detail 與 Focus 兩段式影像理解

第一層 Observation 回傳 `change_detected`、`change_confidence`、`change_reasons`、`change_summary` 與 `warning_signal`。即時訊息只輸出 change-only 短述，不重複 scene footnote；完整 normalized Observation 仍保存給事件狀態機與 SQLite 稽核。只有 Observation 提出 `fall`、火災、煙霧、警報或撞擊等高風險候選時，才由預熱的 5 FPS sampler 送出 2 秒滑動窗口，確認是否符合候選事件。

5 FPS 確認為高風險後，立即建立 high-risk state，從 2 FPS buffer 取連續 10 秒做 `focus_review`，並同步讓 Resident Interaction Agent 以住民稱呼發出「還好嗎？是否發生……？」。詢問每 20 秒重複一次，60 秒無回應標示 `confirmed_no_response`；一般住民要求在此期間被阻擋，危急回應仍可進入。Focus 判定疑似不是跌倒時，會把固定大小的 Focus 結果交給可選的雲端 M3 二次確認；目前仍不執行通知或其他外部 action。

如果高風險被人工解除，或本機／雲端確認不成立，系統會從 60 秒 rolling buffer 取回暫存的 Observation windows，批量補齊缺失時段，之後恢復一般 change gate。

當連續 30 秒沒有新的 Observation，系統會從影像 buffer 每 3 秒取一張、共 10 張做一次 quiet probe；只要有新的 Observation，計時就重置。這個 probe 仍是一次模型判斷，不是每張影像各叫一次模型。

Main Agent 不主動處理一般窗口。它另外以 10 分鐘小節與 1 小時摘要讀取事件、Observation 描述、時間片段與 log；摘要格式保留「某時段人物做了什麼／無事件」及一小時動向推測，並在高風險期間暫停，避免摘要和危急判斷互相搶資源。

## 9. Agent 目前與下一階段

目前已具備 VLM Observation、並行 Main Agent judgment、deterministic policy trace、事件候選、SQLite agent run、Resident Interaction 的文字／語音入口與 Dashboard。住民 ASR 對 GMI M3 的實際音訊能力仍需 provider capability probe；沒有可驗證的 transcript 時會 fail closed。尚待完成的是正式 Context Sentinel schema、information-gap evaluator、完整 consent/interruptibility gate，以及 Caregiver privacy summary。
