# Care Agent 完整程式實作文件 v2 · v3 Amendment

版本：2026-09-04  
current product direction：**Ambient Care Agent / Partial Observability / Active Inquiry**

## 產品核心

本系統不是「看著老人」的 AI，而是在有限資訊下管理 Known、Unknown、Hypothesis、Attention 與 Next Action 的 local-first 照護 Agent。Camera、microphone、Frigate、IoT、手機與 wearable 都是可替換的 sparse sensors；共享核心是 Event Normalizer、World State、Event Ledger、Memory、Policy 與 Privacy Aggregator。

## Current runtime

目前先跳過 Frigate，使用本機 Nemotron Omni vLLM：

```text
HTTPS browser MediaStream
  → WSS /ws/media continuous WebM (camera + microphone)
  → backend in-memory sampler
  → 2 FPS × 5 seconds = 10 ordered frames + 5 seconds 16 kHz mono audio
  → vLLM served model nemotron_omni
  → typed Observation + event_candidates
  → existing fall/hydration state machine or recognition_events exception
  → SQLite /ws Dashboard
```

Browser media 不會變成 screenshot polling；音訊只在單次 multimodal request 期間以 local temporary WAV URI 提供給 Omni，完成即刪除。

Current video retention 是 rolling 60 秒。第一層 2 FPS/5 秒輸出 change gate；只有 Observation 提出高風險候選時，才由預熱的 5 FPS sampler 產生 2 秒 high-risk confirmation，接著才取 2 FPS/10 秒 Focus review。普通 Observation 只送 change-only 短述；完整 normalized record 留在 SQLite。

## 文件順序

1. [產品範圍與完成定義](00_SCOPE_AND_DEFINITION_OF_DONE.md)
2. [系統元件、功能與邊界](01_SYSTEM_COMPONENTS_AND_BOUNDARIES.md)
3. [事件、Agent 與 Policy 契約](02_EVENT_AGENT_AND_POLICY_CONTRACTS.md)
4. [跌倒、喝水與多模態窗口](03_VISION_FALL_AND_HYDRATION.md)
5. [SQLite 資料模型](04_SQLITE_DATA_MODEL.md)
6. [Backend API 與即時通訊](05_BACKEND_API_AND_REALTIME.md)
7. [World Context Dashboard](06_WEB_FRONTEND.md)
8. [MiniMax/Privacy Aggregation](07_MINIMAX_HEALTH_AND_RISK.md)
9. [實作順序與驗證](08_IMPLEMENTATION_AND_VERIFICATION.md)
10. [Live Media、Frigate 與 Audio adapters](09_LIVE_MEDIA_FRIGATE_AND_AUDIO.md)
11. [Long-term Observer](10_LONG_TERM_OBSERVER.md)
12. [部署與 Operations](11_DEPLOYMENT_AND_OPERATIONS.md)
13. [Telegram L3](12_TELEGRAM_L3_NOTIFICATION.md)
14. [Setup 與 Model Management](13_SETUP_AND_MODEL_MANAGEMENT.md)

## Existing-first contract

- `fall`、`hydration` 保持既有 event 欄位與 state machine。
- sound/person/object/scene 只有在既有事件無法表達時才用 `event_candidates`/`recognition_events`。
- VLM 不可直接把 candidate 變成 confirmed action；confidence、cross-window evidence、coverage、consent 與 policy 都必須通過。
- `UNKNOWN`、`unobservable`、`insufficient_data` 與 `SILENT` 都是合法產品結果。
- 若 Omni 判定有清楚 speech，才保存有 TTL 的 `speech_transcript`；不清楚語音不得猜測補字。

## 優先級與未完成項

目前 local multimodal observation、exception event contract、SQLite、WSS dashboard 與 basic health/observer 已可運作。下一個 Gate 2b 項目是 Context Sentinel World State、information-gap/Active Inquiry、Default Silent/Interruption Budget、VLM event → Policy/Alert，以及受限 Silero VAD/Whisper conversation window。Gate 3 再做 caregiver aggregate、personal baseline、connector、重連與完整正負例 E2E。

目前新增 Main Agent vertical slice：只有高風險 Focus review 完成後才以獨立 task 交給流程模型，可在 `VLLM_MAX_CONCURRENCY` 內並行。它產生 `MainAgentJudgment`（facts、時序、existing-first mapping、unknown、hypothesis、risk、attention、next action），再由 deterministic `MainAgentPolicy` 計算 attention score 與 fail-closed final action。結果保存於 `agent_runs`，並由 `/api/agent/runs`、`agent.analysis.*` WebSocket 訊息與 Dashboard 顯示。另有 10 分鐘小節與 1 小時摘要讀取 logs／events／descriptions／segments，保存 `main-agent-period-summary.v1` 到 `agent_period_summaries.summary_type`。

## 安全邊界

Agent 只能讀授權 context、固定大小 aggregate 與 scoped evidence；不能任意 SQL、讀完整 raw media、修改 threshold 或啟動 L4。Caregiver 預設只看到 privacy-aggregated summary。這是照護輔助與事件治理架構，不是診療系統。
