# 01 · 系統元件、技術棧與邊界

## 建議技術棧

- Bun workspace；Python 3.12 FastAPI/Pydantic/SQLAlchemy 或 SQLModel/SQLite；React/TypeScript/Vite。
- Video：FFmpeg + OpenCV 或 PyAV，RTSP decode、JPEG preprocessing、AMD/NVIDIA/CPU hardware decode。
- Model Gateway：OpenAI SDK 或相容 HTTP client。
- Local runtime：受版本鎖定、能提供 OpenAI-compatible API 的 llama.cpp server、vLLM 或其他 catalog runtime；實際選擇按 model/OS/GPU probe。
- Cloud：任意通過 capability probe 的 OpenAI-compatible endpoint。

禁止把 `mlx`、`mlx-vlm`、`mlx-whisper`、Metal 或 vendor SDK設為必要 domain dependency。

## Runtime 拓撲

```text
React Dashboard ↔ FastAPI
  ├─ Source/Audio Managers
  ├─ Frame/PCM bounded buffers
  ├─ Vision Loop / Event State Machines
  ├─ Model Gateway ─ OpenAI-compatible API
  │                  ├─ local runtime supervisor (AMD/NVIDIA/CPU)
  │                  └─ cloud endpoint
  ├─ Agent Orchestrator / Policy Gateway
  ├─ SQLite / Realtime Broadcaster
  └─ Setup, Installer & Settings Service
```

## 邊界

- Model output 是 observation，不是 confirmed event；只有 deterministic state machine 能確認事件。
- Local/cloud response 都先轉成內部 schema，SDK/runtime私有物件不得進 domain layer。
- Vision、transcription、analysis、speech/embedding slots 可各自選 endpoint/model。
- AMD/NVIDIA/CPU 差異只在 installer/launcher 和 media decode adapter；業務邏輯只看 capabilities/health。
- Frame/audio queues 有界；cloud upload 顯示目的地、限制 bytes/rate；local runtime 顯示 RAM/VRAM/device。
- SQLite 是 canonical state，WebSocket 僅做 notification/invalidation。

## 設定分類

| 類別 | 前端能力 | 例子 |
|---|---|---|
| `ui_editable` | 讀、改、測試、套用、回滾 | endpoint/model、runtime/device、interval、threshold、retention |
| `secret_write_only` | configured 狀態、覆寫／清除 | API key、RTSP password、Bot token |
| `host_managed` | 只顯示狀態與說明 | bind、DB/media root、secret store、GPU driver |

除 host bootstrap/security 外，不要求使用者手改 `.env`。環境變數只作初始預設或 emergency override。

Vision concurrency 預設 1，最多一個 running 和一個 latest pending。Loop 送出的是短影片片段而非影格集合：P0 為 5 秒片段 @ 2fps，基準心跳 15 秒、變化或 suspect 時 5 秒，皆可從前端調整（見 `03`）；cloud 顯示 requests/hour，local 顯示 benchmark 與 resource pressure。
