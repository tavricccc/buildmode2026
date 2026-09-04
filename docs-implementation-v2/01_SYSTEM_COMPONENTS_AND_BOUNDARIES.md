# 01 · 系統元件、功能與邊界

## 1. 建議技術棧

- Monorepo 與 JavaScript package manager：Bun workspace。
- 唯一使用者啟動命令：bun start。
- Backend：Python 3.12、FastAPI、Pydantic、SQLAlchemy 或 SQLModel、SQLite WAL；Python 套件以鎖定的 Python environment 管理，由 Bun script 統一 orchestration。
- Frontend：React、TypeScript、Vite，由 Bun 安裝與啟動。
- 即時通訊：WebSocket；REST 用於命令與歷史查詢。
- 視覺 runtime：`mlx-vlm` 優先；模型與量化版本由環境變數指定。
- 影片處理：OpenCV 或 PyAV。Replay source 與 RTSP source 實作相同介面。
- NVR：Frigate Docker + go2rtc；Apple Silicon detector 以 host process 運行並透過 ZMQ 連入容器。
- 音訊：host mic capture、Silero VAD、MLX Whisper adapter。
- 外部 AI：OpenAI Python SDK 或相容 HTTP client，endpoint 與 model 不寫死。

## 2. Runtime 拓撲

```text
React Dashboard
   ↕ REST + WebSocket
FastAPI Application
   ├─ Source Manager ─ FrigateAdapter / RtspSource / ReplaySource
   ├─ Audio Manager ─ MicCapture / SileroVAD / WhisperAdapter
   ├─ Frame Sampler
   ├─ Local Vision Adapter ─ Qwen-VL
   ├─ Event State Machines ─ fall / hydration
   ├─ Agent Orchestrator
   ├─ Deterministic Policy Gateway
   ├─ MiniMax Adapter
   ├─ SQLite Repository
   └─ Realtime Broadcaster
```

## 3. 元件責任矩陣

| 元件 | 負責 | 不負責 | 主要輸出 |
|---|---|---|---|
| Source Manager | 統一 replay、RTSP、Frigate 輸入生命週期 | 事件語意 | frame packet、source status |
| Audio Manager | 收音、VAD segmentation、ASR job 與 transcript buffer | 風險判斷、永久保存原始音訊 | speech segment、transcript |
| Frame Sampler | 依設定抽幀、縮放、保留短窗口 | 判斷跌倒或喝水 | sampled frame、window ref |
| Local Vision Adapter | 將窗口轉為結構化視覺 observation | 通知、健康建議、直接寫事件統計 | `VisionObservation` |
| Event State Machine | 依 observation、時間與 cooldown 建立／更新事件 | 自由文字推理 | `EventRecord` transition |
| SQLite Repository | transaction、查詢、聚合、idempotency | 業務判斷 | persisted records、summary |
| Agent Orchestrator | 依事件依序呼叫 logical agents | 自行繞過 policy | typed agent results |
| MiniMax Adapter | API 呼叫、timeout、schema validation、usage 紀錄 | 直接通知、任意 SQL | validated cloud result |
| Policy Gateway | 依設定與資料狀態決定允許動作 | 使用 LLM 自由文字當規則 | policy decision |
| Realtime Broadcaster | 將已提交資料推送前端 | 作為資料真相來源 | typed WebSocket messages |
| Dashboard | 顯示、查詢、操作 Demo | 保存 canonical state、持有 API key | user commands |
| Setup Service | prerequisites、模型 catalog、下載／驗證／啟用與 integrations 測試 | 執行任意 shell、接受任意下載 URL 或路徑 | setup state、download jobs |

## 4. 邊界原則

- SQLite 是 canonical state；WebSocket 只是通知。斷線重連後，前端必須用 REST 補抓現況。
- 模型輸出是 observation，不是 confirmed event。只有 state machine 可確認事件。
- Agent 可以建議風險與動作，但只有 Policy Gateway 能核准 `alert` 或 `speak`。
- Qwen-VL 與 MiniMax adapter 都可替換；domain code 不依賴 SDK response object。
- 所有時間使用含時區 ISO 8601；影片內時間另存 `source_offset_ms`。
- MVP 使用單 process 與 bounded async queues；不得為了架構圖先拆 microservices。
- Frigate、Apple Silicon detector 與 backend 是不同 OS process，但 domain agents 不是額外服務。
- Long-term Observer 使用 repository 的固定唯讀 snapshot；寫入 finding 時走獨立 transaction。
- 前端 Setup Wizard 只能呼叫受限 backend API；模型下載與 filesystem 操作一律由 backend 執行。

## 5. 資源界線（M4 16GB）

- Local VLM concurrency 固定為 1。
- 預設只保留最近 15 秒的記憶體 frame window。
- 先以 1 FPS、最長 8-frame window benchmark；數值可設定，不寫死在程式。
- 主模型固定為 `Qwen3-VL-8B-Instruct` 4-bit。啟動時先做記憶體與延遲檢查；若無法在可接受時間內穩定完成，才降至 4B，且 UI 與 model call record 必須顯示實際使用模型。
- Background aggregation 不可與 realtime VLM 同時大量佔用 unified memory。
