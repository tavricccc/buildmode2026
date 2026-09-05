# Ambient Care Agent OS 規格書

版本：v0.2 · 2026-09-04
定位：**在有限感知下建立生活脈絡，而不是全天候監控老人。**

## 0. 範圍宣告

系統從稀疏的 camera、microphone、IoT、手機與 wearable 輸入 typed events，建立住戶的局部 World State。它必須能表達 Known、Unknown、Hypothesis、confidence、coverage 與下一步，並在 policy 允許時詢問、提醒、通知或保持安靜。

### 做什麼

- Browser camera/microphone continuous MediaStream 作為目前可執行 sensor。
- 本機 Nemotron Omni vLLM 做多模態觀察：2 FPS、5 秒、10 張有序 frames + 5 秒 16 kHz mono audio。
- 既有 `fall`、`hydration` 事件優先沿用；其他家庭聲音、人物活動、非人物物件成為有證據的 exception recognition event。
- Event Ledger、World State、Semantic Memory、Scheduled Memory、Active Inquiry、Privacy Aggregation 與 personal baseline。

### 不做什麼

- 不做診斷、治療、疾病預測或自動評定 IADL。
- 不把攝影機當成產品本身；camera 是可替換 sensor。
- 不在未知時硬猜目前位置或事件，不以「沒有資料」當成「沒有發生」。
- 不在未經同意的情況下做 24/7 逐字 ASR；不把第三方對話當成可永久保存資料。
- 不自動聯絡社工、政府或緊急服務；L4 executor 不存在於本版。

## 1. 設計原則

1. **Partial observability**：感知永遠是不完整的，`UNKNOWN` 是一等輸出。
2. **Existing-first**：`fall`、`hydration` 的既有欄位與 state machine 優先；只有無法表達的 sound/person/object/scene 才建立例外事件。
3. **Event before Agent**：先做 deterministic normalize、correlation、cooldown、quality，再決定是否呼叫模型。
4. **Default Silent**：不值得知道、不適合打擾或信心不足時，保持安靜並保留 uncertainty。
5. **Evidence before interpretation**：Observation、Interpretation、Risk、Hypothesis、Fact 分層保存，不能互相升格。
6. **Privacy by abstraction**：照護者預設讀摘要與趨勢，不讀完整生活 raw stream。

## 2. 系統架構

```text
Camera / Mic / IoT / Phone / Wearable
                ↓
Source adapters → Event Bus → Normalizer → Correlator
                                      ↓
                         World State: Known / Unknown / Hypothesis
                                      ↓
               Context Sentinel → Attention & Intervention Policy
                    ↓                         ↓
       Active Inquiry / Memory          Silent / Ask / Remind / Warn
                    ↓                         ↓
             Resident Interaction       Caregiver Aggregation
                                      ↓
                           Dashboard / Care Log
```

目前 runtime：Browser HTTPS MediaStream → backend WSS → in-memory sampler → local Nemotron vLLM → SQLite → WSS Dashboard。Frigate/RTSP/MQTT 仍是 optional source adapters。

## 3. Sensor 與輸入契約

每個 sensor adapter 只負責取得資料、保留必要 timestamp、建立 source quality，輸出：

```json
{
  "source_event_id": "src_...",
  "source": "browser_camera|microphone|frigate|iot|health",
  "subject_id": "resident_demo",
  "occurred_at": "2026-09-04T17:32:00+08:00",
  "privacy_scope": "local_processing",
  "observability": "observed_normal|observed_abnormal|unobservable",
  "payload": {},
  "provenance": {}
}
```

缺 source、缺時間、斷線或權限不足必須產生 coverage/data-quality 訊號，不可靜默丟棄。

## 4. World State

World State 不是模型記憶中的自然語言，而是可重建的 typed snapshot：

```json
{
  "known": [{"key": "last_observed_zone", "value": "kitchen", "confidence": 0.84}],
  "unknown": [{"key": "current_zone", "reason": "resident left camera view"}],
  "hypotheses": [{"statement": "resident may have stored groceries", "confidence": 0.31, "expires_at": "..."}],
  "attention": {"value_of_information": 0.5, "urgency": "low", "interruptible": true},
  "next_action": "silent",
  "snapshot_version": "world.v1"
}
```

`last_observed_zone` 不等於 `current_zone`。每個 hypothesis 必須有 supporting refs、confidence、expiry/review condition。

## 5. Event Ledger 契約

既有 canonical event 使用以下欄位，新增資訊盡量放入 `attributes`，不複製另一套事件信封：

```json
{
  "event_id": "evt_...",
  "subject_id": "resident_demo",
  "event_type": "fall|hydration",
  "status": "candidate|confirmed|recovering|resolved|dismissed|invalid",
  "occurred_at": "2026-09-04T17:32:00+08:00",
  "ended_at": null,
  "confidence": 0.78,
  "evidence_ids": ["evd_..."],
  "attributes": {"window": {}, "audio": {}, "uncertainty": []},
  "model_call_id": "call_...",
  "dedup_key": "sha256:...",
  "schema_version": "event.v1",
  "config_version": "config.v1"
}
```

