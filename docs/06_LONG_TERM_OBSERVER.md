# 06 · Long-term Observer Agent

## 1. 目的

Long-term Observer Agent 在夜間或 GPU 閒置時分析歷史事件與近期健康脈絡，尋找「相對於這個人自身 baseline 的變化」。它產生 Finding、Baseline 與 Hypothesis，不直接做診斷、不直接通知，也不直接改變 L4 規則。

## 2. 執行流程

1. Scheduler 只在資源、同意與維護狀態允許時建立工作。
2. 建立 immutable analysis snapshot：資料時間窗、Ledger revision、健康資料版本、Watchlist 版本、feature definition 與 model version。
3. 選取已完成、去重且品質足夠的事件；缺失資料要計入 coverage，不可當成「沒有事件」。
4. 正規化事件、HealthKit／FHIR、照護計畫與人工回饋，建立可解釋特徵。
5. 依人、時段、星期、場域與裝置建立或更新 baseline。
6. 計算頻率、持續時間、baseline deviation、趨勢、序列與跨來源關聯。
7. 產生帶證據、反證、信心與下一步觀察的 Finding/Hypothesis。
8. Memory/Consolidation Agent 決定保留、衰減、封存或送人工確認。
9. Watchlist Agent 只提出 candidate；經核准後才成為 active watch item。

## 3. 分析維度

| 維度 | 特徵例子 | 必要注意 |
|---|---|---|
| Frequency | 咳嗽、夜間離床、疑似跌倒每晚次數 | 以可觀測時間校正，避免裝置離線造成假下降 |
| Duration | 事件持續時間、未恢復時間 | 分清 sensor window 與真實狀態時間 |
| Baseline | 活動、睡眠、聲音、步態、作息分布 | 每個人、時段、情境分層，不能只用全域平均 |
| Trend | 連續數日／週的變化 | 需有最小樣本、資料覆蓋率與變化窗口 |
| Sequence | 起床 → 搖晃 → 扶牆 → 坐下 | 先描述行為序列，不直接命名疾病 |
| Pattern | 夜間咳嗽與睡眠中斷同時增加 | 產生待確認假設，顯示相關不代表因果 |

## 4. Baseline 版本

Baseline record 必須包含 subject、feature definition、aggregation window、分層條件、資料覆蓋率、樣本數、統計摘要、建立期間、版本與排除規則。新資料到達時建立新版本；不覆寫舊版本，避免歷史判斷無法重現。

建議先用簡單且可解釋的 rolling median、分位數、平均值／標準差與事件率，等有足夠標註後再引入較複雜模型。對新住民或資料不足的人，baseline 狀態應為 `insufficient_data`，不要輸出強結論。

## 5. Observer Finding 契約

```yaml
finding_id: find_20260904_07
subject_id: resident_001
time_window: {start: 2026-08-21, end: 2026-09-04}
statement: "night-time exit events increased relative to personal baseline"
features:
  current_rate: 1.8
  baseline_rate: 0.7
  coverage: 0.91
evidence_refs: [evt_1001, evt_1044, hk_sleep_20260903]
contradicting_refs: [evt_1050]
confidence: 0.76
hypothesis_status: proposed
next_test: "observe next 7 nights and check caregiver feedback"
baseline_version: baseline_resident_001_v4
```

## 6. Watchlist 回饋規則

- 只把可觀察、可驗證、與照護目的相關的敘述送為 watchlist candidate。
- candidate 必須寫明觀察窗口、優先級、觸發條件、停止條件、資料來源與建議處理。
- 任何可能改變 L3/L4 行為的項目都需要人員或既有 deterministic policy 審核。
- 連續未命中、資料不足或反證出現時，降低優先級或標記 expired；不悄悄刪除歷史。
- Watchlist 更新要產生新版本，並記錄觸發 Finding、審核者與生效時間。

## 7. 反饋與評估

評估不只看模型預測，也要看：Finding 是否可由 evidence 反查、baseline deviation 的誤報／漏報、資料缺失影響、照護者是否能理解與回饋、Watchlist 是否造成過度打擾，以及模型升級後結果是否可重現。

## 8. 資源與隔離

背景工作使用獨立 queue 與 budget，不得搶占 L2–L4 的即時資源；可取消、可續跑、可重試。分析 snapshot 只讀，產出透過 Consolidation 寫入新版本，避免背景工作修改即時事件狀態。

依賴的資料分層見 [04_MEMORY_AND_DATA_MODEL.md](04_MEMORY_AND_DATA_MODEL.md)，健康資料入口見 [08_HEALTH_CONTEXT_INTEGRATION.md](08_HEALTH_CONTEXT_INTEGRATION.md)。

