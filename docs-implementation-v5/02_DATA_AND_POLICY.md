# 02 · Data、Event、Policy 與稽核

沿用 v4 的 events、evidence、hydration_sessions、health_samples、analyses、actions、transcripts、daily_summaries、observer_findings、notification_deliveries。

新增 `pipeline_runs`，每個視覺窗口至少記錄：L1 判斷與 confidence、Gemini `called / skipped_l1 / heartbeat / forced_high_risk / failed`、Gemini model/call id/escalation reason、MiniMax `not_required / called / degraded_text_only / failed`、MiniMax model/call id、evidence ref、latency、config version。

每個 event 必須能反查完整路徑：`L1 → Gemini → MiniMax（若有）→ Policy → action`。

## Policy Gateway

Policy Gateway 不呼叫模型，只讀已驗證欄位與設定。模型可以提出 interpretation、uncertainty、risk/action 建議；不能改 threshold、指定任意 Telegram recipient、直接發通知或查任意 SQL。

## Agents

保留同 backend 內的 Event Understanding、Health Context、Risk、Intervention logical agents，不拆成 service。Intervention 只能執行 Policy Gateway 核准 action。

## Observer

每日彙總 hydration、fall、health、coverage，比較 7/30 日 baseline。只有達設定變化門檻才呼叫 MiniMax，且只送 fixed-size summaries/aggregate，不需要把整天影片丟過去。

## Telegram

維持 v4：Bot long polling、allowlist、opaque callback token、acknowledged / false_alarm / failed。通知由 deterministic policy 決定，模型不可直接操作 Bot。

