# REST API 與 WebSocket 規格參考 (API Reference)

Care Agent 後端提供標準 REST API 與 WebSocket 即時資料流（預設監聽連接埠 `8200`）。所有資料交換均採用 UTF-8 JSON 格式。

---

## 認證與安全性規範

- **零金鑰外洩原則**：任何 GET 端點均不回傳真實 API 金鑰明文。敏感資訊僅標記 `is_configured: true`。
- **設定版本追蹤**：任何改變運作行為的寫入操作（`PUT /api/settings`、`POST /api/settings/providers`）皆會在 SQLite 中自動遞增建立一筆設定版本，支援一鍵 Rollback。

---

## 1. 系統狀態與管線稽核 (Status & Telemetry)

### `GET /api/status`
取得系統各模組運行健康度、啟動時間與當前配置。
- L2 與 L3 的 `provider`、`model` 會隨設定變化；以下以目前建議的 Gemini + MiniMax 雲端組合示範。
- **回應範例**（Provider 會依設定變化）：
  ```json
  {
    "uptime_ms": 3600000,
    "subject_id": "subject-1",
    "config_version": "policy.v5.0",
    "source": { "running": false },
    "providers": {
      "l2": { "name": "gemini", "model": "gemini-3.5-flash-lite" },
      "l3": { "name": "minimax", "model": "MiniMaxAI/MiniMax-M3" }
    },
    "cascade": { "windows_seen": 0 }
  }
  ```

### `GET /api/pipeline/runs`
取得端到端全視窗稽核紀錄（包含被 L1 略過的無人視窗與統計）。
- **查詢參數**：
  - `limit` (int, 預設 50, 最大 500)
  - `offset` (int, 預設 0)
  - `l2_outcome` (string, 選填: `called`, `skipped_l1`, `heartbeat`, `failed`)
  - `stats_window_sec` (int, 預設 3600 秒)
- **回應內容**：包含 `runs` 陣列與滑動視窗內之統計匯總（略過率、呼叫數、升級數、平均延遲）。

---

## 2. 事件與健康指標 (Events & Health)

### `GET /api/events`
查詢狀態機追蹤之事件列表。
- **查詢參數**：`type` (如 `fall`, `hydration`)、`status` (如 `suspect`, `confirmed`, `resolved`)、`limit`。

### `GET /api/events/{event_id}`
查詢單一事件之完整階梯覆核路徑（Cascade Trace）。
- **回應範例**：
  ```json
  {
    "event": { "event_id": "evt_123", "type": "fall", "status": "confirmed" },
    "runs": [ ... ],
    "model_calls": [ ... ],
    "analyses": [ ... ],
    "actions": [ ... ]
  }
  ```

### `GET /api/hydration/summary`
取得長輩當日與近期累計飲水總量、目標達成率（`progress`）與各次有效飲水週期明細。

### `GET /api/health/current`
查詢長輩最新感測器或輔助健康數據指標。

歷史量測不另設端點；`GET /api/statistics?days=1|3|7|30` 的 `health_samples` 會回傳所選期間內、按時間排序的量測。單次回應最多 1,000 筆。

### `POST /api/health/sample`
手動或透過外部感測器注入單筆健康量測樣本。
- **請求格式**：
  ```json
  {
    "metric": "heart_rate",
    "value": 72.0,
    "unit": "bpm",
    "source": "wearable"
  }
  ```

---

## 3. 整合驗證與連線測試 (Integration Probes)

### `POST /api/integrations/person-gate/test`
針對目前緩衝區影格執行 L1 人體存在感測器快速驗證。
- **回應**：回傳偵測耗時、偵測器健康狀態與每一影格之信心度與邊界框判讀。

### `POST /api/integrations/gemini/test`
測試 Google Gemini API 金鑰有效性與模型可達性。
- **特點**：此端點僅執行輕量模型清單查詢，不傳送多媒體，費用為零且反應時間約 150–200ms。

