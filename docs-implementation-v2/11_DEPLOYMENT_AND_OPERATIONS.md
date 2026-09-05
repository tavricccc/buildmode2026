# 11 · 完整部署與啟動

> **v3 amendment：** Current deployment 可不啟動 Frigate：vLLM `8000`、Care backend HTTPS `8002`、frontend HTTPS `5173`。Frigate/MQTT/RTSP 為可選 profile；啟動順序先確認 local VLM、DB、WSS 與 privacy boundary。

## 1. Process 清單

| Process | 執行位置 | 必要性 |
|---|---|---|
| Nemotron Omni vLLM | local WSL/host model server | current multimodal P0 必要 |
| Care backend | local host | current P0 必要；HTTPS `8002` |
| React frontend | Vite dev server | current P0 必要；HTTPS `5173` |
| Browser camera/microphone | user browser permission | current P0 input |
| SQLite | Care backend local data path | current P0 必要 |
| Mosquitto MQTT | Docker 或 host | Frigate adapter 啟用時才需要 |
| Frigate + go2rtc | Docker | optional RTSP/NVR adapter |
| VAD/Whisper worker | local host | deferred speech transcript stage |
| Telegram update worker | Care backend background task | optional L3 acknowledgement |

## 2. 使用者啟動

頂層 package 使用 Node.js/npm scripts。使用者只需執行：

    npm start

這個命令先啟動 Care backend 與 frontend，再依已保存設定檢查其他 process。現行開發驗證也可先啟動本機 Nemotron vLLM、Care backend HTTPS 與 frontend HTTPS；Frigate、MiniMax、Telegram 依 integration 狀態選擇性啟用。

## 3. 內部啟動順序

1. 檢查 Nemotron served model、SQLite directory、TLS certificate 與 secret variables。
2. 確認 vLLM `/v1/models`、multimodal request 與 GPU runtime healthy。
3. 啟動 Care backend，執行 migration、capability probes 與 browser source registration。
4. 啟動 frontend HTTPS，確認 browser origin 可取得 camera/microphone permission。
5. （選用）啟動 MQTT/Frigate/RTSP adapter，等待其獨立 healthy。
6. （後續）啟動 VAD/Whisper、MiniMax、Telegram workers。
7. 執行 smoke test：HTTPS page → camera/mic permission → WSS media → 2 FPS/5 秒 window → Nemotron → SQLite → `/ws`。

## 4. 環境變數

- APP_ENV、DATABASE_PATH、MEDIA_ROOT
- ACTIVE_SOURCE、DEMO_MODE
- VLLM_BASE_URL、VLLM_MODEL、VLLM_API_KEY
- VLLM_SAMPLE_FPS、VLLM_WINDOW_SECONDS、VLLM_WINDOW_STRIDE_SECONDS、VLLM_WINDOW_FRAMES
- TLS_CERT_FILE、TLS_KEY_FILE、FRONTEND_PORT、BACKEND_PORT
- FRIGATE_BASE_URL、FRIGATE_MQTT_HOST、FRIGATE_MQTT_TOPIC（optional）
- FRIGATE_USERNAME、FRIGATE_PASSWORD、RTSP_CAMERA_URL（optional）
- WHISPER_MODEL（deferred）
- MINIMAX_BASE_URL、MINIMAX_API_KEY、MINIMAX_MODEL
- TELEGRAM_BOT_TOKEN、TELEGRAM_ALLOWED_CHAT_IDS、TELEGRAM_POLL_TIMEOUT_SEC

Secret 只放未追蹤的 local environment 或 secret manager；設定範例只能提供 placeholder。

## 5. Health check

API 必須分開回報 database、browser capture、microphone、local_vlm、WSS、frigate_api（optional）、vad（deferred）、whisper（deferred）、minimax、telegram、model_store 與 scheduler。

狀態使用 starting、healthy、degraded、unavailable，並附最後成功時間與安全錯誤摘要。

## 6. 關閉與恢復

- Shutdown 時停止接受新 model jobs、完成或取消目前工作、flush SQLite，再停止 source。
- 啟動後將 processing 且逾期的 job 標為 interrupted，依 idempotency policy 重試。
- Frigate、MiniMax、VAD/Whisper 或 Telegram 單獨失效不得使 REST 歷史查詢與 current browser VLM Dashboard 整體失效。
- SQLite 寫入使用短 transaction；WAL checkpoint 與備份不能與 realtime critical job 爭用。

## 7. 明確不部署

本版不提供 L4 emergency executor，不自動撥打緊急服務，也不讓模型取得任何等價工具。
