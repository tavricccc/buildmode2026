# 01 · 系統架構

## 1. 架構總覽

```text
Sparse Sensors
  ├─ browser camera + microphone
  ├─ optional Frigate / RTSP / MQTT
  ├─ optional IoT door/fridge/pill sensors
  └─ optional phone/wearable health
          ↓
Source Adapters → Event Bus / Normalizer → Event Correlation
                                      ↓
                              World State Compiler
                         ┌────────────┴────────────┐
                  Known / Unknown / Hypothesis   Event Ledger
                         ↓              ↓             ↓
              Context Sentinel     Attention Policy  Memory
                         ↓              ↓             ↓
               Active Inquiry   Silent / Ask / Remind / Warn
                         ↓                            ↓
                 Resident Interaction                 Caregiver Agent
                         ↓                            ↓
                 consented Memory             Privacy Aggregator

```

Current Main Agent：每個 multimodal window 由同一 Nemotron Omni 以 bounded parallel task 產生 judgment；Policy Gateway 再裁決 final action proposal。

Camera is one sensor, not the product. Sensor differences end at the adapter boundary；下游只接 `EventCandidate`、`EvidenceReference`、`Observation` 與品質欄位。

## 2. 元件責任

| 元件 | 責任 | 不負責 |
|---|---|---|
| Sensor adapter | 收集資料、重連、轉成 typed input | 語意判斷、通知 |
| Event Normalizer | 統一 id、時間、source、privacy scope | 補猜缺失資料 |
| Event Correlator | 將多個 raw event 合併為 situation/window | 呼叫外部行動 |
| World State | 編譯 Known、Unknown、Hypothesis、location confidence | 宣告醫療事實 |
| Context Sentinel | 評估資訊缺口、attention value、下一步候選 | 直接傳 raw data 給照護者 |
| Interaction Agent | 依 policy 產生 Ask/Remind/Chat | 自行發通知、修改門檻 |
| Caregiver Agent | 讀 aggregated context 與 findings，產生照護摘要 | 取得未授權 raw evidence |
| Policy Gateway | deterministic 地核准 action、recipient、payload level | 使用 LLM 自由文字當規則 |
| Event Ledger | 保存事件、證據、模型、版本與 action trace | 取代 policy |

## 3. 目前 local runtime

Browser 的 continuous WebM stream 進入 backend；ffmpeg 在記憶體中以 2 FPS 產生 frame，並取同一 5 秒的 16 kHz mono audio。Nemotron Omni 以 OpenAI-compatible API 接收 10 張 image + 一個 audio URI，輸出 typed multimodal Observation。原始 frame/audio 不進 SQLite，只有短暫的受控工作檔與 metadata。

Frigate adapter 可在未來接回 RTSP/MQTT。若 Frigate 不可用，local VLM、Event Ledger 與 Dashboard 不應停止。

## 4. 邊界與一致性

- SQLite 是 canonical state，WebSocket 只是提交後的即時通知。
- 事件先 commit，再 broadcast；斷線後前端用 REST resync。
- Model output 只能建立 Observation/candidate；既有 `fall`、`hydration` 由既有 state machine 確認。
- 所有 Agent 使用 allowlisted tools；raw evidence、health、memory 與 notification scope 分離。
- 所有時間使用含時區 ISO 8601；窗口另存 start/end offset。

## 5. 資源基線

- Omni request 使用 `VLLM_MAX_CONCURRENCY` bounded semaphore，預設 2 個 request 可並行；observation 與 Main Agent 共用此上限。
- 2 FPS、5 秒、10 frames；窗口 stride 預設 5 秒，可明確調成 sliding stride。
- vLLM 目前 served model `nemotron_omni`，不使用 CPU offload；執行參數與實測結果以 runtime report 為準。
- 不用 LLM 處理每個 sensor event；先 correlation，再對 ambiguous/important situation 升級。
