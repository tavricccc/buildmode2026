# 06 · Long-term Observer 與 Caregiver Summary

## 1. 目的

Long-term Observer 不監看即時畫面，也不直接通知。它讀取已確認 Event Ledger、health aggregate、coverage 與 semantic memory，尋找相對於住戶自身 baseline 的變化，產生可供 Caregiver Agent 使用的 finding。

## 2. 生活指標

首版可由事件與感測器聚合：活動時間、出門次數與時長、冰箱開關與停留、飲水 session、食物新增/移除、聲音事件（洗衣、微波、電鍋、流水、沖水）、人物活動與資料 coverage。模型不能把「沒有影像」解讀為「沒有活動」。

## 3. 個人 baseline

baseline 是該住戶過去 12 週的 rolling mean/sd，不使用人口平均。觀測期預設最近 4 週；住院、外宿、旅遊、送餐服務等排除期間需由人工標記。資料不足時狀態為 `provisional` 或 `insufficient_data`，不輸出確定衰退。

## 4. Privacy Aggregator

原始事件先轉成日／週摘要，再交給 Caregiver Agent：

```text
raw: 08:13 bathroom entered, 08:20 exited
summary: 今日已記錄 5 次如廁事件，較近 7 日個人平均略高
```

Caregiver 預設看到 Level 1/2；只有特定事件 scope、權限與同意都成立時才可查看 Level 3 evidence index。

## 5. Finding contract

```json
{
  "finding_id": "finding_...",
  "finding_type": "activity_change",
  "window": {"start": "2026-08-01", "end": "2026-08-28"},
  "statement": "午後活動量較個人基線下降",
  "supporting_daily_summaries": ["2026-08-20", "2026-08-21"],
  "baseline_comparison": {"metric": "activity_minutes", "delta_sd": -1.8},
  "coverage": {"camera": 0.92, "audio": 0.81},
  "confidence": 0.72,
  "status": "proposed"
}
```

Finding 是待觀察假設，不是診斷，不修改即時 alert threshold，不直接呼叫 Notify。

## 6. 執行與驗收

- 每日建立固定 window snapshot，日／週重跑不重複計數。
- 7／30 日趨勢與 rolling baseline 可回查日期與事件。
- sensor offline 降低 coverage，不產生「零事件」結論。
- 只有顯著變化才升級到 Caregiver Agent；摘要固定大小。
- 需以測試時鐘完成 daily summary、baseline、finding 與 acknowledge/dismiss 流程。
