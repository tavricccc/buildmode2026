# 13 · 前端 Setup 與模型管理

## 1. 啟動契約

Repository 頂層使用 Bun workspace。使用者唯一必要啟動命令：

    bun start

Bun 負責安裝 JavaScript dependencies、啟動 Setup Server、backend、workers 與 frontend。Qwen、Whisper 與 Silero 的 Python runtime 仍由 Python environment 管理；Bun 只負責呼叫受版本鎖定的 bootstrap，不假裝能安裝 Python packages。

建議 scripts：

- bun start：檢查 prerequisites，啟動完整應用。
- bun run dev：開發模式與 hot reload。
- bun run verify：執行 lint、typecheck、unit、contract 與 smoke tests。
- bun run setup:backend：建立／更新 Python environment。
- bun run migrate：執行 SQLite migrations。

## 2. 首次啟動流程

    bun start
      → 檢查 Bun、Python、Docker／OrbStack、磁碟與權限
      → 若 backend environment 不完整，啟動 bootstrap job
      → 啟動 Setup Server 與 frontend
      → 前端導向 /setup
      → 使用者選擇模型與 integrations
      → backend 下載、驗證、啟用
      → 完成 health checks
      → 導向 Dashboard

Setup state 必須持久化；重新啟動時只驗證，不重複下載。

## 3. Setup Wizard

步驟：

1. Runtime：Python、Docker／OrbStack、可用 RAM、磁碟空間。
2. Vision model：預設 Qwen3-VL-8B-Instruct 4-bit；4B 為明示 fallback。
3. Speech model：選擇 Whisper model 與語言 Chinese。
4. Frigate：URL、MQTT、camera mapping、連線測試。
5. Camera：RTSP credential 與 live preview。
6. MiniMax：base URL、model、API key、capability probe。
7. Telegram：Bot token、allowlisted chat、發送測試。
8. Care settings：飲水容量、每日目標、跌倒確認與通知時間窗。
9. Review：顯示將下載的大小、儲存位置與目前啟用設定。

## 4. Model Catalog 邊界

前端只提交 catalog 中的 model ID、quantization 與版本，不得提交任意 URL、repository 或 filesystem path。

Catalog entry 至少包含：

- id、display name、provider、revision。
- modality、quantization、estimated size。
- minimum／recommended memory。
- download source allowlist 與 expected files。
- checksum 或可信 revision。
- runtime compatibility。

## 5. Download Job

模型下載由 backend 執行：

1. 驗證 catalog 與磁碟空間。
2. 建立 download job 與暫存目錄。
3. 串流進度到 WebSocket。
4. 支援 cancel 與可恢復下載。
5. 驗證檔案、revision 與最小 load probe。
6. 驗證成功後原子移至 model store。
7. 更新 model installation record。
8. 只有 activation probe 成功才切換 active model。

失敗時保留上一個 active model，不留下被誤認為可用的半套目錄。

## 6. 設定保存

- 非 secret 設定保存於 SQLite settings 與 config version。
- Secret 保存於本機 secret store 或權限受限的未追蹤檔案；API 只能回傳 configured boolean，不能回傳原值。
- 風險 threshold 更新需驗證範圍並建立新 config version。
- Runtime job 固定使用開始時的 config version，設定更新不改寫正在處理的事件。

## 7. Setup API

- GET /api/setup/status
- GET /api/setup/prerequisites
- GET /api/models/catalog
- GET /api/models/installed
- POST /api/models/downloads
- GET /api/models/downloads/{job_id}
- DELETE /api/models/downloads/{job_id}
- POST /api/models/{model_id}/activate
- POST /api/integrations/frigate/test
- POST /api/integrations/minimax/test
- POST /api/integrations/telegram/test
- GET /api/settings
- PATCH /api/settings

所有長任務回傳 job ID；前端透過 WebSocket 顯示 progress，不讓 HTTP request 一直掛住。

## 8. 驗收

1. 全新環境執行 bun start 可進入 Setup Wizard。
2. 8B model 可從前端選擇、下載、驗證與啟用。
3. 下載中斷後可恢復；失敗不破壞目前 active model。
4. Secret API 不回傳 token。
5. 切換模型後 model_calls 與 UI 顯示實際 model revision。
6. 修改風險時間窗後，新事件使用新 config version，舊事件仍可重現。

