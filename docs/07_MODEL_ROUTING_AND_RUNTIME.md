# 07 · Model Routing 與 Runtime

## 1. 目的

動態路由的目標是讓普通事件保持低延遲、低成本與本地處理；只有風險、關聯性或不確定性足夠高時，才使用較昂貴的多模態或強模型。路由是可審計的系統決策，不是由 LLM 自由選擇工具。

### Provider 對齊

本機 vLLM 是主要模型 provider。三個邏輯 Agent 透過 `ModelRuntime` 呼叫模型，不直接依賴 MiniMax 或其他供應商；provider 可替換，但輸出 schema、evidence scope、deadline 與 audit 欄位固定。

~~原 HTML 所描述的「所有高階推理都交給雲端 MiniMax M3」不再是目標行為。~~ 若使用 MiniMax，僅限於明確授權的特定 VLM 工作，且不可取得通知、政策寫入或任意 SQL 權限。

## 2. 路由等級

| Route | 使用時機 | 執行內容 | 失敗／低信心 |
|---|---|---|---|
| T0 Archive | 明顯正常、無 watchlist 命中 | 保存最小事件索引，延後抽樣 | 背景抽樣或人工標註 |
| T1 Local Light | 一般事件 | 本地 ASR、音效分類、規則、小模型 | 升級 T2 |
| T2 Local Multimodal | 模態需要交叉驗證、watchlist 命中 | 本地 VLM + ASR + Audio，縮短窗口 | 升級 T3 或 L1/L2 |
| T3 Strong Fast Path | 高風險、強衝突、本地結果低信心 | 強模型、完整事件包、最小照護摘要 | 人工確認與保守介入 |

## 3. Router 輸入與決策

Router 至少評估：`urgency`、`uncertainty`、`watchlist_match`、`evidence_quality`、`modality_conflict`、`subject_context_relevance`、`deadline`、`device_health`、`queue_load` 與 `cost_budget`。

建議用可解釋的 reason codes 產生路由：例如 `high_urgency`、`low_local_confidence`、`impact_floor_combination`、`missing_audio`、`watchlist_match`。不使用不可追蹤的單一黑盒分數作為唯一升級原因。

路由決策必須保存：候選摘要、輸入特徵、route、reason codes、模型 ID/version、policy/runtime version、開始／結束時間、是否升級、成本／token、結果與 fallback。

## 4. Runtime 佇列

| Queue | 優先級 | 工作 | 資源 |
|---|---|---|---|
| realtime-critical | 最高 | L2–L4 候選、衝突、高風險 | 保留 CPU/GPU 配額 |
| realtime-normal | 中 | T1/T2 普通事件 | 平行數上限 |
| caregiver-response | 高 | 等待回應、timeout、delivery retry | 不依賴模型可用性 |
| background | 低 | Observer、embedding、摘要、壓縮 | 可取消、夜間／閒置 |
| dead-letter | 人工處理 | 無法解析、schema 失敗、重試耗盡 | 僅人工或修復工作流 |

所有 queue 都需有最大並行數、deadline、retry/backoff、circuit breaker、取消與 dead-letter 行為。背景工作不可阻塞即時與通知 queue。

## 5. 模型輸出規約

模型只能輸出版本化 JSON schema；至少包含 claim、evidence_refs、confidence、uncertainty、data_quality、provenance 與 model_version。Schema 驗證失敗、evidence 不存在、confidence 不在合法範圍或 output 內容超出 agent scope 時，結果標記 invalid，不得直接進 Risk。

World State Agent 另須輸出 `known[]`、`unknown[]`、`observability` 與可選的 `question_candidate`；Resident Agent 的 transcript 只可在 conversation window 中存在；Caregiver Agent 不接收未聚合的原始影音。

## 6. 本地優先與強模型邊界

- 原始影片／音訊預設在本地處理；外部強模型只收到必要 clip、轉錄、特徵與最小 context snapshot。
- 脱敏或 pseudonymization 在出站前完成；外部傳輸要有 consent scope 與 audit。
- 強模型不可取得通知工具、政策寫入工具或直接修改 Medical Context 的權限。
- 強模型結果仍需與本地結果、證據引用與 Policy Gateway 分開保存。

## 7. 降級策略

模型服務不可用時，依序考慮：規則與最近可靠 Observation、縮短窗口重試、L1 Observe、L2 check-in、人工隊列。降級輸出必須明確寫出 `degraded=true` 與原因，不得假裝正常完成。

## 8. Runtime 驗收

- 可用固定 replay dataset 重放事件，得到相同 dedup、路由與 policy inputs。
- T0/T1 不會在沒有升級理由時呼叫 T3。
- 高風險訊號出現時可搶占背景工作；背景工作恢復後不重複寫入結果。
- 所有模型 latency、error、cost、confidence calibration 與 route outcome 可查詢。

事件契約見 [02_EVENT_PIPELINE.md](02_EVENT_PIPELINE.md)，安全限制見 [09_DEPLOYMENT_AND_SECURITY.md](09_DEPLOYMENT_AND_SECURITY.md)。
