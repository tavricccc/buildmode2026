# 06 · Web Dashboard

## 1. 單頁布局

```text
┌──────────────────────── Header / system status ────────────────────────┐
│ Video + replay controls        │ Current event / local VLM observation │
├────────────────────────────────┼───────────────────────────────────────┤
│ Health cards                   │ Hydration today                       │
│ HR / SpO2 / steps / activity   │ count / estimated ml / target         │
├────────────────────────────────┴───────────────────────────────────────┤
│ MiniMax health & risk analysis / alert banner                         │
├────────────────────────────────────────────────────────────────────────┤
│ Event timeline                  │ Structured live logs                  │
└────────────────────────────────────────────────────────────────────────┘
```

## 2. 功能與邊界

### Video Panel

- 顯示選定 replay 影片與目前時間。
- 操作 load、play、pause、reset。
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

- Timeline 只顯示 domain events 與 actions。
- Logs 顯示 component、level、message、latency 與 correlation ID。
- 點擊事件可查看 evidence offsets、local result、cloud analysis 與狀態轉換。
- 不顯示 API key、完整 prompt 或可能含敏感資料的 raw response。

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

