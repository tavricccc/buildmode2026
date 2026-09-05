# 07 · 健康與風險分析

Health Context/Risk 使用 active `analysis` model slot。它可以指向本地或雲端 OpenAI-compatible endpoint，不固定 MiniMax 或任何 model ID。

輸入只包含使用者指定窗口的健康快照、SQL event/hydration aggregates、coverage 與資料限制；預設不傳影片。輸出必須符合 `health-risk.v1`：繁中摘要、risk level、reason codes、supporting facts、uncertainties、recommendations、proposed actions 與 analysis window。

相同 input hash、model、prompt、schema、config version 可快取。Timeout、retry、repair count、cache TTL 與手動 refresh cooldown 均可由前端設定且有安全範圍。

Capability probe 必須驗證 auth、model existence（若 endpoint 支援 `/v1/models`）、structured JSON、timeout/error format；tool calling/streaming 是可選能力。模型不可直接查 SQLite、讀 secret、修改 threshold 或執行通知。

Endpoint degraded 時，SQL 統計、deterministic reminders、事件偵測與歷史 Dashboard 照常運作。
