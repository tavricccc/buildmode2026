# HANDOFF — Care Agent v5 Frontend Reimagine（2026-09-05）

Branch: `frontend`

Base: `origin/main` @ `ceea44a`

Design source: Google Stitch project `Care Agent v5 · Frontend Reimagine`

## 本次交付

以 Stitch「Calm Vigilance」方向完整重構 `v5/frontend`，並補上前端所需的真實 Observer、統計與影像 Snapshot 後端能力。不是靜態 mock；畫面仍接既有 REST、WebSocket、SQLite、L1/L2/L3 與 Policy Gateway。

### 資訊架構

- **照護總覽**：住戶安全狀態、來源狀態、AI 身體狀況、L1→L2→L3→Policy 連續管線、事件、飲水、健康、Pipeline Runs、Policy 決策與日誌。
- **即時影像**：RTSP、內建 Replay Scenario、本機錄影三種來源；開始、停止、重新連線；顯示低頻分析 Snapshot 與來源健康指標。
- **趨勢與統計**：7/30/90 日區間、飲水、跌倒、L2/L3 使用量、每日活動/飲水趨勢、AI 狀態與完整 Observer 紀錄。
- **初始設定**：環境、L1、L2、L3 與端到端 Cascade Test，繁體中文化並明確區分 offline stub 與真模型。
- **系統設定**：Write-only Secrets、Providers、Policy 群組、版本與 Rollback，繁體中文化。

## 持續型 AI Observer

新增 `observer_runs` 稽核表與 `ObserverScheduler`：

- 預設每 15 分鐘執行，可用 `CARE_OBSERVER_INTERVAL_SEC` 調整，最低 60 秒。
- 啟動時先執行一次；單一執行鎖避免重疊。
- 每次都寫入紀錄，狀態為 `stable`、`attention`、`insufficient_evidence`、`anomaly` 或 `failed`。
- 正常、沒有警報時仍會留下「狀況穩定」紀錄。
- 後端只提供白名單 SQLite 彙總，不讓模型執行任意 SQL。
- 彙總姿勢、活動/靜止比例、信心、飲水、跌倒、coverage、skip 與模型使用量。
- 只有指標超過門檻時才呼叫 L3 產生 narrative；AI 仍只能建議，Policy Gateway 才能授權通知。
- UI 明示「AI 觀察不是醫療診斷」。

## 新增 API

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/observer/status` | 排程狀態與最新 Observer 紀錄 |
| GET | `/api/observer/records?limit=N` | 持續觀測紀錄 |
| GET | `/api/statistics?days=7\|30\|90` | 每日彙總、Observer 狀態統計與近期觀測 |
| POST | `/api/observer/run` | 手動立即執行一次，重疊時回 409 |
| GET | `/api/source/snapshot` | Ring Buffer 最新 JPEG；沒有影格時回 404 |

既有 `/api/source/start` 現在由 UI 實際使用 `rtsp`、`replay_scenario` 與 `replay_file` 三種模式。RTSP URI 不會由 `/api/status` 回傳，只回傳去除認證資訊的 host。

## 資料庫

新增 migration：`v5/backend/store/migrations/002_observer_runs.sql`

`observer_runs` 保存分析區間、狀態、摘要、信心、資料完整度、deterministic/L3 模式、model call、彙總 metrics 與 anomaly codes；已建立 subject/time 與 status/time indexes。

## 視覺與互動

- 深藍黑底、低警報疲勞；警示色只用於真正需要注意的狀態。
- L1 綠青、L2 藍、L3 紫，Policy 使用獨立授權節點。
- Event Trace 改為 480px overlay drawer，不再壓縮 Dashboard。
- 44px 級操作目標、鍵盤 focus、狀態同時使用文字與色彩。
- 使用 Phosphor Icons，不用 emoji 或自製 SVG。
- 1150px 與 760px 響應式重排。

## 驗證

```text
bun run verify
✅ Python compile check
✅ 124 unit tests
✅ frontend TypeScript typecheck
✅ ffmpeg found

bun run build
✅ Vite production build
```

Windows 原先直接斷言 POSIX `0600` mode 會錯誤讀成 `0666`；測試已改為 Windows 驗證檔案存在、POSIX 環境維持嚴格 mode assertion。Secret API 的不回傳與 redaction 測試仍保留。

## 已知限制與下一步

1. Snapshot 是分析 Ring Buffer 的低頻 JPEG，不是 NVR，也不持續儲存影片。
2. 身體狀況來源是現有 L2 姿勢、靜止、跌倒、飲水與 scene summary；不宣稱心率、血壓、體溫或疾病診斷。
3. 真實 Gemini 能力仍需有效 Key 跑 `bun run probe:gemini`。
4. Observer 現在以 deterministic 彙總為常態；只有越過門檻才花費 L3。
5. 前端 Google Fonts 需要網路；無網路時會安全退回 system fonts。

## 執行

```bash
cd v5
bun install
bun run migrate
bun start

# 模擬情境
bun start -- --source fall

# 即時 RTSP
bun start -- --rtsp "rtsp://..."
```
