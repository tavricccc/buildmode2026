# 01 · 系統架構

## 1. 架構分層

| 層 | 元件 | 職責 | 主要輸出 |
|---|---|---|---|
| 感知 | Camera、Mic、Wearable、Frigate NVR | 捕捉資料、偵測物件／音效、建立事件時間窗 | Sensor Event、Evidence Reference |
| 事件 | Event Gateway、Event Bus、Deduplicator | 去重、關聯、排序、重試與保存事件狀態 | Event Candidate |
| 理解 | Local ASR、Video VLM、Audio Classifier、Fusion | 對事件窗口產生轉錄與模態觀察 | Observation、Transcript |
| Agent | Watchlist、Event Understanding、Risk、Intervention、Observer、Consolidation | 將證據轉成可治理的推論與行動 | Interpretation、Risk、Intervention、Hypothesis |
| 記憶 | Event Ledger、Object Storage、Baseline、Medical Context、Watchlist | 版本化保存、查詢、摘要與留存 | Evidence chain、Context snapshot |
| 治理 | Policy Gateway、Consent、Audit、Notification | 授權、冷卻、人工確認、升級與稽核 | Policy decision、Audit record |

完整元件關係可先閱讀 [00_EXECUTIVE_OVERVIEW.md](00_EXECUTIVE_OVERVIEW.md) 的核心架構段落。

## 2. 核心元件責任

### Frigate NVR

Frigate 是低成本初始感知器與 trigger，不是醫療判斷器。它提供物件、音效或事件時間窗，以及 clip/frame/audio 的證據索引。持續影音是否保存、保存多久，由 consent 與 retention policy 決定。

### Event Gateway / Event Bus

Gateway 將外部 payload 轉成內部事件信封，產生 `event_id`、`correlation_id`、`subject_id` 與時間窗；Bus 負責解耦、重試、優先級與 dead-letter queue。所有 consumer 必須支援 idempotency，避免同一事件重複介入。

### Model Router

Router 以 urgency、uncertainty、watchlist match、證據完整度、裝置狀態與資源預算選擇 T0–T3 路由。路由本身也要寫入 Ledger，以便回顧延遲、成本與誤報。

### Event Ledger

Ledger 是 append-oriented 的事件真相來源：不直接覆寫已產生的判斷；重跑、模型升級、人工修正都新增版本並用 `supersedes_id` 關聯。Blob/object store 保存大型影音，Ledger 保存雜湊、URI、時間、權限與證據關聯。

### Policy Gateway

Gateway 是所有外部行動前的安全閘門，執行 consent scope、角色權限、冷卻時間、重試限制、人工接手、升級計時器與 L4 先決條件。LLM 的輸出只能是輸入之一，不可繞過 Gateway。

## 3. 主要介面

| 介面 | 方向 | 最小契約 |
|---|---|---|
| Event ingest | Sensor → Gateway | source、subject、occurred_at、evidence refs、initial labels |
| Model job | Router → Runtime | job_id、route、input refs、deadline、schema version |
| Model result | Runtime → Ledger | observations、confidence、model version、provenance、data quality |
| Agent message | Agent → Agent | typed event、input refs、requested action、idempotency key |
| Policy decision | Risk → Gateway | risk assessment、policy version、allowed levels、reason codes |
| Intervention result | Channel → Ledger | state、recipient、ack/timeout/cancel、timestamps |

## 4. 一致性與故障原則

- 事件寫入先於介入；若 Ledger 不可寫，禁止發出 L3/L4 行動。
- 推論可重試但介入必須 idempotent，使用 `intervention_key = event_id + policy_version + level`。
- 模型 timeout、缺 clip、裝置離線或模態衝突時，降級到保守觀察、主動確認或人工隊列。
- Event Bus 失敗時保留本地 spool；恢復後按 occurred_at 與 priority 補送，並標記延遲。
- 外部通知回報需可追蹤 delivery、acknowledged、cancelled、expired、escalated 狀態。

## 5. 非功能需求基線

| 面向 | Demo 基線 | 產品化方向 |
|---|---|---|
| 延遲 | L0–L2 事件數秒內完成 | 依事件類型訂定 p95 SLA |
| 可用性 | 本地單機可重啟恢復 | 多節點、斷線可運作、可觀測性 |
| 可審計 | 每次路由／政策／介入有紀錄 | 不可竄改稽核、保留與匯出 |
| 隱私 | 本地優先、最小必要資料 | 權限分層、加密、刪除與同意撤回 |
| 可解釋 | evidence refs + reason codes | 人工標註回饋與模型評估集 |

下一步的事件細節見 [02_EVENT_PIPELINE.md](02_EVENT_PIPELINE.md)，部署邊界見 [09_DEPLOYMENT_AND_SECURITY.md](09_DEPLOYMENT_AND_SECURITY.md)。
