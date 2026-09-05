# 13 · 前端 Setup 與模型管理

> **v3 amendment：** Setup 的 current local model 是 Nemotron Omni vLLM；Frigate 不是完成 setup 的必要條件。Setup 必須顯示 Known/Unknown、模型實際 served ID、2 FPS/5 秒/10 frames + audio 能力，以及未啟動元件的 disabled 狀態。

## 1. 啟動契約

Repository 頂層使用 Node.js/npm workspace。使用者唯一必要啟動命令：

    npm start

Node/npm 負責安裝 JavaScript dependencies、啟動 backend 與 frontend。Nemotron vLLM、Whisper 與 Silero 的 Python runtime 仍由各自受版本鎖定的 environment 管理；npm 只負責呼叫 bootstrap，不假裝能安裝 Python packages。

建議 scripts：

- npm start：檢查 prerequisites，啟動 backend 與 frontend。
- npm run dev：開發模式與 hot reload。
- npm run verify：執行 lint、typecheck、unit、contract 與 smoke tests。
- npm run setup:backend：建立／更新 Python environment。
- npm run migrate：執行 SQLite migrations。

## 2. 首次啟動流程

    npm start
      → 檢查 Node/npm、Python、Docker、磁碟與權限
      → 若 backend environment 不完整，啟動 bootstrap job
      → 啟動 Care backend 與 frontend
      → 前端顯示 /setup 或目前狀態
      → backend 探測 Nemotron vLLM 與選擇 integrations
      →（需要時）runtime 另行下載／驗證模型
      → 完成 health checks
      → 導向 Dashboard

Setup state 必須持久化；重新啟動時只驗證，不重複下載。

## 3. Setup Wizard

步驟：

1. Runtime：Python、Docker／OrbStack、可用 RAM、磁碟空間。
2. Local VLM：確認 Nemotron Omni vLLM endpoint、實際 served model ID 與 multimodal capability。
3. Window：確認 2 FPS、5 秒、10 frames、audio present 與 bounded retention。
4. Browser capture：camera/microphone permission 與 virtual stream smoke test。
5. Frigate：只有啟用 RTSP adapter 時才設定 URL、MQTT、camera mapping 與連線測試。
6. MiniMax：base URL、model、API key、capability probe。
7. Telegram：Bot token、allowlisted chat、發送測試。
8. Care settings：飲水容量、每日目標、跌倒確認、notification/attention 時間窗與 privacy level。
9. Review：顯示目前 served model、啟用／停用 integrations、window parameters 與目前設定。

## 4. Model Catalog 邊界

若未來加入可管理的模型 catalog，前端只提交 catalog 中的 model ID、quantization 與版本，不得提交任意 URL、repository 或 filesystem path。Current Nemotron 權重由外部 vLLM runtime 管理，Care Setup 只保存 endpoint、served model ID 與 capability 結果。

Catalog entry 至少包含：

- id、display name、provider、revision。
- modality、quantization、estimated size。
- minimum／recommended memory。
- download source allowlist 與 expected files。
- checksum 或可信 revision。
- runtime compatibility。

## 5. Runtime 驗證與（未來）Download Job

Current Nemotron setup：

1. 呼叫 vLLM `/v1/models`，確認 served model ID 與設定一致。
2. 執行文字、影像、audio_url 及 structured observation smoke test。
3. 保存 endpoint、實際 model、prompt/schema version、latency 與 capability status。
4. unavailable/degraded 時保留 UI 可用，但不假稱已完成 multimodal inference。

未來若加入受控 model download job，才可依下列流程：

1. 驗證 catalog 與磁碟空間。
2. 建立 download job 與暫存目錄。
3. 串流進度、支援 cancel 與可恢復下載。
4. 驗證檔案、revision 與最小 load probe。
5. 驗證成功後原子移至 model store，並以 activation probe 切換。

失敗時保留上一個 active model，不留下被誤認為可用的半套目錄。

## 6. 設定保存

- 非 secret 設定保存於 SQLite settings 與 config version。
- Secret 保存於本機 secret store 或權限受限的未追蹤檔案；API 只能回傳 configured boolean，不能回傳原值。
- 風險 threshold 更新需驗證範圍並建立新 config version。
- Runtime job 固定使用開始時的 config version，設定更新不改寫正在處理的事件。

## 7. Setup API

- GET /api/setup/status
- GET /api/setup/prerequisites
- GET /api/models/catalog（future managed catalog）
- GET /api/models/installed（future managed catalog）
- POST /api/models/downloads（future managed catalog）
- GET /api/models/downloads/{job_id}（future managed catalog）
- DELETE /api/models/downloads/{job_id}（future managed catalog）
- POST /api/models/{model_id}/activate（future managed catalog）
- POST /api/integrations/vllm/test
- POST /api/integrations/frigate/test（optional）
- POST /api/integrations/minimax/test
- POST /api/integrations/telegram/test
- GET /api/settings
- PATCH /api/settings

所有長任務回傳 job ID；前端透過 WebSocket 顯示 progress，不讓 HTTP request 一直掛住。

## 8. 驗收

1. 全新環境執行 npm start 可啟動 backend/frontend；Setup Wizard 完成後續 integration 設定。
2. Nemotron vLLM `/v1/models` 可查到實際 served model，multimodal smoke test 可通過；若未啟動則 Setup 顯示 unavailable。
3. 下載中斷後可恢復；失敗不破壞目前 active model。
4. Secret API 不回傳 token。
5. 切換模型後 model_calls 與 UI 顯示實際 model revision。
6. 修改 window 或風險時間窗後，新事件使用新 config version，舊事件仍可重現。