例外事件使用相同語意的 `recognition_events`：`id`、`subject_id`、`event_type`、`domain`、`label`、`status`、`occurred_at`、`confidence`、`attributes`、`window_id`、`model_call_id`、`dedup_key`。它不能取代 `fall`／`hydration` 的計數與確認流程。

## 6. Event taxonomy

### Existing-first events

- `fall`：跨 frame down/near_floor/lying evidence，由 fall state machine 確認。
- `hydration`：container near mouth + drinking motion，由 hydration session state machine 確認與計數。

### Sound exceptions

`doorbell`、`door_knock`、`door_open`、`door_closed`、`fridge_open`、`fridge_closed`、`water_running`、`toilet_flush`、`washing_machine`、`microwave`、`rice_cooker`、`range_hood`、`dishes`、`impact_sound`、`cough`、`tv_audio`、`speech_activity`、`alarm_sound`。

### Person exceptions

`person_present`、`person_walking`、`person_sitting`、`person_lying`、`person_entered`、`person_left`、`person_inactive`。

### Non-person visual exceptions

`object_cup`、`object_bottle`、`object_phone`、`object_remote`、`object_bag`、`object_pet`、`object_vehicle`、`smoke`、`fire`。

例外候選必須包含 `domain`、`label`、`state`、`confidence`、`evidence_frame_indexes`、`attributes` 與 `uncertainty_reasons`；低於 0.55 只保留為 uncertainty。

## 7. Multimodal VLM 契約

每個窗口：

- 2 FPS。
- 5 秒、10 張按時間排序的 frames。
- 同窗口 5 秒、16 kHz、mono audio。
- vLLM served model：`nemotron_omni`。
- `chat_template_kwargs.enable_thinking=false`，response 使用 strict JSON schema。
- 音訊使用短暫 `file:///mnt/d/...` WAV URI；request 結束立即刪除。

```json
{
  "observed_at_offset_ms": 5000,
  "person_visible": true,
  "posture": "standing|sitting|lying|unknown",
  "vertical_transition": "up|down|none|unknown",
  "near_floor": false,
  "drink_container": "cup|bottle|other|none|unknown",
  "container_near_mouth": false,
  "drinking_motion": false,
  "confidence": 0.82,
  "supporting_frame_indexes": [0, 4, 9],
  "uncertainty_reasons": [],
  "audio_present": true,
  "audio_events": ["door_knock"],
  "speaker_emotion": "neutral",
  "audio_confidence": 0.72,
  "audio_uncertainty_reasons": [],
  "speech_detected": true,
  "speech_transcript": "我有點不舒服",
  "transcript_confidence": 0.82,
  "transcript_uncertainty_reasons": [],
  "change_detected": false,
  "change_confidence": 0.0,
  "change_reasons": [],
  "warning_signal": "none",
  "event_candidates": []
}
```

若 audio track 存在，`audio_present=true` 代表已提供音訊；`audio_events=[]` 代表目前沒有可靠聲音事件，不代表音訊不存在。只有 `speech_detected=true` 且 transcript 非空時，才將 `speech_transcript` 寫入有 TTL 的 `transcripts`；Omni 聽不清楚時必須留空並寫 uncertainty，不可猜字。

Main Agent 接著讀取同一窗口的 10 frames、audio、typed Observation、既有事件與最近事件摘要，固定產生：`observed_facts`、`temporal_assessment`、`situation_phase`、`event_assessments`、`hypotheses`、`unknowns`、`uncertainty_reasons`、`risk_level`、`attention_level`、`proposed_action` 與 `next_action`。Omni 可以並行處理不同窗口，但由 `VLLM_MAX_CONCURRENCY` 與 pending limit 控制。模型不得輸出 hidden chain-of-thought，也不得直接執行 action。

程式端 `MainAgentPolicy` 以 `15 × model_confidence + 10 × visual_confidence + 75 × event_signal − uncertainty_penalty` 計算可重現的 attention score，其中 `event_signal = event_confidence × event_type_weight`；例行 person／家電事件權重低，fall／impact／alarm／fire 權重高。正常 observation 不會因高信心而自動變成值得注意，再套 evidence、confidence、existing-first 與 critical override gates。低信心／無有效 evidence 一律 `insufficient_data → silent`；critical fall recovery、fire/smoke/alarm 或 distressed audio 才能升級 proposal。結果寫入 `agent_runs`，並保存 `action_executed=false`。

## 8. Event correlation 與狀態機

```text
fridge_open → person_near_fridge → bag_detected → fridge_closed
                              ↓
                   possible_grocery_storage
```

不要為每個 motion/person/VAD transition 呼叫 detail LLM。第一層 observation 的 change gate 同時檢查模型 change 訊號、person 出現／離開、新 memorable event、既有 event 狀態與 warning；只有 gate 通過才觸發 5 FPS description。Main Agent 先讀 description，只有 needs_further_attention 才啟動 2 FPS × 10 秒 focus。沒有 warning/change-focus 或 distress signal 時，單獨 ask 建議保持 silent/observe。依 attention value/urgency 決定 local-only、VLM、詢問或 silent。

