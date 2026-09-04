# 11 · 完整部署與啟動

## 1. Process 清單

| Process | 執行位置 | 必要性 |
|---|---|---|
| Care backend | macOS host | 必要 |
| Qwen3-VL runtime | backend worker 或 local model server | 必要 |
| Mic/VAD/Whisper worker | macOS host | 必要 |
| React frontend | dev server 或 backend static assets | 必要 |
| Telegram update worker | Care backend background task | L3 acknowledgement 必要 |

完整 live 部署通常是 **4 個常駐 OS process**：Care backend、Qwen runtime、audio worker、frontend。Qwen 若作為 backend 內嵌 worker，可降為 3 個；Telegram update worker 與 Setup Service 是 backend background task，不另算 process。

## 2. 使用者啟動

頂層 package manager 使用 Bun。使用者只需執行：

    bun start

這個命令先啟動 Setup／orchestrator，再依已保存設定啟動或檢查其他 process。第一次啟動由 Web Setup Wizard 完成模型、camera、vision loop、MiniMax、Telegram 與風險時間窗設定。

## 3. 內部啟動順序

1. 檢查 model files、media volume、SQLite directory 與 secret variables。
2. 啟動 backend，執行 migration、capability probes 與 RTSP source registration。
3. 啟動 Qwen runtime，完成 warm-up。
4. 啟動 audio worker。
5. 啟動 frontend。
6. 執行 smoke test：status → live frame → vision loop tick → local VLM → SQLite → WebSocket。

## 4. 環境變數

- APP_ENV、DATABASE_PATH、MEDIA_ROOT
- ACTIVE_SOURCE、DEMO_MODE
- RTSP_CAMERA_URL、RTSP_USERNAME、RTSP_PASSWORD
- VISION_LOOP_INTERVAL_MS、VISION_WINDOW_SEC、VISION_MAX_FRAMES
- LOCAL_VLM_MODEL、LOCAL_VLM_QUANTIZATION、WHISPER_MODEL
- MINIMAX_BASE_URL、MINIMAX_API_KEY、MINIMAX_MODEL
- TELEGRAM_BOT_TOKEN、TELEGRAM_ALLOWED_CHAT_IDS、TELEGRAM_POLL_TIMEOUT_SEC

Secret 只放未追蹤的 local environment 或 secret manager；設定範例只能提供 placeholder。

## 5. Health check

API 必須分開回報 database、camera、vision_loop、frame_buffer、microphone、vad、whisper、local_vlm、minimax、telegram、model_store 與 scheduler。

狀態使用 starting、healthy、degraded、unavailable，並附最後成功時間與安全錯誤摘要。

## 6. 關閉與恢復

- Shutdown 時停止接受新 model jobs、完成或取消目前工作、flush SQLite，再停止 source。
- 啟動後將 processing 且逾期的 job 標為 interrupted，依 idempotency policy 重試。
- RTSP、MiniMax、local VLM 或 audio worker 單獨失效不得使 REST 歷史查詢與 Dashboard 整體失效。
- SQLite 寫入使用短 transaction；WAL checkpoint 與備份不能與 realtime critical job 爭用。

## 7. 明確不部署

本版不提供 L4 emergency executor，不自動撥打緊急服務，也不讓模型取得任何等價工具。
