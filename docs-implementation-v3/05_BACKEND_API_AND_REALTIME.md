# 05 · Backend API 與即時通訊

## 1. REST API

| Method | Path | 功能 |
|---|---|---|
| GET | `/api/status` | backend、source、local VLM、MiniMax、DB 狀態 |
| GET | `/api/cameras` | RTSP camera、live 狀態、最近 frame 與 loop latency |
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

端點：`/ws`

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
- `vision.loop.tick`
- `vision.loop.dropped`
- `event.created`
- `event.updated`
- `local_analysis.started`
- `local_analysis.completed`
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
