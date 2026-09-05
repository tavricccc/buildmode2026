# 00 · 產品範圍與完成定義

## Demo 核心鏈

```text
手機 RTSP → bounded frame buffer → fixed-rate vision loop
麥克風 → VAD → transcription model
               ↓
Model Gateway → OpenAI-compatible endpoint
                ├─ local model server (AMD/NVIDIA/CPU)
                └─ cloud provider
  → validated observations/transcripts
  → 跌倒／喝水狀態機 → SQLite → WebSocket → Dashboard
```

Vision、transcription、analysis 和可選 speech model 都由前端選擇、安裝、probe、啟用。沒有有效 active model 時顯示 `configuration_required`，不假裝成功。

## 必做

- RTSP/replay、跌倒、喝水、Fake Health、SQLite、Dashboard、Telegram L3、Observer 與 logical agents 維持 v3 能力。
- 所有模型呼叫都經統一 OpenAI-compatible Model Gateway；本地和雲端使用相同 domain contract。
- 本地模型由前端 catalog 安裝並選擇 AMD/NVIDIA/CPU runtime；雲端模型由前端設定 endpoint/key/model 後加入 registry。
- 前端可設定 camera、models、runtime/device、sampling、timeout/retry、audio、threshold、飲水、Observer、通知與 retention。
- Secret 可由前端覆寫或清除，但 API 只回 configured metadata。
- 設定先驗證再建立 config version；每次 model call 記錄 endpoint、model、prompt/schema 和 config version。

## 階段分層

v4 描述目標架構;交付分三階段,文件其餘章節以此界定範圍。

| 階段 | 內容 |
|---|---|
| **P0** | cloud-only 部署。影片片段 → vision model → `VisionObservation` → 跌倒/喝水狀態機 → SQLite → REST/WebSocket → Dashboard。model ID 與 endpoint 由設定進入,呼叫走 Model Gateway。 |
| **P1** | Telegram L3、健康與風險分析、Long-term Observer、獨立 ASR 管線、Setup/Settings 完整表單。 |
| **P2** | 本地模型 catalog 安裝(下載、checksum、續傳)、AMD/NVIDIA/CPU runtime probe 與 supervisor、config version 與 rollback、多硬體驗收。 |

P0 不要求完整的安裝/啟用流程,但 model ID、base URL、片段參數必須是設定值而非寫死常數——否則規格書描述的 capability slot 與實作不一致。

## 不做

- MLX、Metal、Apple detector 或 Apple-only 必要依賴。
- 自動安裝 GPU kernel driver、接受任意模型 URL/path/package。
- 醫療診斷、自動 L4、多租戶與完整 RBAC。

## Definition of Done

1. `bun start` 可進 Setup，從前端完成本地或雲端模型配置。
2. Vision、transcription、analysis 各可安裝 local 或 cloud model，切換不改 domain code。
3. 本地 runtime 對 NVIDIA、AMD 與 CPU 做 capability detection，不相容選項不可啟用。
4. Application/domain code 不含 `darwin`、`mlx`、`mps` 或 GPU vendor inference 分支。
5. Timeout、429、invalid schema、local runtime crash 都可降級且不破壞歷史查詢。
6. Settings 覆蓋所有 ui-editable/write-only secret 欄位，具驗證、restart、version 和 rollback。
7. Secret 不出現在 bundle、GET response、DB logs、console 或 Git。
8. Replay 跌倒／喝水、mic transcription、Telegram acknowledgement、Observer 與 rollback 均通過 E2E。
9. 每筆事件可反查 model endpoint、deployment type、evidence、prompt/schema/config version。
