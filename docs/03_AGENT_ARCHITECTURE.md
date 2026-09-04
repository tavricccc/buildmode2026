# 03 · Agent 架構

## 1. 設計原則

Agent 是受限的工作單元，不是可以任意讀寫資料或呼叫外部服務的全能角色。每個 Agent 有明確的輸入、輸出、工具白名單與不可越過的安全邊界；跨 Agent 溝通使用 typed message，不用自然語言傳遞關鍵決策。

產品對外只呈現三個邏輯 Agent；下表的既有 Agent 保留作為內部責任分解：

| 產品邏輯 Agent | 內部責任 | 主要輸出 |
|---|---|---|
| Context / World State Agent | Event Understanding、狀態 reducer、資料品質與不確定性 | World State、known／unknown、question candidate |
| Resident Interaction Agent | Intervention 的長輩互動部分、Memory 寫入申請、Reminder proposal | prompt、resident reply、confirmed fact、reminder proposal |
| Caregiver Agent | Long-term Observer、Consolidation、照護者投影 | 日誌、趨勢、finding、evidence refs |

~~既有的 Event Understanding、Risk、Intervention、Observer、Consolidation 名稱不再直接作為產品主敘事；它們保留在 runtime 內，負責可測試與可審計的細部工作。~~

### 最新 v3 對照

目前 v3 實作將上述產品概念落在同一個 backend 的 logical agents：`Event Understanding` 負責本地視覺事件解讀，`Health Context` 負責健康／事件摘要，`Risk` 與 `Intervention` 負責政策後的行動；Long-term Observer 產生日／週 finding。這些不是獨立 microservices，詳見 [docs-implementation-v3/02_EVENT_AGENT_AND_POLICY_CONTRACTS.md](../docs-implementation-v3/02_EVENT_AGENT_AND_POLICY_CONTRACTS.md)。

## 2. Agent 責任矩陣

| Agent | 觸發 | 讀取 | 可寫入 | 明確不能做的事 |
|---|---|---|---|---|
| Watchlist Agent | 新脈絡、Observer Finding、人工要求 | Medical Context、Baseline、Hypothesis、歷史 Event | Watchlist candidate/version | 建立 L4 規則、改變緊急門檻 |
| Event Understanding Agent | Event Candidate／Bundle | 證據、最小 Watchlist context | Observation、Interpretation | 發通知、判定介入等級 |
| Risk Agent | 新 Interpretation、趨勢更新 | Observation、Interpretation、風險因子、政策摘要 | Risk Assessment | 直接呼叫照護者或緊急服務 |
| Intervention Agent | Policy Gateway 核准 | Risk、Policy decision、channel state | Intervention、delivery outcome | 修改政策、擴大通知對象 |
| Long-term Observer Agent | 夜間／閒置排程 | Event Ledger、Baseline、Health Context | Baseline、Finding、Hypothesis | 宣告診斷、直接啟用緊急規則 |
| Memory/Consolidation Agent | 事件完成、背景分析完成 | 全部可授權記憶層與 retention policy | 摘要、版本、衰減／封存決定 | 繞過同意、刪除不可刪審計資料 |

## 3. 共用 Agent Runtime

Runtime 應提供以下能力，讓 Agent 只處理領域工作：

- typed tool schema：資料查詢、模型呼叫、寫入與通知都經過 schema 驗證。
- context builder：依 `subject_id`、事件類型與 policy scope 組出最小必要 context。
- model router：統一處理 T0–T3、deadline、重試、成本與 fallback。
- output validator：拒絕缺少 evidence、provenance、confidence 或版本的輸出。
- idempotency：每個 job、寫入與介入都有可重複執行的 key。
- audit hook：記錄 actor、工具、輸入引用、輸出摘要、policy decision 與錯誤。
- human-in-the-loop：在假設確認、政策變更、L3/L4 或資料衝突時建立人工工作項。

## 4. Agent 執行合約

每輪執行至少包含：

1. 取得工作與權限 scope。
2. 載入最小必要 context snapshot。
3. 宣告要查詢的 evidence refs 與預計使用的模型路由。
4. 執行工具／模型，對結果做 schema、confidence、provenance 與 data quality 驗證。
5. 產生 typed output，寫入正確記憶層，不覆寫事實。
6. 若結果不足，補取證據、升級模型或轉人工；不可自行猜測補值。
7. 記錄耗時、錯誤、token/cost、決策與後續工作。

## 5. 典型協作順序

即時事件：`Event Gateway → Router → modality workers → Event Understanding → Ledger → Risk → Policy Gateway → Intervention → Ledger`。

背景觀察：`Scheduler → Observer → Baseline/Trend features → Hypothesis → Consolidation → Watchlist review`。

脈絡更新：`Health/FHIR/錨定照護資料 → Context Normalizer → Watchlist Agent → human/policy review → Active Watchlist`。

## 6. 權限邊界

| 能力 | 可用 Agent | 限制 |
|---|---|---|
| 讀 Raw Evidence | Event Understanding、受限 Observer | 需 evidence scope；原檔不直接暴露給不需要的 Agent |
| 讀 Medical Context | Watchlist、Risk、Observer | 只讀摘要與授權欄位，保留來源與版本 |
| 寫 Event Ledger | Event Understanding、Risk、Intervention | append/version only |
| 寫 Watchlist | Watchlist、Consolidation | candidate 與 active 分離，active 需審核 |
| 發送通知 | Intervention | 只能使用 Policy Gateway 核准的 channel、對象與 level |
| 啟動 L4 | Policy Gateway + deterministic executor | Agent 不具直接權限，必須滿足 gate |

詳見 [05_RISK_AND_INTERVENTION.md](05_RISK_AND_INTERVENTION.md) 與 [07_MODEL_ROUTING_AND_RUNTIME.md](07_MODEL_ROUTING_AND_RUNTIME.md)。
