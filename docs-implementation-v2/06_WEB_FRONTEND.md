# 06 · Web Dashboard

> **v3 amendment：** Dashboard 主畫面從「監控面板」改成 Home Context / Agent State / Memory：顯示 Known、Unknown、Hypothesis、VLM window、audio events、Next action 與 privacy level。camera 是 local preview，不是 caregiver 預設視角。

## 1. 單頁布局

```text
┌──────────────────────── Header / connection status ────────────────────┐
│ Continuous camera + mic input       │ Current stable posture/state     │
├─────────────────────────────────────┴───────────────────────────────────┤
│ Confirmed event timeline: stood up / sat down / fall / sound           │
├─────────────────────────────────────┬───────────────────────────────────┤
│ Main Agent current structured output │ All rounds + persistent trace    │
├─────────────────────────────────────┴───────────────────────────────────┤
│ VLM evidence / descriptions / transcripts / live feed                  │
└────────────────────────────────────────────────────────────────────────┘
```

首次啟動或設定未完成時先進入 /setup；完成後才進入 Dashboard。後續可由 Settings 再次測試 integrations、下載／切換模型與修改時間窗。

## 2. 功能與邊界

### Camera / Video Panel

- 透過 HTTPS browser permission 取得真實 camera + microphone MediaStream，顯示 live preview 並以 WebSocket continuous stream 傳送；這不是 screenshot 上傳。
- 顯示 2 FPS × 5 秒 window、10 frames、audio bytes/status 與實際 Nemotron model。
- Frigate live camera 為 optional adapter；可切換 replay 測試模式。
- Replay 模式提供 load、play、pause、reset。
- 疊加目前 observation label、confidence 及事件狀態。
- 不在瀏覽器執行 canonical inference；顯示資料以 backend 結果為準。

### Health Panel

- 顯示最新值、單位、測量時間與 stale 狀態。
- 提供 Fake Health scenario 按鈕。
- 提供分析時間窗選單與「請 MiniMax 分析」按鈕。

### Hydration Panel

- 顯示今日 confirmed session count。
- 顯示 estimated ml、每日目標及完成百分比。
- 明確標示「估算」，不把配置容量冒充視覺精確量測。

### Timeline 與 Logs

- Timeline 只顯示已確認的 domain events 與姿態 transition；瞬時 VLM observation 不冒充事件。
- 姿態 transition 必須跨兩個有序窗口確認，顯示絕對時間、stream offset、首次觀察 offset、確認 offset、from/to state 與 confidence。
- Recognition logs 顯示 VLM 的值得注意／忽略判定、compact log excerpt、window 與 provenance；例外聲音／人物／物件不硬塞進 fall/hydration。
- 5 FPS 描述卡片只呈現人物／物品動作與變化，不重複場景註腳；無動作時保留明確的無動作摘要。
- Logs 顯示 component、level、message、latency 與 correlation ID。
- 點擊事件可查看 evidence offsets、local result、cloud analysis 與狀態轉換。
- 不顯示 API key、完整 prompt 或可能含敏感資料的 raw response。

### Runtime 與 Agent Trace

- 顯示 camera、mic、Nemotron vLLM、DB 與 WebSocket 狀態；Frigate、VAD、Whisper、MiniMax、Telegram 未啟用時顯示 disabled/degraded，不得顯示成 healthy。
- 顯示 logical agent 的輸入摘要、tool call、耗時、結果與 Policy Gateway 決定。
- 顯示 World State 的 Known、Unknown、Hypothesis、coverage、attention level 與 next action（完整 Active Inquiry UI 為後續階段）。
- 開發面板展開每輪 Main Agent 的 situation summary、observed facts、temporal assessment、event assessments、Unknown/Hypothesis、不確定性、decision reasons、policy gates、score components、next action 與 TTL transcript；只顯示 structured judgment，不顯示隱藏 chain-of-thought。
- Transcript 只顯示仍在 retention window 的內容；到期後同步移除。
- WSS 事件只做增量合併；每 4 秒由 REST 恢復 canonical state。不得因新 observation、agent trace 或重連清空前一輪內容。

### Observer 後台

- 顯示 7／30 日飲水、跌倒、健康與 coverage 趨勢。
- 顯示 finding、支持資料、分析窗口、信心與狀態。
- 支援手動重跑指定日期及 acknowledge／dismiss finding。

### Telegram 通知狀態

- 顯示 queued、sending、sent、acknowledged、false_alarm、failed。
- 顯示 provider message ID、嘗試次數、最後錯誤與 acknowledgement 時間。
- 前端不能修改 Telegram chat ID allowlist 或讀取 Bot token。

### Setup 與 Settings

- 顯示 prerequisites、磁碟、記憶體及各 integration health。
- 顯示並驗證 Nemotron vLLM 實際 served model、endpoint、multimodal capability 與 window parameters。
- Frigate、Whisper、MiniMax、Telegram 是可選 integration；設定頁必須標示未啟用狀態。
- 設定 camera/microphone permission、風險時間窗與既有事件／例外事件模式。
- Secret 欄位只能覆寫或清除；載入頁面時不得回填原值。
- Model ID 與來源只能從 backend catalog 選擇，不提供任意 URL／path 輸入框。

## 3. Client State

- Server state 以 REST cache + WebSocket invalidation 維護。
- UI-only state 僅包含選取 tab、filter、dialog 與尚未送出的 controls。
- Reload 後必須能由 REST 完整恢復，不依賴瀏覽器記憶體。
- 所有時間以使用者本地時區呈現，API 保留 ISO 8601 原值。

## 4. Demo 操作安全

- 分析按鈕需防重複點擊；進行中顯示 job 狀態。
- Alert 可由 Demo 操作者 acknowledge，但不可刪除原事件。
- Backend degraded 時保留歷史查詢與 replay 控制，並清楚顯示失效元件。
- 提供全螢幕模式，最低支援 1366×768 投影畫面。
