# 01 · 三層事件 Pipeline

## Media ingest

`RTSP / Replay → FFmpeg / PyAV → bounded ring buffer`。只保留最近短時間窗口，不做完整 NVR；Replay 與 RTSP 共用相同 downstream contract。

## L1 Person Gate

輸出只需 `person_present / confidence / observed_at / detector_id / health`。預設可用 YOLO11n person class；threshold、sampling FPS、debounce/hysteresis、device 可設定。

為避免 false negative：no-person 時仍定期建立 safety heartbeat Gemini job；detector stale/unavailable 時 fail-open；event 已進 suspect/confirmed 時直接忽略 L1。

## L2 Gemini 3.5 Flash Lite

一般窗口建議 5–10 秒。Gemini 收短影片與 prompt，必要時可附 transcript 或其他文字 context。

呼叫方式見 `src/backend/l2/gemini_client.py`：小檔 `inline_data`，大檔 Files API。API key 存 backend secret store / `GEMINI_API_KEY`。

輸出至少包含：person visible、fall observation、hydration observation、confidence，以及：

```json
{
  "escalation": {
    "required": false,
    "reason_codes": [],
    "requested_evidence_window_sec": 10
  }
}
```

Schema invalid 可 repair 1 次；仍失敗則標 invalid，不更新 event state。

## Event state machine

跌倒：`idle → suspect → confirmed → recovering → resolved`。喝水：`idle → suspect → confirmed → active → completed`，只有 completed session 計數。模型輸出只是 observation，不直接等於 confirmed event。

## L3 MiniMax M3

觸發來源：Gemini escalation、state machine 高風險狀態、deterministic policy 二次判讀、使用者手動深度分析。

正常 evidence bundle：`short video clip + Gemini structured result + escalation reason + current event state + optional transcript + optional health/event aggregate`。

MiniMax 必須直接看到影片，不只看 Gemini 二手摘要。影片缺失時才可 text-only degraded。L3 回傳 deeper interpretation / uncertainty / risk recommendation，但不能直接發 Telegram。

## Audio

短影片若包含音軌，可讓 Gemini / MiniMax 原生多模態處理，但不能把「一定理解音訊」當成未測即成立的能力。需要逐字稿時才啟用 `Mic/stream audio → VAD → ASR → Transcript Buffer`，Transcript 有 retention TTL，可附到 L2/L3 context。

## Failure behavior

- L1 unavailable：fail-open 到 Gemini，不能 assume empty room。
- Gemini unavailable：L1、SQLite、Dashboard 繼續；suspect 標 degraded/uncertain。MiniMax 不自動變成全時替代品。
- MiniMax unavailable：Gemini + state machine 正常；deterministic policy 可依已驗證資料繼續允許的通知。
- L2/L3 queue 預設各 `1 running + 1 pending`；高風險 pending 受保護。