### `POST /api/integrations/minimax/test`
測試 MiniMax / GMI Cloud API 金鑰與端點連線能力。

### `POST /api/pipeline/cascade-test`
端到端三層級聯綜合測試。
- **請求參數**：`scenario`（如 `fall`, `hydration`, `empty_room`）。
- **行為**：從 `replays/` 讀取特定測試情境，依序通過 L1 判定、強制 L2 語意理解、觸發 L3 升級審查，並回傳三層完整的判斷與耗時。

---

## 4. 設定與金鑰管理 (Settings & Secrets)

### `GET /api/settings`
取得系統運作策略、模型 Slot 配置、可用 Provider 清單、金鑰配置狀態與設定版本歷史。

### `PUT /api/settings`
套用全新運作策略（包含 L1 門檻、心跳間隔、通知規則等），自動產生新版本號並即時熱重載。

### `POST /api/settings/rollback`
將運作策略回滾至指定之歷史版本。
- **請求格式**：`{ "version": "policy.v5.1725580000000" }`

### `POST /api/settings/providers`
熱切換 L2 或 L3 之供應商與模型參數：
- **請求格式範例**：
  ```json
  {
    "l2": {
      "name": "gemini",
      "model": "gemini-3.5-flash-lite",
      "timeout_sec": 45.0
    },
    "l3": {
      "name": "minimax",
      "model": "MiniMaxAI/MiniMax-M3"
    }
  }
  ```

### `POST /api/secrets`
寫入敏感 API 金鑰（Write-Only）。
- **請求格式**：`{ "key": "GEMINI_API_KEY", "value": "AIzaSy..." }`
- **回應**：僅回傳 `{ "secrets": { "GEMINI_API_KEY": { "configured": true } } }`。

---

## 5. 觀察者與長期分析 (Observer)

- `GET /api/observer/findings`：取得近期的個人作息異常報告與每日摘要。
- `GET /api/observer/status`：查詢觀察者排程器下次執行時間與最近一次執行狀態。
- `POST /api/observer/run`：手動立即觸發一次觀察者分析計算。

### `POST /api/observer/analyze-all`

依照照護總覽目前選取的期間，執行一次 L3 綜合分析。`days` 只接受 `1`、`3`、`7` 或 `30`：

```json
{ "days": 7 }
```

後端會先更新當日 deterministic rollup，再封裝期間內的每日彙總、健康量測、事件、Policy 動作、Observer 紀錄與 Pipeline 統計。這個請求不包含 secrets、原始資料庫或影像。L3 必須依 `l3.care_review.v1` 回傳以下欄位：

- `summary`
- `risk_level` 與 `confidence`
- `recommendations`
- `positive_signals`
- `attention_items`
- `data_limitations`

成功回應也會帶回實際模型名稱、資料筆數、`call_id` 與 `finding_id`。完整結果會寫入 `model_calls` 與 `observer_findings`，但不會送進 Policy Gateway 或直接建立通知。L3 未啟用時回傳 `409 l3_disabled`；模型呼叫或格式修復仍失敗時回傳 `502`。

---

## 6. WebSocket 即時推播協定 (`/ws`)

前端客戶端可建立持久 WebSocket 連線至 `ws://127.0.0.1:8200/ws`：

- **連線建立**：伺服器立即推送最新 `status` 與 `active_config`。
- **事件推播格式**：
  ```json
  {
    "type": "pipeline_run",
    "payload": {
      "window_id": "win_1725580123",
      "l1_decision": "person_present",
      "l2_outcome": "called",
      "l2_latency_ms": 1820,
      "l3_called": false
    }
  }
  ```
- **推播訊息類型 (`type`)**：
  - `pipeline_run`：新視窗完成推論或略過。
  - `event_state_change`：狀態機狀態躍遷（如跌倒由 `suspect` 轉為 `confirmed`）。
  - `hydration_update`：飲水週期累計更新。
  - `config_updated`：系統設定發生異動。
