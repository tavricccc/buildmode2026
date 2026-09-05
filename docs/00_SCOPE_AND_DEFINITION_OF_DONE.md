# 00 · 產品範圍與完成定義

## Demo 核心鏈

```text
RTSP / Replay
  → bounded ring buffer
  → L1 local person-presence filter
      ├─ no person → skip normal L2 calls + sparse heartbeat
      └─ person present / forced follow-up
             ↓
        L2 Gemini 3.5 Flash
        → structured observation
        → event state machine
        → escalation decision
             ↓ when required
        L3 MiniMax M3
        → deeper event / ambiguity / health-risk analysis
             ↓
        deterministic Policy Gateway
             ↓
        SQLite → WebSocket → Dashboard / Telegram L3
```

## 必做

- 單一使用者、單一主要場域；RTSP live 為正式來源，ReplaySource 使用相同 downstream contract。
- L1 本地 person gate 只做 presence filtering，預設允許小型 detector（如 YOLO11n person class），但 detector 可替換。
- L1 具 hysteresis、stale、heartbeat 與 fail-open 行為；不可因 detector failure 靜默停止 Gemini。
- Gemini 3.5 Flash 是 L2 正常語意層，model ID 可由前端設定。
- Gemini 原生 REST adapter 支援 text/image/audio/video；<=20MB 使用 `inline_data`，較大媒體使用 Files API。
- Gemini 輸出版本化 JSON，包含事件 observation、uncertainty 與 `escalation`。
- 跌倒／喝水仍由 deterministic state machine 確認，不讓 Gemini 或 MiniMax 直接建立 confirmed event。
- suspect/confirmed 高風險狀態必須 bypass L1，強制 L2 follow-up。
- MiniMax M3 僅作 L3 escalation；一般窗口不可每次呼叫。
- MiniMax 失效不能阻塞 L1/L2、SQLite、Dashboard 或 deterministic policy。
- SQLite 保存 evidence、L1 decision、Gemini call、escalation routing、MiniMax call、事件、健康、分析與 action。
- Dashboard 顯示三層健康、呼叫率、skip 數、escalation 數、latency、usage/cost（provider 有提供時）。
- Telegram L3、Observer、Fake Health、logical agents、settings versioning 與 secret write-only 保留。
- `bun start` / Docker image build 不自動拉取大型權重；第一次啟動要先能進 `/setup`。
- Windows + WSL 可進行開發與測試；最終 runtime 不綁 Apple-only 技術。

## 不做

- L1 身份辨識、人臉辨識、姿勢／跌倒／喝水語意判斷。
- 醫療診斷、自動緊急服務 L4、多租戶或完整 RBAC。
- 把 MiniMax 當成 Gemini 的無條件 fallback 並全時運行。
- 把 Gemini 強行偽裝成 OpenAI-compatible endpoint。
- 啟動時自動下載數 GB 模型。

## Definition of Done

1. 全新環境執行 `bun start` 後，在不下載大型模型的前提下可進入 Setup UI。
2. Setup 可選擇／下載 L1 detector，並分別設定 Gemini 與 MiniMax provider。
3. L1 no-person 時，大部分 Gemini normal jobs 被 skip；Dashboard 可看到 `skipped_by_l1`。
4. no-person 狀態下仍會依設定執行 sparse Gemini safety heartbeat。
5. L1 unavailable/stale 時，系統 fail-open，不把該狀態當成空房。
6. person-present 時，5–10 秒短影片可送入 Gemini 並得到 schema-valid observation。
7. Gemini 可回傳 `escalation.required`；只有 escalation 或 deterministic force 才建立 MiniMax job。
8. `fall.suspect` / `fall.confirmed` 時不受 L1 no-person 決定抑制，持續 Gemini follow-up。
9. MiniMax timeout/unavailable 時，Gemini/state machine/SQLite/Dashboard 繼續運作。
10. 每個 pipeline window 可反查 L1 decision、Gemini skip/call、Gemini escalation、MiniMax skip/call、reason、latency、model/config version 與 evidence。
11. Replay 跌倒與喝水皆能產生可重現狀態序列，重送不重複計數。
12. Telegram acknowledgement、Observer daily finding、settings rollback 皆可 E2E 驗證。
13. API key 不出現在 frontend bundle、GET response、logs、SQLite raw payload 或 Git。
14. Windows/WSL 開發環境至少能使用 Replay + stub/local L1 + Gemini adapter contract tests；最終部署可在 Windows/macOS/Linux 依 capability 啟動。