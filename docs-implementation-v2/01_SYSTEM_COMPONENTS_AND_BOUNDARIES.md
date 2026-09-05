# 01 · 系統元件、功能與邊界

> **v3 amendment：** Sensor 不等於產品，Frigate/RTSP/MQTT 可延後。Current multimodal path 使用 2 FPS、5 秒、10 frames + audio 的 Nemotron window；Event Correlator、World State、Unknown、Active Inquiry 與 Privacy Aggregator 是跨元件的共同邊界。

## 1. 建議技術棧

- Monorepo：Node.js/npm workspace（`package.json`）；目前啟動入口為 `npm start`。
- 目前開發啟動亦可分別啟動 frontend、Care backend 與本機 vLLM；其他 JavaScript runtime 只能重用相同 npm scripts 語意。
- Backend：Python 3.10+、FastAPI、Pydantic、SQLite WAL；Python 套件以鎖定的 Python environment 管理。
- Frontend：React、TypeScript、Vite；以 HTTPS 提供 browser camera/microphone permission。
- 即時通訊：`/ws/media` 接收 continuous WebM media，`/ws` 廣播已提交 observation/event；REST 用於命令與歷史查詢。
- Current multimodal runtime：OpenAI-compatible local vLLM，served model 預設為 `nemotron_omni`，實際權重由 `VLLM_MODEL`／vLLM server 決定。
- 影片處理：backend 以 2 FPS、5 秒窗口、10 frames 做取樣；Replay、RTSP、Frigate 是可替換 source adapter。
- NVR：Frigate + go2rtc 為 optional adapter，不是 current VLM path 的必要服務。
- Current audio：browser MediaRecorder 的 audio track 進入同一窗口，backend 轉為 16 kHz mono WAV 送 Omni；Silero VAD/Whisper 為後續 transcript adapter。
- 外部 AI：MiniMax adapter 只接 privacy-aggregated health/event summary；不把 raw continuous stream 當預設輸入。

## 2. Runtime 拓撲

```text
React Dashboard（HTTPS）
   ↕ REST + /ws + /ws/media
FastAPI Care backend（HTTPS）
   ├─ Browser Media Stream Session
   ├─ 2 FPS × 5 秒 Window Sampler
   ├─ Nemotron Omni vLLM Adapter（HTTP localhost）
   ├─ Event Correlator / Event State Machines
   │    ├─ existing: fall / hydration
   │    └─ exception: sound / person / object recognition_events
   ├─ World State（Known / Unknown / Hypothesis）
   ├─ Context Sentinel / Resident Interaction / Caregiver Agent（logical units）
   ├─ Deterministic Policy Gateway
   ├─ Privacy Aggregator → MiniMax Adapter（後續）
   ├─ Optional Frigate / RTSP / MQTT Adapter
   ├─ SQLite Event Ledger / Memory Repository
   └─ Realtime Broadcaster
```

## 3. 元件責任矩陣

| 元件 | 負責 | 不負責 | 主要輸出 |
|---|---|---|---|
| Browser Media Session | 權限、continuous stream、session status | 事件語意、永久保存 raw media | media chunks、source status |
| Source Manager | 統一 browser、replay、RTSP、Frigate lifecycle | 事件語意 | frame/audio packet、source status |
| Audio Window Sampler | 對齊 5 秒 audio、PCM/WAV metadata | 風險判斷、永久保存原始音訊 | audio window、audio status |
| Frame Sampler | 2 FPS 抽幀、縮放、保留短窗口 | 判斷跌倒或喝水 | 10 sampled frames、window ref |
| Local VLM Adapter | 將 frame + audio window 轉為結構化 observation | 通知、健康建議、直接決定 action | `MultimodalObservation` |
| Event Correlator / State Machine | 先套既有 event contract，再落例外 recognition event | 自由文字推理 | event transition、recognition event |
| World State | 聚合 Known、Unknown、Hypothesis 與 coverage | 直接執行通知 | state snapshot、information gap |
| SQLite Repository | transaction、查詢、聚合、idempotency | 業務判斷 | persisted records、summary |
| Agent Orchestrator | 依事件依序呼叫 logical agents | 自行繞過 policy | typed agent results |
| Main Agent | 以 Omni 產生 bounded judgment、facts、unknown 與 proposed action | 直接執行 action、把 candidate 升格 | `MainAgentJudgment`、`agent_runs` |
| MiniMax Adapter | API 呼叫、timeout、schema validation、usage 紀錄 | 直接通知、任意 SQL | validated cloud result |
| Policy Gateway | 依設定與資料狀態決定允許動作 | 使用 LLM 自由文字當規則 | policy decision |
| Realtime Broadcaster | 將已提交資料推送前端 | 作為資料真相來源 | typed WebSocket messages |
| Dashboard | 顯示、查詢、操作 Demo | 保存 canonical state、持有 API key | user commands |
| Setup Service | prerequisites、模型 catalog、下載／驗證／啟用與 integrations 測試 | 執行任意 shell、接受任意下載 URL 或路徑 | setup state、download jobs |

## 4. 邊界原則

- SQLite 是 canonical state；WebSocket 只是通知。斷線重連後，前端必須用 REST 補抓現況。
- 模型輸出是 observation，不是 confirmed event。只有 state machine 可確認事件。
- Agent 可以建議風險與動作，但只有 Policy Gateway 能核准 `alert` 或 `speak`。
- Nemotron Omni 與 MiniMax adapter 都可替換；domain code 不依賴 SDK response object。
- 所有時間使用含時區 ISO 8601；影片內時間另存 `source_offset_ms`。
- MVP 使用單 process 與 bounded async queues；不得為了架構圖先拆 microservices。
- vLLM、backend、frontend 是目前主要 process；Frigate、MQTT、RTSP 是不同 process／adapter，但 domain agents 不是額外服務。
- Long-term Observer 使用 repository 的固定唯讀 snapshot；寫入 finding 時走獨立 transaction。
- 前端 Setup Wizard 只能呼叫受限 backend API；模型下載與 filesystem 操作一律由 backend 執行。

## 5. 資源界線（目前本機 GPU runtime）

- Local VLM concurrency 固定為 1。
- 預設只保留最近 15 秒的記憶體 frame window。
- Current baseline 為 2 FPS、5 秒、10 frames + 5 秒 audio；參數由 `VLLM_SAMPLE_FPS`、`VLLM_WINDOW_SECONDS`、`VLLM_WINDOW_FRAMES` 控制。
- 主模型為本機 vLLM served `nemotron_omni`，UI 與 model call record 必須顯示實際 model ID；不得以文件中的歷史候選模型冒充目前 runtime。
- Background aggregation 不可與 realtime VLM 同時大量佔用 unified memory。
- Observation 與 Main Agent 共用 vLLM concurrency budget；超過 pending limit 時丟棄窗口並寫入 backpressure log，不以空結果冒充完成。
