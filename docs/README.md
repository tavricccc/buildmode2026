# AI 長照 Agent OS 設計文件索引

版本：1.0 · 2026-09-04

這組文件定義從事件感知到長期照護洞察的完整架構。每份文件都可獨立閱讀；文件中的相對鏈接指向同一套設計基線，流程以步驟、狀態表與資料契約描述，方便工程實作與 code review。

## 文件導覽

| 編號 | 文件 | 核心問題 |
|---|---|---|
| 00 | [執行摘要](00_EXECUTIVE_OVERVIEW.md) | 為何這樣設計、邊界在哪裡？ |
| 01 | [系統架構](01_SYSTEM_ARCHITECTURE.md) | 元件如何分層與互相協作？ |
| 02 | [事件管線](02_EVENT_PIPELINE.md) | 一個事件如何從 trigger 走到可審計結果？ |
| 03 | [Agent 架構](03_AGENT_ARCHITECTURE.md) | 各 Agent 的責任與權限如何切開？ |
| 04 | [記憶體與資料模型](04_MEMORY_AND_DATA_MODEL.md) | 哪些是證據、事實、推論與暫時假設？ |
| 05 | [風險與介入](05_RISK_AND_INTERVENTION.md) | 風險如何映射到 L0–L4 行動？ |
| 06 | [長期觀察](06_LONG_TERM_OBSERVER.md) | 如何從歷史事件建立 baseline、trend、pattern？ |
| 07 | [模型路由與 Runtime](07_MODEL_ROUTING_AND_RUNTIME.md) | 何時用本地模型、何時升級強模型？ |
| 08 | [健康脈絡整合](08_HEALTH_CONTEXT_INTEGRATION.md) | HealthKit、FHIR 與照護設定如何安全進入推論？ |
| 09 | [部署與安全](09_DEPLOYMENT_AND_SECURITY.md) | 系統如何部署、隔離、留存與稽核？ |
| 10 | [MVP 與 Roadmap](10_MVP_AND_ROADMAP.md) | 如何從 Demo 逐步走向可驗證的產品？ |
| 11 | [本機 Capture Layer](11_LOCAL_CAPTURE_LAYER.md) | 如何用本機麥克風與攝影機建立可重播事件包？ |
| 12 | [目標架構與 Agent 邊界](12_TARGET_ARCHITECTURE.md) | 新產品方向如何落成可執行的模組邊界？ |

## 建議閱讀方式

- 要快速理解：先讀 00，再看 01、06、09 的「架構與流程」段落。
- 要實作事件 demo：讀 01、02、03、05、07。
- 要設計資料與評估：讀 04、06、08、10。
- 要做醫療或照護場域審查：讀 00、05、08、09，並把「待確認」項目轉成場域政策。
- 要理解本次產品方向：先讀 12，再回看 01、03、04、07 與 10。

## 文件共通約定

目標架構的 Mermaid 原始碼位於 [`diagrams/`](diagrams/)，包含整體架構、World State loop 與照護者聚合流程。parent workspace 的舊 `deliverables/mermaid/` 仍可作比較，但不作本 repo 的唯一來源。

- `occurred_at` 是現象發生時間；`recorded_at` 是系統收到時間。
- `confidence` 是模型對該輸出的信心，不等同於醫療確診率。
- `provenance` 必須能追溯到感測器、資料源、模型、prompt/policy 版本或人工操作。
- `Fact` 與 `Hypothesis` 不可混寫；假設經人工確認後仍保留原始假設與提升原因。
