# Ambient Care Agent OS

> 它不是「看著老人」的 AI，而是在有限資訊下知道什麼值得注意、什麼不知道、什麼時候該問、什麼時候該保持安靜的照護 Agent。

本 repository 是一個 local-first、privacy-aware、可審計的 Ambient Care Agent 原型。Camera、microphone、IoT、手機與 wearable 都只是稀疏感測器；產品核心是把它們轉成 Event Ledger、World State、Uncertainty、Hypothesis 與受政策治理的行動。

## 目前實作路徑

目前先跳過 Frigate；流程模型已切換到 GMI Cloud 的 `MiniMaxAI/MiniMax-M3`，本機 Nemotron Omni vLLM 保留為可切回的影像模型：

```text
HTTPS browser MediaStream (camera + microphone)
  → continuous WebM over WSS /ws/media
  → backend in-memory sampler
  → 2 FPS × 5 seconds = 10 ordered images + optional 5 seconds 16 kHz mono audio
  → configured flow model（預設 GMI Cloud MiniMaxAI/MiniMax-M3；audio 需 capability probe 通過）
  → L0 local change gate（每 5 秒只輸出有／無）
  → 有變化才進 L1 structured Observation / event_candidates
  → temporal posture tracker（跨窗口確認起身／坐下）
  → existing fall/hydration state machine or exceptional recognition_events
  → SQLite Event Ledger
  → WSS /ws
  → Main Agent（同一 Omni、可並行、bounded concurrency）
  → deterministic attention / risk policy
  → persistent event timeline / Agent rounds / Known / Unknown / Next action
```

Frigate、MQTT 與 RTSP adapter 仍保留，等需要時再接回；它們不是目前 VLM 開發的必要條件。GMI key 從 `GMIAPI.txt` 讀入記憶體，該檔案已列入 git ignore。

## 文件入口

**現行規格書是 [docs-implementation-v4](docs-implementation-v4/README.md)。** 規格衝突時依序採用 v4 → v3 → v2 → `docs/`。

| 目錄 | 角色 |
|---|---|
| [`docs-implementation-v4/`](docs-implementation-v4/README.md) | **現行執行契約**。硬體中立、cloud-only P0、模型能力槽位與 provider 限制 |
| [`docs-implementation-v3/`](docs-implementation-v3/README.md) | 前一版,綁定特定模型與 Apple Silicon,已由 v4 取代 |
| [`docs-implementation-v2/`](docs-implementation-v2/README.md) | Frigate 時期的執行契約,保留供追溯 |
| [`docs/`](docs/README.md) | 產品與架構背景,非執行契約 |

實際 provider 能力與已知限制見 [14 · Provider 能力與限制](docs-implementation-v4/14_PROVIDER_CONSTRAINTS.md);交付階段 P0/P1/P2 見 [00 · 產品範圍與完成定義](docs-implementation-v4/00_SCOPE_AND_DEFINITION_OF_DONE.md)。

1. [執行摘要](docs/00_EXECUTIVE_OVERVIEW.md)
2. [系統架構](docs/01_SYSTEM_ARCHITECTURE.md)
3. [事件 Pipeline](docs/02_EVENT_PIPELINE.md)
4. [Agent 架構](docs/03_AGENT_ARCHITECTURE.md)
5. [Memory 與資料模型](docs/04_MEMORY_AND_DATA_MODEL.md)
6. [Risk 與 Intervention](docs/05_RISK_AND_INTERVENTION.md)
7. [Long-term Observer](docs/06_LONG_TERM_OBSERVER.md)
8. [Model Routing 與 Runtime](docs/07_MODEL_ROUTING_AND_RUNTIME.md)
9. [Health Context](docs/08_HEALTH_CONTEXT_INTEGRATION.md)
10. [Deployment 與 Security](docs/09_DEPLOYMENT_AND_SECURITY.md)
11. [MVP 與 Roadmap](docs/10_MVP_AND_ROADMAP.md)
12. [Agent Memory 與 Research layer](docs/11_AGENT_MEMORY_AND_RESEARCH.md)

## 安全與產品邊界

- Model output 永遠先是 Observation 或 Hypothesis，不直接是 Fact、診斷或行動。
- `fall`、`hydration` 優先使用既有事件欄位與 state machine；只有家庭聲音、人物活動、非人物物件等例外才建立 `recognition_events`。
- `UNKNOWN` 是合法且重要的結果；不可用最後觀察位置冒充目前位置。
- Default Silent；詢問、提醒、警告都要經過 attention／interruption policy。
- 原始影像與音訊只在本機短暫保留；獲授權的有變化窗口會送至設定的 flow model endpoint，SQLite 保存必要 metadata、hash、confidence、窗口與 provenance，不保存 raw stream 或 API key。
- 目前不做診斷、治療、自動通報或 L4 emergency executor。
- Caregiver 預設收到 privacy-aggregated summary，不是完整生活紀錄。
- Main Agent 會保存 facts、跨 frame 時序、existing-first mapping、Unknown/Hypothesis、attention score、policy gates 與 next action；模型建議不等於已執行 action。

## 啟動

需求：Python 3.10+、Node.js 18+、GMI Cloud API key（`GMIAPI.txt`）；本機 vLLM `nemotron_omni` 可選。`.env` 預設使用 HTTPS、Care Agent `8002`：

```powershell
# D:\Longcare
npm start
```

前端：[https://192.168.50.140:5173](https://192.168.50.140:5173)

第一次使用自簽憑證時，請信任 [certs/lan.crt](certs/lan.crt)，再允許 camera／microphone 權限。前端串流後，VLM panel 應顯示 `10 frames / 5s`；`audio`、`sound`、`emotion` 只有 active model 通過 audio capability probe 或獨立 ASR 已啟用時才可顯示可用結果，否則應顯示 unavailable/unknown。

## 驗證

```powershell
npm run verify
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Frigate compose 只在需要時使用：`npm run frigate:config`、`npm run frigate:up`。目前主流程不依賴 Frigate。
