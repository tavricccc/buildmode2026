# 08 · 實作順序與驗證

## 實作 Tracks

- Backend/Data：FastAPI、SQLite、REST/WebSocket、media、state machines、settings/versioning。
- Frontend：Setup/Settings、model install jobs、Dashboard 與 typed clients。
- Model Runtime/Gateway：統一 OpenAI-compatible client、local runtime launcher、cloud endpoints、capability probes 與 schemas。

## Gates

1. 建立 schema、fixtures、stub OpenAI-compatible server 與設定版本機制。
2. Replay → stub vision → event → SQLite → WebSocket → Dashboard。
3. 前端完成 cloud model 登錄、probe、activate；以測試 endpoint 跑 vision/ASR/analysis。
4. 前端完成本地 catalog 安裝；至少在一個 NVIDIA 和一個 AMD/CPU-capable runtime 通過相同 API contract。
5. RTSP + vision loop、mic + transcription、agents/policy/Telegram/Observer 完整 E2E。
6. 穩定化：invalid JSON、timeout、429、endpoint restart、GPU OOM、CPU fallback、設定衝突與 rollback。

## 驗證矩陣

| 測試 | 驗證重點 |
|---|---|
| Model contract | local/cloud 同 fixture、OpenAI compatibility、schema、capabilities |
| Installer | allowlist、checksum、resume/cancel、失敗不破壞 active model |
| Hardware | NVIDIA、AMD、CPU probe 與 fallback，不出現 Apple-only dependency |
| Settings | schema-driven UI、secret write-only、version conflict、restart、rollback |
| Vision/Replay | bounded queue、frame order、事件狀態、hydration dedup |
| Audio | VAD、cloud/local transcription、TTL、bounded queue |
| Security | SSRF、任意 path/URL、secret、provider response/log redaction |

舞台前固定測試影片、prompt/schema、model endpoint profile 與 stub fallback。UI 必須顯示實際 deployment type、endpoint、model revision，禁止把 fallback 偽裝成原模型。
