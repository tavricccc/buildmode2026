# 11 · Agent 記憶、分析層與研究層

## 1. 架構結論

這幾個 Agent 的方向合理，但不應讓每個 Agent 都直接修改其他 Agent 的狀態。建議採用「共享 Ledger、分層輸入輸出、不可越權升格」：

```text
Sensor / Omni Observation
          ↓
Main Agent：情境分析與注意力判斷
          ↓
Deterministic Policy：action proposal gate
          ↓
Decision Memory（短期）＋ Abstraction Memory（中期）
          ↓
Research / Analysis Agent（長期 aggregate）
          ↓
Research Note / Care Notice proposal
          └──────────────→ 供 Main Agent 與抽象層下次參考
```

「Main Agent」負責當下 window 的判斷；「Decision layer」負責可重現的裁決；「Abstraction layer」負責把多輪資訊壓縮成可讀情境；「Research layer」負責長期趨勢與研究假設。它們不是四個互相自由對話的模型服務。

## 2. 各層責任

| 層 | 讀取 | 輸出 | 保存與權限 |
|---|---|---|---|
| Omni Observation | 10 frames + audio | typed Observation、speech transcript、event candidates | 原始 media 只在 local bounded window |
| Main Agent | current Observation、既有 events、recognition events、近期摘要 | facts、時序、event assessment、Unknown/Hypothesis、risk、attention、next action | `agent_runs`；不能直接執行 action |
| Decision Policy | Main Agent judgment、事件狀態、confidence、coverage、cooldown | `silent`、`observe`、`ask`、`remind`、`dashboard_alert` proposal | 程式 deterministic；fail closed |
| Decision Memory | policy decision、理由、attention score | 短期注意事項 | `agent_notes.layer=decision`，預設 24 小時 |
| Abstraction Memory | facts、events、unknowns、hypotheses | situation summary | `agent_notes.layer=abstraction`，預設 7 日 |
| Research Agent | privacy-aggregated daily/weekly summaries、baseline、coverage | finding、研究假設、care notice proposal | `layer=research`；預設需審核 |

## 3. 每輪分析與裁決順序

每一輪 Main Agent 必須按以下順序輸出可稽核摘要，不把內部 chain-of-thought 傳到 UI：

1. 只列 `observed_facts`，每項都能回到 frame/audio/window。
2. 依 frame 順序產生 `temporal_assessment` 與 `situation_phase`。
3. 先對應既有 `fall`／`hydration`，再判斷 sound/person/object/scene 例外。
4. 列出 `unknowns`、`hypotheses`、`uncertainty_reasons`，不可把未知補成正常。
5. 提出 `risk_level`、`attention_level`、`proposed_action` 與 `next_action`。
6. Deterministic policy 再檢查 evidence、confidence、existing-first、coverage、critical signal、cooldown 與 consent 邊界。

目前 attention score：

```text
attention_score = 15 × model_confidence
               + 10 × visual_confidence
               + 75 × event_signal
               - uncertainty_penalty

event_signal = event_confidence × event_type_weight
```

例行人物出現、家電或物件事件權重低；fall、impact、alarm、fire、smoke 權重高。高信心的正常坐姿仍應保持 `silent`。低信心或 evidence 不足固定 `insufficient_data → silent`。critical fall recovery deadline、fire/smoke/alarm、distressed audio 才能覆蓋一般 action proposal。

## 4. 每輪事件 trace

每一輪會在 `agent_run_events` 保存並經 `/ws` 即時送出：

- `agent.analysis.started`
- `agent.context.built`
- `agent.judgment.ready`
- `agent.policy.evaluated`
- `agent.memory.updated`
- `agent.action.proposed`
- `agent.analysis.completed` 或 `agent.judgment.failed`

前端顯示的是這些可審計摘要、事件階段與 policy 結果，不顯示隱藏推理 token。`action_executed=false` 代表目前只是 proposal，沒有呼叫 speak/notify executor。

## 5. 記憶層與跨層注意事項

目前的 `agent_notes` 是小型、受控的記憶文件：

- `decision`：保存當下「為什麼值得／不值得注意、目前 action、next action」，短 TTL，供近期 Main Agent 參考。
- `abstraction`：保存跨欄位情境、事實、未知與假設，不保存 raw media，供後續 Context Sentinel 或 Research 使用。
- `research`：未來保存日／週 aggregate、個人 baseline、趨勢與研究假設；不得直接覆寫 decision/abstraction，透過 `target_layers` 形成待審核注意事項。

每一筆 note 都必須有 `source_agent`、`source_run_id`、`source_window_id`、`confidence`、`privacy_level`、`expires_at`、`dedup_key` 與必要的 `requires_review`。Research note 若要影響前兩層，必須建立新的 reviewed note 或 config version，不能靜默修改歷史記憶。

## 6. 語音與 transcript

Omni 在 audio window 存在且偵測到清楚人聲時，可同時產生：

- `speech_detected`
- `speech_transcript`
- `transcript_confidence`
- `transcript_uncertainty_reasons`

只有非空且模型宣告 `speech_detected=true` 的 transcript 才寫入 `transcripts`。目前保存 `zh-TW`、window model call、時間與 `retention_until`；原始 audio 仍在 request 後刪除。Transcript 不是永久記憶，也不是醫療判斷來源；未來若進入 Resident Interaction，還要加 consent、第三方語音遮蔽與更短 conversation TTL。

## 7. 並行、順序與失敗

- Observation 與 Main Agent 都使用同一 Omni endpoint，但由 `VLLM_MAX_CONCURRENCY` bounded semaphore 控制。
- Media sampler 以 `VLLM_MAX_PENDING_WINDOWS` 限制窗口 task；超量會明確記錄 backpressure/skipped。
- 同一 window 以 stream/window/config dedup；同一 note 以 run/layer dedup。
- model timeout、invalid JSON 或 schema mismatch 時，保存 failed run 與原因，policy 固定 silent；不因模型失敗升級通知。
- Research layer 只能讀 privacy-aggregated input；不得把 raw continuous stream 當長期 context。

## 8. 下一步

1. 讓 Main Agent 讀取近期未過期 decision/abstraction notes，並將 note provenance 顯示在 trace。
2. 實作 Context Sentinel 的 World State compiler 與 information gap。
3. 加入 consent/interruptibility 後才接 `ask`／TTS／Whisper。
4. 建立 daily/weekly privacy aggregate，再實作 Research Agent 與需審核的 research note。
5. 用人工確認與正負例資料集評估 false attention、missed attention、transcript quality 與 note drift。
