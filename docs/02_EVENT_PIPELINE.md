# 02 · 即時事件 Pipeline

## 1. 目標

把「可能值得注意」的 trigger 轉成可追溯、可重跑、可安全升級的 Multimodal Event Bundle。每個事件只處理必要的時間窗與脈絡，不把所有連續影音直接送到強模型。

~~舊主流程是「候選事件 → 三支模態 → Event Understanding → Risk → Intervention」。~~ 新 Demo 主流程在事件落檔後先進入 Context / World State Agent；只有資料不足且值得確認時，才建立 Resident Interaction 工作，之後再把經確認的內容寫入 Memory，並由 Privacy Filter 產生 Caregiver projection。

## 2. 事件生命週期

| 步驟 | 元件 | 輸入 | 輸出／責任 |
|---|---|---|---|
| 1 | Frigate NVR | 影像、音訊、裝置事件 | 建立候選時間窗與證據索引 |
| 2 | Event Gateway | 外部 payload | 建立 ID、正規化時間、去重、寫入 Sensor Event |
| 3 | Model Router | 候選摘要、watchlist 命中 | 選擇 T0–T3 與 deadline |
| 4 | ASR／VLM／Audio | 事件時間窗 | 各模態 Observation、Transcript、品質訊號 |
| 5 | Multimodal Assembler | 三支模態輸出 | 對齊並產生 Event Bundle，顯示缺失與衝突 |
| 6 | Event Understanding Agent | Event Bundle、最小照護脈絡 | Observation、Interpretation、證據引用 |
| 7 | Risk Agent | Interpretation、歷史風險因子 | Risk Assessment、uncertainty、reason codes |
| 8 | Policy Gateway | Risk Assessment、授權與規則 | 允許的 intervention level、cooldown、gate result |
| 9 | Intervention Agent | Policy decision | 執行通知／確認／求助，回寫完整狀態 |

## 3. 分流與匯合

事件啟動後至少分成三支：

- ASR／人聲理解：語音轉錄、語言／說話者線索、求助語句候選；不把轉錄直接視為事實。
- Video VLM：姿勢、位置、物件、活動、事件前後狀態；保留 frame/clip references。
- Audio Event Classification：impact、scream、yell、alarm、cough 等音效候選；保留時間片段與模型版本。

三支輸出由 Multimodal Assembler 對齊 `event_id`、時間窗、空間與 subject，再產生 Bundle。每個模態可以缺失，但缺失必須顯式標註，不能用空值冒充「沒有發生」。

## 4. Bundle 最小內容

```yaml
event_id: evt_20260904_000123
subject_id: resident_001
occurred_at: 2026-09-04T22:14:03+08:00
window: {start: 2026-09-04T22:13:48+08:00, end: 2026-09-04T22:14:33+08:00}
trigger:
  source: frigate
  labels: [person, audio_impact]
evidence:
  - kind: video_clip
    ref: object://evidence/evt_20260904_000123.mp4
    sha256: <digest>
  - kind: audio_clip
    ref: object://evidence/evt_20260904_000123.wav
modal_observations:
  asr: {status: available, confidence: 0.71, refs: [obs_asr_01]}
  video: {status: available, confidence: 0.64, refs: [obs_video_01]}
  audio: {status: available, confidence: 0.88, refs: [obs_audio_01]}
context:
  watchlist_ids: [watch_009]
  snapshot_id: ctx_20260904_17
quality:
  clock_sync_ms: 42
  missing_modalities: []
  conflict_flags: [video_audio_uncertain]
```

## 5. 去重、超時與升級

1. 以 subject、source、時間窗與事件類型建立 dedup key；重複 trigger 只增加 evidence，不重複發起介入。
2. Router 先給每個工作 deadline；ASR、VLM、音效分類可平行執行，Assembler 在 deadline 到達時產出「已完成／缺失／衝突」狀態。
3. 若本地輸出低信心、模態互相矛盾、命中高優先 watchlist 或出現高風險組合，升級 T2/T3。
4. 強模型只收到完整事件證據與最小必要照護摘要；不直接收到全部健康資料。
5. 若升級失敗，Risk 必須使用保守路徑，通常是 L1/L2 或人工確認，而不是生成確定的低風險結論。

## 5.1 World State 與主動詢問

每個事件完成後，World State 至少要更新：目前可能位置、活動／session、感測器健康、`known[]`、`unknown[]`、`observability` 與 evidence refs。當 `unknown` 對照護目的有價值且打擾程度可接受時，產生 `question_candidate`；Policy Gateway 再決定是否由 Resident Agent 發出一次性詢問。

長輩回答只在 conversation window 中處理。回答若未明確確認，不得直接寫入 Fact；可先寫成待確認的 interaction record。

## 5.2 照護者投影

Caregiver Agent 不讀取原始 transcript 或不必要的影音。它接收事件類型、聚合指標、observability／coverage、長輩確認的 Fact 與 evidence refs，輸出日誌、趨勢、資料不足提示與下一步建議。

## 6. 高風險 Fast Path 示例

以下是系統測試示例，不是醫療規範：

| 觀察組合 | 路由 | 後續 |
|---|---|---|
| 單獨 speech | T0/T1 | 留存最小索引或本地轉錄 |
| person walking | T0/T1 | 記錄或輕量追蹤 |
| impact + floor posture | T2，低信心時 T3 | 進入確認流程 |
| scream/yell + rapid downward motion | T2/T3 | 優先融合，縮短 deadline |
| 求助語句 + floor posture + 未恢復 | T3 | Policy Gateway 評估 L2/L3/L4 條件 |

## 7. 失敗與資料品質處理

| 情況 | 必須記錄 | 預設處理 |
|---|---|---|
| clip 不存在或 hash 不符 | evidence status、錯誤碼 | 不送強模型；進人工或 L1 |
| ASR 語言／轉錄不穩定 | language、confidence、segments | 標為不確定，不當作語意事實 |
| 模態時間不同步 | clock offset、同步方法 | 擴大窗口或降級為 Observation |
| 模型 timeout | job status、deadline、route | 重試一次後走保守 fallback |
| Event Bus 重送 | delivery id、dedup key | 追加 evidence，不重複介入 |

## 8. 驗收條件

- 任一介入都能由 `intervention_id → risk_id → interpretation_id → observation_id → evidence_ref` 反查。
- 同一 `event_id` 重送不產生重複通知。
- 任一模態缺失或時間不同步都會在 Bundle 與 Audit 中可見。
- Router 可在本地快速結果出現後中止不必要的強模型工作，或在高風險訊號出現時立即升級。
- 所有輸出符合版本化 schema，無法驗證的模型輸出不得進入 Risk 或 Intervention。

下一步的 Agent 職責見 [03_AGENT_ARCHITECTURE.md](03_AGENT_ARCHITECTURE.md)，資料欄位定義見 [04_MEMORY_AND_DATA_MODEL.md](04_MEMORY_AND_DATA_MODEL.md)。
