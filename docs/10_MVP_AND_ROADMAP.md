# 10 · MVP 與 Roadmap

## 1. 新核心 Demo

展示「一天的有限感知」而非全天監控：

1. Camera/mic stream 建立局部 observation。
2. 系統展示 Known、Unknown、Hypothesis 與 confidence。
3. 冰箱／門／人物／家庭聲音事件被 correlation 成 situation。
4. 若物品辨識不確定，Sentinel 產生 information gap。
5. Policy 決定 silent 或在合適時機詢問。
6. 居民回答寫入 resident-confirmed memory。
7. 未來時間提醒與 Caregiver privacy summary 由同一 Event Ledger 產生。

## 2. 目前已完成

- HTTPS React dashboard、camera/mic continuous MediaStream。
- 2 FPS、5 秒、10-frame + audio multimodal window。
- Nemotron Omni vLLM image/audio structured request。
- `fall`、`hydration` existing state machine。
- sound/person/object exception `recognition_events`、confidence、cooldown、dedup。
- SQLite evidence/model/log/stream/memory 基礎資料模型。
- WSS live observation、generic event timeline、recognition logs。
- Parallel Main Agent：Omni detailed judgment、policy gates、attention score、Unknown/Hypothesis、agent run audit 與 dashboard panel。
- Fake Health、MiniMax degraded summary、Observer 基礎流程。

## 3. Phase 1：Context Sentinel（Main Agent 之後）

- 建立 World State compiler：Known/Unknown/Hypothesis/last observed location。
- Event Correlation：fridge_open + person_near + fridge_closed → situation。
- information-gap、value-of-information、suitable-interaction schema。
- 不確定性與 coverage 在 dashboard 可視化。

## 4. Phase 2：Resident Interaction

- Default Silent 狀態機。
- consent、interruptibility、recent interaction、resident preference、interruption budget。
- `ASK` → browser/TTS → VAD/Whisper → resident-confirmed memory。
- transcript window/TTL 與第三方隱私測試。

## 5. Phase 3：Caregiver Agent

- Privacy Aggregator：日／週活動、飲食、如廁、聲音與 coverage 摘要。
- semantic/scheduled memory 與提醒。
- personal baseline、finding、acknowledge/dismiss。
- caregiver dashboard 預設不顯示 camera/raw audio。

## 6. Phase 4：穩定化與可選 adapters

- Policy/Intervention action、notification idempotency、人工確認。
- real Frigate/RTSP/MQTT、IoT door/fridge/pill sensors、wearable health。
- positive/negative evaluation set、timeout/invalid/reconnect/reset/queue 壓力測試。
- 只有通過安全與場域審核才評估更高級別通知；本版不做 L4。

## 7. Definition of Done

- 每個 observation/event 都有來源、窗口、confidence、uncertainty、版本與可回查證據。
- 同一事件重送不重複計數或介入。
- Unknown 不被轉成 no-event。
- VLM unavailable 時 local state、dashboard、history 仍可用。
- Demo 可展示 silent、ask、remember、remind 與 caregiver aggregate 五種結果。
