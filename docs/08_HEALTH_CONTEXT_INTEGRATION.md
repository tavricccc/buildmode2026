# 08 · Health Context Integration

## 1. 目的與邊界

健康資料的用途是提供事件理解、個人 baseline、已確認風險因子與照護偏好的脈絡，不是讓 Agent 自動診斷。每次推論只取與事件或背景工作相關的最小必要欄位；原始資料與正規化摘要要分開保存。

## 2. 資料來源

| 來源 | 可用資料例子 | 進入系統前要處理 |
|---|---|---|
| Apple HealthKit／智慧裝置 | 活動、步數、睡眠、心率或裝置可提供的量測 | 使用者授權、樣本時間、單位、裝置與資料完整度 |
| FHIR 臨床資料 | Observation、Condition、Medication、Allergy、CarePlan 等 | 來源機構、資源版本、患者身份、撤回與範圍 |
| 照護者設定 | 作息、聯絡對象、通知偏好、確認流程 | 角色權限、有效期、版本與變更審批 |
| 人工照護紀錄 | 已確認事件、回饋、例外說明 | actor、時間、證據或理由、修正歷史 |

## 3. Ingestion 與正規化

資料流程：`授權來源 → Connector → Raw External Record → Identity/Time/Unit Normalizer → Canonical Context → Context Snapshot → Agent query`。

Normalizer 必須處理：subject identity mapping、時區與時間精度、單位轉換、裝置時鐘、重複資料、來源優先級、缺值、撤回與同步延遲。不可因解析失敗而靜默丟棄資料；要建立 ingestion error 與 coverage record。

## 4. Context Snapshot

每次事件或背景分析固定一個 snapshot，包含：

- `snapshot_id`、subject、建立時間、資料水位與來源 revision。
- 目前有效的 Medical Context、CarePlan、Active Watchlist 與 Baseline version。
- 權限／同意 scope、欄位 purpose 與 expiry。
- 使用的 normalizer、schema 與 mapping version。
- 排除的資料與原因，特別是逾期、撤回、身份無法確認或品質不足的資料。

snapshot 讓事件可以重現，也避免後來同步的新病史悄悄改寫已完成的判斷。

## 5. Context Compiler 與 Watchlist

Context Compiler 把外部資料整理成三類輸入：

1. `confirmed_facts`：已確認條件、用藥、過敏、照護安排與人工設定。
2. `risk_factors`：只描述與觀察策略相關的脈絡，保留來源，不等同診斷推論。
3. `observation_questions`：下一次事件或背景分析值得檢查的可觀察問題。

Watchlist Agent 可依此提出 watch item，但每個 item 要標記來源（human、policy、agent_suggested）、優先級、觀察窗口、資料來源、停止條件與是否需要審核。Agent-suggested item 不得直接成為 L4 policy。

## 6. FHIR 對映原則

外部 FHIR 資源保留原始 resource reference 與版本；內部模型只建立必要的 canonical projection。量測資料與主張可作為 Observation projection，但 Risk Assessment、Hypothesis 與 Intervention 不應為了方便而全部偽裝成臨床 Observation。診斷、用藥、照護計畫與風險評估保持各自語意。

## 7. 同意、撤回與最小化

- 讀取 HealthKit/FHIR 之前要有可驗證的 consent scope、目的與到期時間。
- scope 撤回後停止新讀取；已保存資料依 retention/deletion policy 處理並留下 audit。
- 事件理解只傳送必要的 context 摘要；不把完整病史、全部量測或沒有必要的身份資料送給模型。
- 照護者可見範圍與被照護者、臨床人員、系統管理員分開定義。

## 8. 資料品質與衝突

來源時間、單位、裝置狀態與覆蓋率進入 `data_quality`。來源衝突不由 LLM 私自選一個答案；依來源優先級、時間與人工規則處理，無法解決時建立 conflict record，並讓 Risk 降低 certainty 或要求確認。

部署與密鑰管理見 [09_DEPLOYMENT_AND_SECURITY.md](09_DEPLOYMENT_AND_SECURITY.md)，長期使用方式見 [06_LONG_TERM_OBSERVER.md](06_LONG_TERM_OBSERVER.md)。

