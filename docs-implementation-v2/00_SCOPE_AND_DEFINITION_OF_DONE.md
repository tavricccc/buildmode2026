# 00 · 產品範圍與完成定義

## 1. Demo 要證明什麼

系統能從 replay 或 camera source 取得影像，在 Mac mini 本地辨識跌倒與喝水，把事件存入 SQLite，立即更新 Web Dashboard，並讓 MiniMax 使用健康快照與事件聚合摘要產生可追溯的健康／風險分析。

核心展示鏈：

```text
預錄影片（即時播放）
  → 本地抽幀與 Qwen-VL
  → 跌倒／喝水事件狀態機
  → SQLite
  → WebSocket
  → Dashboard
  → MiniMax-M3 讀取健康快照與事件統計
  → 分析結果／建議／警報狀態回寫 SQLite 與 Dashboard
```

## 2. P0 必做

- 單一使用者、單一場域、單一影片來源。
- Replay source 支援載入、播放、暫停、重設及接近即時的時間軸。
- Qwen-VL adapter 產生版本化 JSON，不讓自由文字直接進事件狀態機。
- 跌倒事件：候選、持續、恢復、確認與警報狀態。
- 喝水事件：候選、確認、session 去重、次數與估算飲水量。
- Fake Health：心率、血氧、活動狀態、步數、量測時間與資料品質。
- SQLite 保存事件、證據、健康樣本、模型呼叫、分析、動作及應用程式 logs。
- Dashboard 即時呈現所有 P0 資料。
- MiniMax 可依指定時間窗分析健康資料與跌倒／喝水聚合。
- MiniMax 不可用時，事件偵測、SQLite 與 Dashboard 仍可運作。

## 3. P1 有時間再做

- RTSP 手機來源。
- Frigate event adapter 與 snapshot／clip 索引。
- macOS 系統 TTS。
- 前端可調整部分風險時間窗與飲水目標。
- 人工確認／修正事件，以及利用修正結果建立 replay evaluation set。

## 4. 本次不做

- 真實 HealthKit、FHIR 或醫療院所整合。
- ASR、聲音事件分類與水聲辨識。
- 真實 LINE、SMS、電話或緊急服務通知。
- 多租戶、完整 RBAC、不可竄改 audit store。
- 長期診斷、疾病預測或自動醫療判斷。
- 多台獨立 Agent service；Agent 先以同一 backend 內的邏輯單元實作。

## 5. Definition of Done

1. 一鍵 reset 後可連續完成兩次相同 Demo，不受前次 runtime state 污染。
2. 預錄影片的 frame 必須在現場送入本地模型；不能只播放預先寫死的最終事件。
3. 跌倒與喝水各至少有一段正例影片及一段容易混淆的負例影片。
4. 每筆確認事件都能由 SQLite 反查模型結果、證據時間窗與 model/prompt version。
5. 喝水 count 由 SQL 聚合 confirmed session；重新播放或重送不重複計數。
6. 前端在 backend 寫入事件後 2 秒內收到更新；模型推論時間獨立顯示。
7. MiniMax 分析只接收健康快照與 SQL 聚合摘要；除非明確要求，不傳完整影片。
8. MiniMax timeout 或 schema invalid 時顯示 degraded，不能卡住主事件管線。
9. API key 不出現在 frontend bundle、SQLite logs、console output 或 Git tracked files。
10. 所有 P0 驗證命令及舞台操作步驟可由新環境照文件重現。

