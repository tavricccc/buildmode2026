# Care Agent 實作文件 v5

版本：2026-09-05

v5 收斂成固定三層：**本地便宜過濾 → Gemini 做主要理解 → MiniMax 只處理需要深挖的事件**。不再維持 v4 那種「所有模型都抽象成同一 serving runtime」的大包袱。

## 核心架構

```text
RTSP / Replay
  ↓
L1 本地 Person Gate
  ├─ 無人 → 大多數窗口略過
  └─ 有人 → 建立短影片
             ↓
L2 Gemini 3.5 Flash Lite
  → 跌倒 / 喝水結構化 observation
  → escalation.required
             ↓
      Event State Machine
        ├─ 一般 → SQLite / Dashboard
        └─ escalation
               ↓
L3 MiniMax M3
  → 短影片 + Gemini 結果 + 必要文字上下文
  → deeper analysis
               ↓
Deterministic Policy Gateway
  → Dashboard / Telegram
```

## 三層責任

### L1：本地 Person Gate

只判斷「畫面是否有人」。不可判斷跌倒、喝水、姿勢、身份、情緒或健康風險。可用 YOLO11n person class 等小型 detector，但 contract 與實作解耦。

無人時不跑一般 Gemini job，但保留低頻 safety heartbeat；L1 掛掉時 fail-open，不能把故障當成沒人。

### L2：Gemini 3.5 Flash Lite

預設 model：`gemini-3.5-flash-lite`，可設定。使用 Google 原生 Gemini REST，不要求 OpenAI-compatible。

- `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=...`
- <=20MB：`inline_data` + Base64 + MIME type。
- 大檔：Files API resumable upload → 等 `ACTIVE` → `file_data.file_uri`。
- 可送 video / audio / image / text；未實測能力仍需 capability probe。

### L3：MiniMax M3

只在 escalation 時呼叫，不是每個窗口都跑。

正常輸入必須同時包含：相關短影片 evidence、Gemini 結構化結果、escalation reason；必要時再加 transcript、event state、health/event aggregate。影片缺失時才允許 degraded text-only，且 UI / SQLite 必須明示。

MiniMax 不能直接通知，仍要經 Policy Gateway。

## 排程

- L1 持續跑低成本 sampled frame。
- `person_present=true` → Gemini 依設定 cadence 分析 5–10 秒短片。
- `person_present=false` → 跳過一般 Gemini，只保留例如每 30–60 秒一次 heartbeat。
- `suspect / confirmed` → 繞過 L1，強制 Gemini follow-up。
- Gemini 或 deterministic policy 可要求 MiniMax escalation。
- 每層 queue 有上限；普通 stale job 可丟，高風險 job 不可被覆蓋。

## 文件

1. [01_PIPELINE.md](01_PIPELINE.md) — 三層 pipeline、影片、音訊、失敗策略。
2. [02_DATA_AND_POLICY.md](02_DATA_AND_POLICY.md) — Event、SQLite、routing audit、Policy、Observer。
3. [03_API_AND_FRONTEND.md](03_API_AND_FRONTEND.md) — REST/WebSocket、Dashboard、三層狀態與設定 UI。
4. [04_SETUP_DEPLOY_VERIFY.md](04_SETUP_DEPLOY_VERIFY.md) — Setup、secret、Docker/WSL、部署與驗收。

規格衝突時採用 v5 → v4 → v3。v4 中「所有模型都必須 OpenAI-compatible」與「單一 cloud vision layer」在 v5 不再適用。

