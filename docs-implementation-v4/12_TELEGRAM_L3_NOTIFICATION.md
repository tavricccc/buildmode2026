# 12 · Telegram L3 通知

沿用 v3 的 Telegram Bot long polling、sendMessage/sendPhoto、opaque callback token、allowlist、idempotency、acknowledged/false_alarm/failed 狀態與「不是 L4」邊界。

前端本機管理頁可修改 Bot token（write-only）、allowed chat IDs、poll timeout、retry、ack timeout、是否附 evidence、訊息模板允許欄位與各事件通知 policy。Recipient 變更與清除 token 需二次確認並建立 config version/audit event。

模型只能提出 action type，不能指定 chat ID、修改模板或取得 token。通知只在 Policy Gateway 核准且 DB commit 後發送。Token、完整健康分析與未授權影像不得出現在 logs 或 provider prompt。
