# 運作監看與系統稽核頁

> 狀態：目前 runtime 已提供運作監看與 pipeline step；Production/Debug 邊界與完整驗收仍持續補強。

## 頁面分工

Production 與 Debug 都提供「運作監看」，但權限不同：

- Production：唯讀。查看目前管線、事件狀態與失敗原因。
- Debug：在相同監看頁增加模擬資料、手動情境與故障注入控制。
- 系統維護：保留歷史 Runs、Policy actions、模型呼叫與日誌查詢。

運作監看回答「現在做到哪一步」；系統維護回答「過去發生了什麼」。兩者不應塞在同一張表裡。

## 即時步驟

每個分析視窗依序呈現：

```text
來源接收
  → Ring Buffer
  → L1 人體判讀
  → L2 情境觀察
  → 跌倒／飲水狀態機
  → L3 深度覆核
  → Policy Gateway
  → 通知／Dashboard
  → SQLite + WebSocket
```

每一步使用同一組狀態：`waiting`、`running`、`succeeded`、`skipped`、`degraded`、`failed`。

步驟資料至少包含 `step_id`、`run_id`、`event_id`、開始與完成時間、耗時、原因代碼、繁體中文摘要、輸入摘要、輸出摘要與下一步。模型步驟另外顯示 Provider、模型、stub/live、重試次數與 token；敏感欄位一律由後端遮蔽。

## 頁面配置

頁面上方顯示來源、目前 Run、事件狀態、L2/L3 queue 與 Policy/通知健康度。主區域使用單一垂直時間線，不把每個 window 的 L1/L2/L3 卡片全部攤開。

操作工具包含：

- 自動跟隨最新事件，可暫停。
- 依 Run、Event、狀態與層級篩選。
- 「只看異常」模式。
- 展開結構化輸入／輸出。
- 從目前步驟跳到完整 Cascade Trace。

已完成的 Run 預設收合。只有造成狀態變化、介入建議、降級或失敗的步驟預設展開。

## 即時事件契約

WebSocket 新增 `pipeline.step` topic：

```json
{
  "seq": 120,
  "topic": "pipeline.step",
  "payload": {
    "run_id": "run_123",
    "event_id": "evt_456",
    "step": "l3_review",
    "status": "running",
    "started_at_ms": 1788600000000,
    "completed_at_ms": null,
    "summary": "正在覆核疑似跌倒視窗",
    "reason_codes": ["possible_fall"],
    "mode": "live"
  }
}
```

重新連線後，前端先以 REST 取得目前 active runs，再從 WebSocket sequence 接續，不依賴記憶體中未保存的 UI 狀態。

## Cascade Trace 改版

目前的 Trace 資料來源保留。畫面改成「事件狀態時間軸 + 可展開的分析視窗」：

- 先顯示 `suspect → confirmed → recovering → resolved`。
- 每個狀態節點列出促成變化的 Run。
- 沒有造成變化的 follow-up 視窗預設收合。
- L3 建議、Policy 決策與通知結果放在同一條因果鏈上。
- 原始 payload、prompt 與錯誤放入技術細節區。

## 可用性與無障礙

- 狀態不能只靠綠、黃、紅辨認；每個狀態都要有文字與圖示。
- 即時更新區使用合適的 `aria-live`，避免每個影格都打斷讀屏。
- 表格與 Trace 可用鍵盤開啟及關閉。
- 1280px 與 360px 寬度都不可要求整頁水平捲動。
- 自動跟隨可暫停，避免使用者閱讀時畫面跳動。

## 驗收條件

1. Run 開始後，畫面能逐步看到等待、執行、略過、完成或失敗。
2. Production 不出現任何 generator 或故障注入控制。
3. Debug 控制產生的每個事件都能追到 Run、模型、Policy 與資料庫紀錄。
4. WebSocket 中斷重連後不會重複或遺失已保存的步驟。
5. 英文 reason code 不會成為照護端或一般操作員唯一可讀資訊。