Fall 不可由單張 `lying` 確認；Hydration 只有完成 session 才計數。所有 state transition 在 transaction 內完成，commit 後才 broadcast。

## 9. Active Inquiry

```text
Event → Observation → Hypothesis → information gap → value/urgency
  → suitable interaction? → Ask resident → resident-confirmed memory
```

問題要短、可回答、非侵入；若資訊價值低或長者不可打擾，維持 `SILENT`。居民回答是新的 provenance，不可覆寫原始 VLM observation。

## 10. Agent 與 Policy

Context Sentinel、Resident Interaction、Caregiver Agent 共用 local vLLM，但有獨立 prompt、context、tools 與權限。現行先實作 Main Agent vertical slice：每個 multimodal window 以 bounded parallel task 交給 Nemotron Omni，輸出可稽核 judgment；Risk 與 Intervention 分離，LLM 只能提出 proposed action。

Policy Gateway deterministic 驗證 confidence、coverage、consent、interruptibility、cooldown、recipient、payload level、idempotency 與 config version。L3 可通知唯一責任照護者；L4 不存在於本版。

## 11. Memory、Privacy 與 caregiver

- Event Ledger：可回溯事件與 evidence。
- Semantic Memory：住戶偏好、已確認食品、生活習慣。
- Scheduled Memory：未來檢查、提醒、詢問。
- Privacy Aggregator：把 raw visits/events 轉為日／週摘要。
- Caregiver 預設看到 Level 1/2 aggregate；raw Level 3 需明確事件 scope 與權限。

影像／音訊 local-first；transcript 只有 conversation window，TTL 到期移除。禁止浴室／臥室 camera，禁止未經 Gate 的 media 外傳。

## 12. Health 與長期觀察

Fake Health 只作 demo；真實 health connector 必須保存 source、measured_at、quality、stale 與 coverage。Long-term Observer 以該住戶自身 7/30 日與 12 週 baseline 比較，資料不足時輸出 provisional/insufficient_data，不當成零事件。

Caregiver summary 必須含時間窗、個人基線、變化幅度、支持日期與建議人工後續，不輸出疾病名稱或自動量表分數。

## 13. API 與即時性

- `GET /api/status`：每個元件獨立回報 healthy/degraded/unavailable/disabled。
- `WS /ws/media`：continuous camera + audio ingress。
- `WS /ws`：typed observation/event/action/log updates。
- `GET /api/events`：canonical + recognition events，支援 type/status/time pagination。
- `GET /api/recognition/logs`：VLM/Frigate compact recognition feed。
- `GET /api/agent/runs`：Main Agent judgment、policy gates、score、latency 與 fail-closed 結果。
- `GET /api/agent/events`：每一輪 Main Agent 的 started/context/judgment/policy/memory/action/completed trace。
- `GET /api/agent/notes`：依 decision、abstraction、research layer 查詢未過期注意事項。
- `GET /api/media/scene-contexts`、`/api/media/descriptions`、`/api/media/focus-reviews`、`/api/media/time-segments`：查詢 scene footnote、影像描述、深入檢查與時間段分類。
- `GET /api/events/{id}`：evidence、window、model call、attributes、action。

WSS message 在 DB commit 後發出；斷線或 sequence gap 時前端 REST resync。前端不能成為 canonical state。

## 14. 目前實作與 Roadmap

### 已完成

- HTTPS browser MediaStream、2 FPS/5 秒/10 frame sampling。
- Nemotron image + audio structured request。
- Existing fall/hydration state machine。
- Sound/person/object exception candidates 與 cooldown/dedup。
- SQLite evidence、model call、recognition event、stream metadata。
- Generic event timeline、VLM live observation、recognition logs。
- Parallel Main Agent：同一 Omni endpoint、typed judgment、deterministic attention policy、`agent_runs` audit 與 dashboard panel。
- Scene bootstrap、change/warning gate、5 FPS visual descriptions、2 FPS/10 秒 focus review、60 秒 rolling media 與無警告 time segments。

### 下一階段

1. Context Sentinel World State compiler 與 Main Agent judgment 的情境聚合。
2. Active Inquiry 與 Default Silent/Interruption Budget。
3. Main Agent proposal → Policy → dashboard alert/action execution。
4. Silero VAD、受限 Whisper conversation window。
5. Semantic/Scheduled Memory 與 resident-confirmed flows。
6. Privacy Aggregator、Caregiver Agent 與 personal baseline。
7. timeout、invalid JSON、reconnect、正負例與 full E2E。

## 15. Definition of Done

1. Unknown 不被轉成 normal/no-event。
2. 事件能回查來源、窗口、model、prompt、config、confidence 與 evidence。
3. VLM 重送不重複建立事件或介入。
4. VLM/audio unavailable 時主狀態與 Dashboard 仍可運作並顯示 degraded。
5. Default Silent、Ask、Remember、Remind、Caregiver Summary 都有可重現測試。
6. 所有 raw media、transcript、caregiver share 與通知都受 consent、scope、TTL 與 audit 控制。
