# 05 · Risk、Attention 與 Intervention

## 1. 分離三件事

1. **Risk**：證據顯示什麼風險、信心與不確定性。
2. **Attention**：是否值得打擾長者或照護者。
3. **Intervention**：在 policy、consent、recipient 與 channel 允許下要做什麼。

Risk 不直接呼叫工具；Attention 不等於 Risk；Intervention 必須由 deterministic Policy Gateway 核准。

## 2. Default Silent

每個事件都先進 `SILENT`。只有下列因素足夠時才考慮開口：

```text
intervention_score = value_of_information
                    × urgency
                    × confidence
                    × interruptibility
                    × consent
                    × channel_reliability
                    - recent_interaction_penalty
```

分數只是排序與解釋依據，不可取代硬性 policy。資訊價值低、信心低或不適合打擾時，保持安靜並留下 Unknown/待觀察。

## 3. 介入級別

| Level | 行動 | 條件 |
|---|---|---|
| L0 | 儲存／更新 World State | 任何合法 observation |
| L1 | Dashboard timeline / quiet reminder | local policy 核准 |
| L2 | resident check-in / speak | consent、可打擾、information value |
| L3 | 通知唯一責任照護者 | confirmed risk、recipient allowlist、payload minimization |
| L4 | 本版不存在 | 不自動撥打或通報緊急服務 |

## 4. 風險輸入

- 跨 frame visual evidence：transition、posture、near_floor、持續時間。
- Audio evidence：impact、alarm、cough、speech activity、environment sound；audio missing 不等於事件不存在。
- 時間、位置 confidence、sensor coverage、personal baseline。
- Resident response、人工確認、近期 intervention history。

## 5. Policy Gateway

Policy 是 deterministic，至少驗證：event status、confidence threshold、window、cooldown、consent、recipient、payload level、idempotency、config version 與目前 channel health。LLM 只能提出 `proposed_actions`，不能自行執行。

## 6. 分級揭露

| Payload | 內容 |
|---|---|
| L0 | sensor metadata、時間與 coverage |
| L1 | 存在／時間／一般活動，不含健康細節 |
| L2 | 單一 domain 提示，例如「訪視時留意進食」 |
| L3 | 經同意的完整趨勢與 evidence index |

Caregiver Agent 預設產生 L1/L2 aggregated summary；raw video/audio/transcript 只有明確事件 scope 才可查看。

## 7. Main Agent 的裁決邊界

目前 Main Agent 只產生可稽核 judgment，並由 deterministic policy 轉成 `silent`、`observe`、`ask`、`remind` 或 `dashboard_alert` proposal。判斷順序為：

1. observation 是否 valid、是否有 window/audio/frame evidence。
2. model confidence 是否達 `MAIN_AGENT_MIN_CONFIDENCE`。
3. 是否有既有 event 的跨窗口支持；candidate 不可直接升格。
4. attention score 是否被 unknown/uncertainty 降低。
5. fall recovery deadline、fire/smoke/alarm、distressed audio 是否觸發 critical override。
6. 沒有 warning/change-focus 或 distress signal 時，模型的單獨 `ask` 建議不會通過；通過後才允許下一階段的 interaction/notification adapter，目前 `action_executed=false`。

所有判斷保存 policy version、gates、score components 與 reasons，供 `/api/agent/runs` 及 Dashboard 回溯。

## 8. 目前待完成

目前已能由 Omni 建立 observation、Main Agent judgment、既有 event 與 exception candidate，並以 policy 產生 fail-closed proposal；尚未接入真正的 speak/notify execution、consent、interruption budget 與 acknowledgement。下一步是把 `fall/hydration/recognition_events` 接入完整 interaction/notification idempotency，並加入人工確認以降低 VLM 誤判造成的升級。
