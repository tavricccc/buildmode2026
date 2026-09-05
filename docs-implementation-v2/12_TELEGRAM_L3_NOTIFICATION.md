# 12 · Telegram L3 通知

> **v3 amendment：** 通知只能接 Policy Gateway 的 attention/intervention decision。Unknown、低信心或單一 VLM candidate 不得直接變成 Telegram；recipient、payload level、責任人與 acknowledgement 都必須可回溯。

## 1. 定義

L3 是通知照護者並追蹤是否有人接手。它不是 L4 emergency，不會自動撥打緊急服務。Telegram Bot 是首版唯一外部通知 channel。

## 2. 發送內容

一般 L3 使用 sendMessage；有必要影像證據時使用 sendPhoto。訊息包含事件類型、時間、camera、已觀察事實、不確定性、持續時間、目前是否恢復，以及 Dashboard event URL 或 event ID。

訊息附上「已收到」與「誤報」inline buttons。callback_data 採短 opaque token，不放健康資料或完整事件 JSON，並保持在 Telegram Bot API 的長度限制內。

## 3. 接收 acknowledgement

本機部署不要求公開 webhook，使用 getUpdates long polling：

1. Worker 讀取下一個 update offset。
2. 驗證 update ID 尚未處理。
3. 驗證 callback sender 與 chat 在 allowlist。
4. 解析 opaque callback token並找到 delivery。
5. 以 transaction 更新 acknowledged 或 false_alarm。
6. 呼叫 answerCallbackQuery，避免 Telegram client 持續顯示 loading。
7. 更新原訊息或移除 buttons，避免重複處理。
8. DB commit 後廣播 notification.updated。

若未來改 webhook，long polling 與 webhook 不可同時啟用。

## 4. 狀態機

    queued
      → sending
      → sent
      → acknowledged | false_alarm
      → failed

Retryable error 可回到 queued；每次 attempt 都增加 attempt_count。相同 action 與 recipient 使用固定 idempotency key，不得重複建立多則通知。

## 5. 安全邊界

- Bot token 只存在 backend environment。
- chat ID 必須在 allowlist；模型不能指定任意 recipient。
- callback data 視為不可信輸入，必須驗證格式、token、sender、chat、expiry 與目前狀態。
- Telegram 只收到事件必要摘要；健康分析全文不預設附上。
- L3 失敗不自動升級成 L4；Dashboard 顯示 failed 並保留人工處理。

## 6. Timeout 與重試

- HTTP connect/read timeout 可設定。
- 429 依 retry_after，5xx／網路錯誤採 exponential backoff + jitter。
- 非 retryable 4xx 直接 failed。
- acknowledgement timeout 只把 delivery 標成 no_response 並在 Dashboard 顯示；不啟動 L4。

## 7. 驗收

1. allowlisted chat 收到測試訊息。
2. confirmed fall 的 L3 policy 只建立一筆 Telegram delivery。
3. 有 snapshot 時可發照片；缺 snapshot 時仍能發文字且註明證據缺失。
4. 按「已收到」後 DB、Telegram message 與 Dashboard 同步更新。
5. 按「誤報」後事件不被刪除，保存 feedback。
6. 重送 callback、偽造 token、非 allowlisted sender 都不重複或越權更新。
7. Bot token 不出現在 logs、SQLite、frontend 或 Git。

