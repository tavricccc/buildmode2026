# 00 · 產品範圍與完成定義

> **v3 amendment：** 本文件現在以 Ambient Care 為產品核心。Frigate 是 optional adapter；current P0 是 browser continuous MediaStream → local Nemotron Omni vLLM → World State/Event Ledger。產品目標是知道、承認不知道、評估是否值得問，而不是持續監視住戶。

## 1. Demo 要證明什麼

目前可運作的 P0 是瀏覽器以 `getUserMedia` 取得攝影機與麥克風，透過 HTTPS/WSS 持續送入 backend；backend 以 2 FPS、5 秒窗口（10 張 frame + 5 秒音訊）呼叫本機 Nemotron Omni vLLM，將結構化 observation、既有事件與例外 recognition log 寫入 SQLite 並推送 Dashboard。Frigate、RTSP、Silero VAD、Whisper 與 MiniMax 是後續整合或分析邊界，不是目前 VLM 主路徑的必要前置。

核心展示鏈：

```text
Browser MediaStream（camera + microphone）
               ↓ HTTPS/WSS
      backend window sampler
      2 FPS × 5 秒 = 10 frames + audio
               ↓
      Nemotron Omni vLLM
      → typed observation
      → fall / hydration existing event contract
      → sound / person / object exception recognition_events
      → SQLite Event Ledger + recognition log
      → WebSocket Dashboard
      →（後續）World State / Active Inquiry / Policy / Caregiver summary

Frigate RTSP/MQTT、Replay 與 Whisper 可作為 source／audio adapter，並不取代上述 current path。
```

## 2. 完整程式必做

- 單一使用者、單一場域；不做多租戶。
- Browser camera + microphone 可在 HTTPS 頁面取得權限並持續串流至 backend。
- Nemotron Omni vLLM adapter 產生版本化 JSON，不讓自由文字直接進事件狀態機。
- 目前以每秒 2 張、每 5 秒 10 張 frame，同窗口附帶 16 kHz mono audio 完成一次 multimodal observation。
- 跌倒與喝水優先沿用既有 event contract；家庭聲音、人物與非人物物件使用 exception recognition event。
- recognition log 保存值得注意判定與 compact provenance，不保存 raw stream。
- Replay source 供測試與舞台備援；未來 adapter 必須使用相同 downstream contract。
- Frigate 可選擇性接入 RTSP/MQTT；不列為 current P0 的完成前置。
- 語音目前由 Omni 直接取得窗口級 audio signals；Silero VAD、Whisper transcript 與住戶對話仍是後續工作。
- 跌倒事件：候選、持續、恢復、確認與警報狀態。
- 喝水事件：候選、確認、session 去重、次數與估算飲水量。
- Fake Health：心率、血氧、活動狀態、步數、量測時間與資料品質。
- SQLite 保存事件、證據、健康樣本、模型呼叫、分析、動作及應用程式 logs。
- Dashboard 即時呈現 browser stream、local VLM window、音訊事件、既有事件、recognition logs、健康與服務狀態；Frigate／ASR／MiniMax 未啟用時要明確顯示 disabled 或 degraded。
- MiniMax 可依指定時間窗分析健康資料與跌倒／喝水聚合。
- MiniMax 不可用時，事件偵測、SQLite 與 Dashboard 仍可運作。
- Agent Orchestrator 的 logical agent contract、World State 與 Policy 邊界完成；Context Sentinel、Resident Interaction、Caregiver Aggregation 的完整執行列為下一階段。
- Memory、State、Health、Speak、Notify、Frontend tools 具可呼叫、可驗證、可稽核的實作。
- L3 Notify Tool 使用 Telegram Bot（若啟用），保存 delivery、acknowledged、false_alarm 與 failed 狀態。
- Long-term Observer 可依排程彙總日／週事件，保存 baseline 與 finding。

## 3. 可在完整架構後擴充

- 第二支 camera 與多場域。
- 真實穿戴裝置 adapter。
- Telegram 以外的通知 channel。
- 更多視覺／聲音事件。
- 人工確認／修正事件，以及利用修正結果建立 replay evaluation set。

## 4. 本次不做

- 真實 HealthKit、FHIR 或醫療院所整合。
- 水聲辨識；喝水以視覺為準。
- 自動撥打緊急服務（L4）。
- 多租戶、完整 RBAC、不可竄改 audit store。
- 長期診斷、疾病預測或自動醫療判斷。
- 多台獨立 Agent service；Agent 先以同一 backend 內的邏輯單元實作。

## 5. Definition of Done

1. 一鍵 reset 後可連續完成兩次相同 Demo，不受前次 runtime state 污染。
2. HTTPS browser stream 可連續運作；每個 5 秒窗口包含 10 張取樣 frame 與 audio，能完成一次 Nemotron observation。RTSP/Frigate／Replay adapter 另以相同 downstream contract 驗證。
3. 跌倒與喝水各至少有一段正例影片及一段容易混淆的負例影片。
4. 每筆確認事件都能由 SQLite 反查模型結果、證據時間窗與 model/prompt version。
5. 喝水 count 由 SQL 聚合 confirmed session；重新播放或重送不重複計數。
6. 前端在 backend 寫入事件後 2 秒內收到更新；模型推論時間獨立顯示。
7. MiniMax 分析只接收健康快照與 SQL 聚合摘要；除非明確要求，不傳完整影片。
8. MiniMax timeout 或 schema invalid 時顯示 degraded，不能卡住主事件管線。
9. API key 不出現在 frontend bundle、SQLite logs、console output 或 Git tracked files。
10. Current audio gate：browser mic → 5 秒 audio window → Nemotron audio observation 可用實際聲音完成一次 E2E；VAD → Whisper → transcript buffer 為 deferred gate。
11. Memory／State／Health／Speak／Notify／Frontend tools 各有 contract test。
12. Long-term Observer 能以測試時鐘產生一次 daily summary 與 finding。
13. 所有驗證命令、部署步驟及舞台操作可由新環境照文件重現。
14. Telegram 測試 chat 可收到 L3 event，按下 acknowledgement 後 SQLite 與 Dashboard 同步更新。
