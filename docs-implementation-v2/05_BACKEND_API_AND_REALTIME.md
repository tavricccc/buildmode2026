# 05 · Backend API 與即時通訊

> **v3 amendment：** `/ws/media` 是 current camera+microphone continuous ingress，`/ws` 是 committed observation/event realtime bus。Frigate webhook/MQTT 是 optional；Dashboard 必須能在 Frigate disabled 時正常顯示 VLM Known/Unknown/Hypothesis。

## 1. REST API

| Method | Path | 功能 |
|---|---|---|
| GET | `/api/status` | backend、source、local VLM、MiniMax、DB 狀態 |
| GET | `/api/cameras` | camera/source 狀態；Frigate 啟用時再包含其 camera 資訊 |
| POST | `/api/capture/status` | 更新 browser capture permission／stream 狀態 |
| GET | `/api/media/streams` | 查詢 virtual camera stream metadata |
| GET | `/api/media/scene-contexts` | 查詢 camera session 場景註腳 |
| GET | `/api/media/descriptions` | 查詢 5 FPS visual descriptions |
| GET | `/api/media/focus-reviews` | 查詢 2 FPS focus reviews 與 warning proposal |
| GET | `/api/media/time-segments` | 查詢無警告時間段分類 |
| POST | `/api/sources/activate` | 在 live／replay source 間切換 |
| GET | `/api/events` | 依 type、status、start、end 分頁查詢 |
| GET | `/api/events/{id}` | 事件、證據、模型呼叫與 action 詳情 |
| GET | `/api/hydration/summary` | 指定時間窗的次數、估算量與目標完成率 |
| GET | `/api/health/current` | 最新 Fake Health snapshot |
| POST | `/api/health/scenario` | 套用 `normal`、`elevated_hr`、`low_spo2`、`inactive` 場景 |
| POST | `/api/health/analyze` | 以允許的時間窗觸發 MiniMax 分析 |
| POST | `/api/events/{id}/analyze` | 針對單一事件建立分析工作 |
| POST | `/api/replay/load` | 載入 allowlisted 本地影片 ID |
| POST | `/api/replay/start` | 開始／繼續播放 |
| POST | `/api/replay/pause` | 暫停 |
| POST | `/api/replay/reset` | 回到影片起點並清除 runtime state |
| POST | `/api/demo/reset` | 清除本輪 Demo records，需開發模式 |
| GET | `/api/transcripts/recent` | 取得 retention window 內的近期 transcript |
| GET | `/api/recognition/logs` | 取得 local VLM／Frigate（若啟用）的 compact recognition logs |
| GET | `/api/agent/runs` | 查詢 Main Agent judgment、policy gates、score 與 fail-closed 狀態 |
| GET | `/api/tools/calls` | 查詢 logical agent 的 tool-call trace |
| GET | `/api/observer/findings` | 查詢 Long-term Observer findings |
| GET | `/api/notifications` | 查詢 Telegram delivery 與 acknowledgement |
| POST | `/api/notifications/test` | 開發模式向 allowlisted chat 發測試訊息 |
| GET | /api/setup/status | prerequisites、setup steps 與 integrations 狀態 |
| GET | /api/models/catalog | allowlisted local models |
| GET | /api/models/installed | 已安裝版本、大小與 active 狀態 |
| POST | /api/models/downloads | 建立可取消、可觀測的 model download job |
| POST | /api/models/{id}/activate | load probe 成功後原子切換 active model |
| GET/PATCH | /api/settings | 讀取／更新非 secret runtime settings |

不得讓前端提交任意檔案路徑或任意 SQL。Replay API 使用 backend 掃描出的影片 ID。

## 2. WebSocket

端點：`/ws`（已提交 observation/event 廣播）；`/ws/media`（browser camera + microphone continuous ingress）。

`/ws/media` 使用 binary WebM chunks 與 bounded session metadata，不接受截圖作為產品主輸入；前端必須先在 HTTPS origin 取得 camera/microphone permission。backend 會自行抽取 2 FPS frame 與 5 秒 audio window，前端不直接呼叫 vLLM。

```json
{
  "message_id": "msg_01J...",
  "type": "event.updated",
  "occurred_at": "2026-09-04T14:32:10+08:00",
  "correlation_id": "evt_01J...",
  "payload": {},
  "schema_version": "realtime.v1"
}
```

消息類型：

- `system.status`
- `video.progress`
- `health.updated`
- `audio.vad`
- `audio.transcript`
- `camera.status`
- `frigate.event`
- `event.created`
- `event.updated`
- `local_analysis.started`
- `local_analysis.completed`
- `agent.analysis.started`
- `agent.analysis.completed`
- `agent.analysis.skipped`
- `recognition.updated`（planned；current payload 隨 `local_analysis.completed` 與 `event.updated` 傳送）
- `cloud_analysis.started`
- `cloud_analysis.completed`
- `action.triggered`
- `tool.called`
- `observer.finding`
- `notification.updated`
- setup.updated
- model.download.progress
- model.activated
- `log.appended`

Current VLM 的 `local_analysis.completed` payload 至少包含 `window`（window id、frame count、seconds、audio status）、實際 `model`、typed `observation`、canonical `events`、exception `recognition_events`、可選 transcript metadata 與 latency。Dashboard 只把已提交結果當成真相，不能自行從畫面推導事件。

`agent.analysis.completed` payload 包含 `agent_run`、`judgment`、`policy`、實際 model 與 latency。`judgment` 只保存可稽核摘要；`policy.action_executed=false` 表示目前尚未接入 speak/notify executor。

## 3. 一致性

- DB commit 成功後才廣播對應消息。
- WebSocket message 可以丟失；頁面載入、重新連線及偵測到 sequence gap 時用 REST resync。
- Replay reset 產生新的 `run_id`；所有 runtime event 都帶 run ID，避免上一輪晚到結果污染新一輪。
- 長任務回傳 `202 Accepted + job_id`，結果由 WebSocket 或查詢端點取得。

## 4. 錯誤格式

```json
{
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "Local vision inference exceeded its deadline.",
    "retryable": true,
    "correlation_id": "job_01J..."
  }
}
```
