# 08 · 實作順序、分工與驗證

## 1. 三個 Codex 的檔案邊界

### Track A：Backend 與 Data

- FastAPI app、設定、SQLite migrations／repositories。
- REST、WebSocket、replay source、Fake Health。
- Frigate adapter、live source、VAD／Whisper pipeline、transcript retention。
- Event state machine 與參數化 aggregation tools。
- 不修改 frontend component 實作與 model adapter internals。

### Track B：Frontend

- React/Vite、typed API client、WebSocket client、Dashboard panels。
- 使用共同 OpenAPI／event fixtures 開發。
- 不直接讀 SQLite、不持有 MiniMax key、不在瀏覽器推論 canonical event。

### Track C：AI Runtime

- Qwen-VL runtime benchmark、frame preprocessing、prompt 與 output validator。
- MiniMax adapter、capability probe、health/risk schema。
- 提供 stub adapter，讓 Track A/B 不等待模型下載。
- 不直接寫 UI 或繞過 repository 建立 event。

一名整合 owner 負責共用 schema、OpenAPI 及 merge；Track 不得私自修改已發布 contract。必要變更先更新 contract fixtures，再同步 consumer。

## 2. 實作順序

### Gate 0：兩小時內完成

- 建立專案骨架、共同型別、sample payloads。
- MiniMax capability probe。
- Qwen3-VL 8B 4-bit／4B 4-bit 使用同一小段影片 benchmark；8B 是主模型，4B 只作資源不足時的明示降級。
- 決定 P0 local model，不再無限比較模型。

### Gate 1：垂直 stub 閉環（舞台版可先交付）

```text
Replay → stub observation → event → SQLite → WebSocket → Dashboard
Fake Health → aggregate → stub MiniMax result → Dashboard
```

Gate 1 未完成前，不加入更多事件或視覺美化。

### Gate 2：替換真實模型

- Qwen-VL 先接跌倒，再接喝水。
- MiniMax 接健康／風險分析。
- 保留 stub mode，舞台前可快速隔離問題。

### Gate 2b：完整 live pipeline

- 手機 RTSP → Frigate → backend event／media。
- Mic → VAD → Whisper → transcript buffer。
- Event Understanding → Health Context → Risk → Policy → Intervention。
- Memory／State／Health／Speak／Notify／Frontend tools contract tests。

### Gate 3：穩定化

- 重播正例／負例 dataset。
- 測 timeout、invalid JSON、重送、WebSocket 重連、reset。
- 固定 Demo 影片、模型 cache、啟動命令與簡報流程。
- 以測試時鐘執行 daily aggregation 與 Long-term Observer。

## 3. 驗證矩陣

| 測試 | 驗證 |
|---|---|
| Unit | schema validation、dedup、state transitions、window aggregation、policy rules |
| Repository | migration、transaction、indexes、時間窗邊界、重複寫入 |
| API | status code、錯誤格式、參數限制、job lifecycle |
| Realtime | commit 後廣播、重連 resync、run_id 隔離 |
| Model contract | valid、invalid、timeout、low confidence、missing frame |
| Replay E2E | 每支測試影片得到預期狀態序列，無重複 hydration count |
| Live media | RTSP 斷線重連、Frigate event mapping、snapshot／clip 可取 |
| Audio | VAD segmentation、Whisper transcript、TTL cleanup、資源競爭 |
| Agent tools | schema、權限、idempotency、Policy Gateway 不可繞過 |
| Observer | daily summary、時間窗邊界、無新資料時不重複呼叫 MiniMax |
| Frontend | 1366×768、loading／empty／degraded／error 狀態、reset |
| Secret | frontend build、Git diff、logs、SQLite 均無 API key |

## 4. 舞台 Runbook

1. 預先下載模型並離線驗證可載入。
2. 啟動 backend，確認 DB migration、MiniMax 與 local VLM status。
3. 啟動 frontend，全螢幕開 Dashboard。
4. 執行 demo reset。
5. 載入跌倒影片，展示 observation → confirmed → no recovery → alert。
6. reset 後載入喝水影片，展示 session completed → SQLite count → hydration progress。
7. 切換 Fake Health scenario，選擇分析窗口並呼叫 MiniMax。
8. 展示 MiniMax 使用事件聚合而非重傳全部影片。
9. 準備 stub mode 截圖／錄影作最後 fallback，但主展示仍使用現場推論。

## 5. 切線規則

- 8B benchmark 在 M4 16GB 不穩或延遲超出 Demo 預算：明示切換 4B，並保留 benchmark 紀錄；不得在 UI 假稱仍使用 8B。
- Frigate 未接好：舞台可使用 ReplaySource，但完整書審驗收仍視為未完成。
- 喝水量視覺估算不穩：保留 confirmed count，容量採設定值。
- MiniMax video input 不穩：只送文字摘要／必要影格。
- UI 時間不足：保留 video、health、hydration、analysis、timeline 五個核心區塊。
- P0 尚未完整 E2E：停止 P1/P2。
