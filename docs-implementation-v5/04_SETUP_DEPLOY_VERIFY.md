# 04 · Setup、部署與驗證

唯一使用者入口：`bun start`。第一次啟動只需讓 Setup backend + frontend 可用，**不得先下載多 GB 模型**。L1 detector、ASR 等本地 artifact 要等使用者在 Setup 選擇後才下載。

Docker image 同樣不得 bake model weights；模型放外部 cache/volume。Docker 是 optional，不是唯一開發方式。

## Windows + WSL 開發

Backend、frontend、SQLite、replay、cloud API 全部可在 Windows + WSL 測；L1 detector 可先用 CPU/stub；RTSP 可用 replay fixture 先完成 contract。最終部署支援 Windows / Linux / macOS，domain code 不依賴 MLX、Metal、CUDA、ROCm。

## Secrets

Gemini API key、MiniMax/GMI key、RTSP password、Telegram token 只存在 backend secret store / local untracked environment，不得出現在 GET API、frontend bundle、SQLite logs 或 Git。

## Capability probes

Gemini 至少測 auth/model、small video inline_data、Files API + ACTIVE polling、audio/video native input、JSON parser、timeout/quota/error。MiniMax 至少測 auth/model、**video + text 同時輸入**、structured output、timeout/rate limit/error。

Provider 文件沒保證的能力，不可直接寫成 runtime 假設，以 probe 結果為準。

## Implementation gates

1. Replay → L1 stub → Gemini stub → event → SQLite → Dashboard。
2. 真實 L1 person detector。
3. 真實 Gemini native REST，完成 fall/hydration。
4. MiniMax video+text escalation。
5. RTSP、audio/transcript、Telegram、Observer。
6. Windows+WSL / target OS E2E 與故障測試。

## 必測情境

- 空房：L1 大量 skip，但 heartbeat 仍有 Gemini call。
- L1 false negative / crash：fail-open。
- 跌倒 suspect：繞過 L1，Gemini 持續 follow-up。
- Gemini escalation：MiniMax 確實收到影片 + 文字。
- MiniMax timeout：主事件管線不被卡死。
- Gemini timeout：事件標 degraded，不假裝安全。
- replay reset、duplicate delivery、hydration dedup、secret scan、config rollback。

完成標準：**L1 節省大多數無人請求、Gemini 完成常規理解、MiniMax 只在必要時接收原始影片與文字深度判讀，而且任何模型都不能繞過 deterministic policy。**
