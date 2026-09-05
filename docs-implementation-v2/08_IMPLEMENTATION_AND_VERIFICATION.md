# 08 · 實作順序、分工與驗證

> **v3 amendment：** P0 已改為 local Nemotron multimodal window、World State 與 Event Ledger；Gate 2b 的下一階段是 Context Sentinel/Active Inquiry、Policy/Intervention 與受限 audio interaction，Gate 3 才做完整 connector、重連與資料集穩定化。

## 1. 三個 Codex 的檔案邊界

### Track A：Backend 與 Data

- FastAPI app、設定、SQLite migrations／repositories。
- REST、WebSocket、replay source、Fake Health。
- browser media session、optional Frigate adapter、live source、後續 VAD／Whisper pipeline。
- Event state machine 與參數化 aggregation tools。
- 不修改 frontend component 實作與 model adapter internals。

### Track B：Frontend

- React/Vite、typed API client、WebSocket client、Dashboard panels。
- 使用共同 OpenAPI／event fixtures 開發。
- 不直接讀 SQLite、不持有 MiniMax key、不在瀏覽器推論 canonical event。

### Track C：AI Runtime

- Nemotron Omni vLLM runtime、2 FPS/5 秒窗口、frame/audio preprocessing、prompt 與 output validator。
- MiniMax adapter、capability probe、health/risk schema。
- 提供 stub adapter，讓 Track A/B 不等待模型下載。
- 不直接寫 UI 或繞過 repository 建立 event。

一名整合 owner 負責共用 schema、OpenAPI 及 merge；Track 不得私自修改已發布 contract。必要變更先更新 contract fixtures，再同步 consumer。

## 2. 實作順序

### Gate 0：已完成的現行 P0 基線

- 建立專案骨架、共同型別、sample payloads。
- HTTPS frontend 可取得 browser camera/microphone permission，並以 `/ws/media` 持續傳送 virtual camera stream。
- backend 以 2 FPS、5 秒、10 frames + audio 組成 bounded multimodal window。
- 本機 Nemotron Omni vLLM 回傳 typed observation；invalid/timeout 不得直接寫事件。
- fall/hydration 走既有 state machine；sound/person/object 走 exception `recognition_events` 與 recognition log。
- Dashboard 顯示 local VLM observation、audio events、事件與 compact logs。
- Main Agent 以同一 Nemotron Omni endpoint 讀取窗口與 typed context；analysis task 可並行，`VLLM_MAX_CONCURRENCY` 限制同時 request，`VLLM_MAX_PENDING_WINDOWS` 限制排隊。
- Main Agent 依 facts → temporal phase → existing-first mapping → uncertainty → attention score → deterministic policy 產生 `agent_runs`；低信心／失敗一律 `insufficient_data → silent`。
- Scene bootstrap、5 FPS/2 秒 description、2 FPS/10 秒 focus、60 秒 rolling media 與 time segment record 都納入 live E2E；Main Agent 的一般 request 不得包含原始影片。
- Gate test 必須涵蓋 person appeared、new memorable event、stable repeated event dedup，以及無 warning 時拒絕單獨 ask proposal。

### Gate 1：current vertical loop

```text
Browser MediaStream → Nemotron observation → event/recognition ledger → SQLite → WebSocket → Dashboard
Replay → deterministic/stub observation → 同一 downstream contract
Fake Health → aggregate →（後續）MiniMax privacy summary
```

Gate 1 未完成前，不加入更多事件或視覺美化。

### Gate 2：Context Sentinel 與互動

- World State 聚合 Known／Unknown／Hypothesis 與 coverage。
- Event Correlator 先用既有 event fields，再寫例外 recognition events。
- Active Inquiry、Resident Interaction Agent、Default Silent 與 interruption budget。
- 保存住戶回答與 memory provenance；保留 stub mode 作故障隔離。

### Gate 2b：語音、政策與照護者摘要

- Silero VAD → Whisper → transcript buffer，與 Omni audio observation 對齊。
- Event Understanding → Health Context → Risk → Policy → Intervention。
- Memory／State／Health／Speak／Notify／Frontend tools contract tests。
- Privacy Aggregator 只送 caregiver-safe aggregate 給 MiniMax；raw stream 不外送。
- Frigate RTSP/MQTT adapter 與 browser source 以同一 downstream contract 驗證。

### Gate 3：穩定化

- 重播正例／負例 dataset。
- 測 timeout、invalid JSON、重送、WebSocket 重連、reset。
- 固定 Demo 影片、模型 cache、啟動命令與簡報流程。
- 以測試時鐘執行 daily aggregation 與 Long-term Observer。

## 3. 驗證矩陣

| 測試 | 驗證 |
|---|---|
| Unit | schema validation、dedup、state transitions、window aggregation、policy rules |
| Repository | migration、transaction、indexes、時間窗邊界、重複寫入 |
| API | status code、錯誤格式、參數限制、job lifecycle |
| Realtime | commit 後廣播、重連 resync、run_id 隔離 |
| Model contract | valid、invalid、timeout、low confidence、missing frame |
| Replay E2E | 每支測試影片得到預期狀態序列，無重複 hydration count |
| Live media | HTTPS permission、WSS continuous binary stream、2 FPS/5 秒 window、斷線重連 |
| Audio | Omni audio window；後續再驗證 VAD segmentation、Whisper transcript、TTL cleanup |
| Main Agent | judgment schema、parallel semaphore、pending backpressure、policy gates、score components、fail-closed |
| Agent tools | schema、權限、idempotency、Policy Gateway 不可繞過 |
| Observer | daily summary、時間窗邊界、無新資料時不重複呼叫 MiniMax |
| Frontend | 1366×768、loading／empty／degraded／error 狀態、reset |
| Secret | frontend build、Git diff、logs、SQLite 均無 API key |

## 4. 舞台 Runbook

1. 確認本機 Nemotron vLLM `/v1/models` 與 multimodal smoke test。
2. 啟動 HTTPS backend/frontend，確認 DB、WSS 與 local VLM status。
3. 啟動 frontend，全螢幕開 Dashboard。
4. 執行 demo reset。
5. 開啟 camera + microphone，展示 continuous stream → 10-frame/audio window → observation。
6. 以測試影像展示 fall/hydration；以聲音、人物、物件展示 exception recognition log。
7. 確認 event timeline、VLM panel 與 recognition log 都能由 DB/WS 回溯。
8. 若啟用 MiniMax，再展示 privacy aggregate；不得把 raw stream 當預設 input。
9. 準備 stub/replay 作最後 fallback，但主展示使用現場 Nemotron 推論。

## 5. 切線規則

- Nemotron vLLM 未 ready：顯示 degraded 並切換 stub/replay；不得在 UI 假稱模型已推論。
- Frigate 未接好：current browser VLM P0 仍可驗收；Frigate adapter gate 延後，不得阻塞主路徑。
- 喝水量視覺估算不穩：保留 confirmed count，容量採設定值。
- MiniMax video input 不穩：只送文字摘要／必要影格。
- UI 時間不足：保留 video、health、hydration、analysis、timeline 五個核心區塊。
- P0 尚未完整 E2E：停止 P1/P2。
