# 09 · Deployment 與 Security

## 1. local-first 拓撲

```text
Browser HTTPS
  ↕ WSS continuous media + typed events
Care backend (HTTPS 8002)
  ├─ in-memory 2 FPS / 5 second sampler
  ├─ local Nemotron vLLM (HTTP 8000, loopback)
  ├─ SQLite WAL / Event Ledger
  ├─ Policy / Memory / Agent runtime
  └─ optional Frigate / MQTT / RTSP / Telegram
```

vLLM 只綁本機；Dashboard 才可依 Private LAN policy 綁區網。Production 必須使用受信任 TLS certificate、authentication、network segmentation 與 secret store。

## 2. 資料流安全

- Raw camera/audio 只在本機短暫 buffer/process；不進 SQLite logs。
- 每筆 Observation 保存 hash、window、offset、model/prompt/schema/config version。
- VLM audio WAV request 完成即刪除；transcript 有明確對話 window 與 TTL。
- Caregiver 接收 privacy aggregate；raw evidence 需權限、同意與事件 scope。
- API key 不進 frontend bundle、URL、console、SQLite 或 Git。

## 3. 權限邊界

Browser 只能呼叫 allowlisted API；不能提交任意 SQL、filesystem path、model URL 或 recipient。LLM 不能修改 policy/threshold、直接發通知、建立 L4、讀取無關 evidence。

## 4. 可靠性

SQLite commit 後才 broadcast；WSS 丟失時由 REST resync。vLLM timeout/invalid 時保留 degraded local observation。stream、VLM、audio、MiniMax、Telegram 任一失效不得拖垮歷史查詢與 Dashboard。

## 5. 威脅模型

| 威脅 | 對策 |
|---|---|
| VLM hallucination | strict schema、unknown、provenance、cross-window state machine |
| prompt injection / 惡意語音 | content 是 evidence；tools/policy 分離 |
| raw media 外洩 | local-only、TTL、scope、aggregate |
| 重複事件／通知 | dedup、cooldown、idempotency key |
| 偽造 callback | allowlist、opaque token、sender/chat/expiry 驗證 |
| 長時間無資料 | coverage/unobservable，不當作正常 |

## 6. 運維驗收

需能檢查 backend/vLLM/DB/stream/audio/queue 狀態、GPU/CPU/RAM、model revision、latency、VLM error rate、window drop、retention 與 reconnection。部署腳本不得自動開啟未授權的外部服務。
