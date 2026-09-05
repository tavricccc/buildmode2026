# Ambient Care Agent OS 設計文件索引

## 核心定位

本系統不是 surveillance dashboard，而是 **在有限感知下建立生活脈絡** 的照護 Agent。它要能分辨：

- Known：目前有證據支持的事實。
- Unknown：目前沒有足夠證據知道的事。
- Hypothesis：值得保留但尚未確認的解釋。
- Attention：是否值得打擾長者或照護者。
- Next action：詢問、提醒、安靜等待、人工查看或升級。

Camera、audio、Frigate、IoT、手機與 wearable 都是 sensors，不是產品本身。所有輸入先轉為 typed event，進入共享的 World State／Event Ledger。

## 文件導覽

| 文件 | 主題 |
|---|---|
| [00](00_EXECUTIVE_OVERVIEW.md) | 產品價值、範圍與安全邊界 |
| [01](01_SYSTEM_ARCHITECTURE.md) | Sensor、Event Bus、World State、Agent 與 Policy |
| [02](02_EVENT_PIPELINE.md) | Correlation、窗口、Observation、Unknown 與 dedup |
| [03](03_AGENT_ARCHITECTURE.md) | Context Sentinel、Resident Interaction、Caregiver Agent |
| [04](04_MEMORY_AND_DATA_MODEL.md) | Event Ledger、Semantic/Scheduled Memory、provenance |
| [05](05_RISK_AND_INTERVENTION.md) | Default Silent、attention budget、分級介入 |
| [06](06_LONG_TERM_OBSERVER.md) | 個人 baseline、趨勢、Privacy Aggregation |
| [07](07_MODEL_ROUTING_AND_RUNTIME.md) | 本地 Nemotron vLLM、路由與資源限制 |
| [08](08_HEALTH_CONTEXT_INTEGRATION.md) | Health snapshot、同意、缺值與衝突 |
| [09](09_DEPLOYMENT_AND_SECURITY.md) | local-first 部署、TLS、威脅與復原 |
| [10](10_MVP_AND_ROADMAP.md) | 目前實作狀態、下一階段與 DoD |
| [11](11_AGENT_MEMORY_AND_RESEARCH.md) | Main Agent trace、記憶分層、Research layer 與 transcript |

## 規格優先級

1. 本文件集與 `SPEC.md` 的 current v0.2 決策。
2. `docs-implementation-v2/` 的具體 API、SQLite、部署與驗收契約；其 v3 amendment 優先於原本 Frigate-first 描述。
3. 原始 HTML 僅為歷史原型，不是 current contract。

## 共通欄位

所有事件、Observation、Hypothesis、Finding 與 action 都應保留 `id`、`subject_id`、`occurred_at`、`source`、`confidence`、`provenance`、`schema_version`、`config_version` 與 `uncertainty`。缺資料用 `unknown`／`unobservable` 表達，不可靜默轉成正常。

## 目前 runtime 基線

本機 vLLM `nemotron_omni` 是目前多模態 runtime。Browser stream 以 2 FPS 取樣，5 秒形成 10-frame + 5 秒 audio window；Frigate 是可替換、可延後的 sensor adapter。詳細 roadmap 見 [10_MVP_AND_ROADMAP.md](10_MVP_AND_ROADMAP.md)。
