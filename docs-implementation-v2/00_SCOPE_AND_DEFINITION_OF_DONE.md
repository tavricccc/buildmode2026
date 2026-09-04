# 00 · 產品範圍與完成定義

## 1. Demo 要證明什麼

系統能從手機 RTSP live stream 與麥克風持續取得資料，由 Frigate、Silero VAD、Whisper 與本地 Qwen-VL 建立多模態事件，把結果存入 SQLite、即時更新 Web Dashboard，並讓 MiniMax 使用健康快照與事件聚合摘要產生可追溯的健康／風險分析。Replay 是相同 source contract 的測試 adapter，不是完整交付的替代品。

核心展示鏈：

```text
手機 RTSP → Frigate → event clip / snapshot
麥克風 → Silero VAD → Whisper transcript segment
               ↓
      本地抽幀與 Qwen-VL
  → 跌倒／喝水事件狀態機
  → SQLite
  → WebSocket
  → Dashboard
  → MiniMax-M3 讀取健康快照與事件統計
  → 分析結果／建議／警報狀態回寫 SQLite 與 Dashboard
```

## 2. 完整程式必做

- 單一使用者、單一場域；不做多租戶。
- 手機 RTSP live stream 可實際接入 Frigate。
- Frigate 可持續 ingest、保留短事件媒體並將事件送入 backend。
- Replay source 供測試與舞台備援，使用相同 downstream contract。
- 麥克風持續送入 Silero VAD；speech segment 送 Whisper 並寫入短期 transcript buffer。
- Qwen-VL adapter 產生版本化 JSON，不讓自由文字直接進事件狀態機。
- 跌倒事件：候選、持續、恢復、確認與警報狀態。
- 喝水事件：候選、確認、session 去重、次數與估算飲水量。
- Fake Health：心率、血氧、活動狀態、步數、量測時間與資料品質。
- SQLite 保存事件、證據、健康樣本、模型呼叫、分析、動作及應用程式 logs。
- Dashboard 即時呈現 camera、Frigate、VAD、ASR、local VLM、MiniMax、事件、健康與 tools 狀態。
- MiniMax 可依指定時間窗分析健康資料與跌倒／喝水聚合。
- MiniMax 不可用時，事件偵測、SQLite 與 Dashboard 仍可運作。
- Agent Orchestrator 實際執行 Event Understanding、Health Context、Risk 與 Intervention logical agents。
- Memory、State、Health、Speak、Notify、Frontend tools 具可呼叫、可驗證、可稽核的實作。
- L3 Notify Tool 使用 Telegram Bot，保存 delivery、acknowledged、false_alarm 與 failed 狀態。
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
2. Live RTSP 可連續運作並在 Frigate 事件後取得 snapshot／clip；Replay 使用相同 downstream contract。
3. 跌倒與喝水各至少有一段正例影片及一段容易混淆的負例影片。
4. 每筆確認事件都能由 SQLite 反查模型結果、證據時間窗與 model/prompt version。
5. 喝水 count 由 SQL 聚合 confirmed session；重新播放或重送不重複計數。
6. 前端在 backend 寫入事件後 2 秒內收到更新；模型推論時間獨立顯示。
7. MiniMax 分析只接收健康快照與 SQL 聚合摘要；除非明確要求，不傳完整影片。
8. MiniMax timeout 或 schema invalid 時顯示 degraded，不能卡住主事件管線。
9. API key 不出現在 frontend bundle、SQLite logs、console output 或 Git tracked files。
10. Mic → VAD → Whisper → transcript buffer 可用實際聲音完成一次 E2E。
11. Memory／State／Health／Speak／Notify／Frontend tools 各有 contract test。
12. Long-term Observer 能以測試時鐘產生一次 daily summary 與 finding。
13. 所有驗證命令、部署步驟及舞台操作可由新環境照文件重現。
14. Telegram 測試 chat 可收到 L3 event，按下 acknowledgement 後 SQLite 與 Dashboard 同步更新。
