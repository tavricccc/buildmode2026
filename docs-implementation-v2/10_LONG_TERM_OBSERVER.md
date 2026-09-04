# 10 · Long-term Observer

## 1. 功能

Long-term Observer 是必須實作的背景 logical agent，定期讀取 SQLite 中已確認的事件與健康摘要，建立後台可查的日／週趨勢與 finding。它不處理即時跌倒、不直接通知，也不輸出疾病名稱。

首版分析：

- 每日喝水次數、估算量、最後飲水時間與目標完成率。
- 每日 confirmed fall 數量與未恢復持續時間。
- Fake Health 的心率、血氧、活動與步數摘要。
- camera、mic 與 health data 的 coverage。
- 近 7 日與 30 日相對於個人 rolling baseline 的變化。

## 2. 工作流程

    Scheduler
      → 建立固定 window snapshot
      → SQL daily aggregation
      → 與 7／30 日 rolling baseline 比較
      → 只有達變化門檻時呼叫 MiniMax
      → 保存 ObserverFinding
      → Dashboard 後台顯示

## 3. 功能邊界

- 同一 subject、date 與 config version 可重跑但不可重複產生相同 finding。
- 沒有足夠 coverage 時輸出 insufficient_data，不可當成零事件。
- MiniMax 只收到 daily summaries 與 baseline comparison，不收到整段影片。
- Finding 是待觀察假設，不會直接修改即時 alert threshold。
- Observer 不可呼叫 Notify Tool；後台人員可以查看並建立人工後續工作。

## 4. 資料輸出

DailySummary 至少包含：

- summary_date
- hydration session count 與 estimated ml
- confirmed／resolved／unresolved fall counts
- health min／max／avg／latest
- source coverage 與 missing periods
- config version

ObserverFinding 至少包含：

- window_start、window_end
- finding_type 與繁中 statement
- supporting daily summary refs
- baseline comparison
- confidence 與 uncertainty
- status：proposed、acknowledged、dismissed、resolved

## 5. 初始時間窗

- Daily aggregation：本地時間每日 00:05，處理前一日。
- Short trend：最近 7 個有效日。
- Baseline：最近 30 個有效日；資料不足時顯示 provisional。
- 所有 window、minimum coverage 與變化門檻可設定並保存 config version。

## 6. 後台畫面

- 7／30 日飲水趨勢。
- 跌倒事件數與未恢復時間。
- Fake Health 趨勢。
- Data coverage 與裝置離線時間。
- MiniMax finding、支持證據、時間窗與狀態。
- 手動重跑指定日期與 acknowledge／dismiss finding。

## 7. 驗收

1. 用測試時鐘可快速建立 30 日資料並執行 Observer。
2. 同一天重跑不重複計數。
3. camera offline 一整天會降低 coverage，不會被解釋成沒有跌倒或喝水。
4. 沒有顯著變化時不呼叫 MiniMax；有變化時 input 是固定大小摘要。
5. 後台可由 finding 反查 daily summaries 與來源事件。

