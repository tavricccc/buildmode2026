# Care Agent 完整程式實作文件 v2

版本：2026-09-04  
舞台里程碑：2026-09-06 10:00（Asia/Taipei）

這個目錄定義書審要實際完成的完整程式架構。既有 `SPEC.md`、`docs/` 與互動式 HTML 均保留為參考，不由本文件集覆蓋。舞台簡化版另見 `../demo/`。

## 已定案範圍

- 執行環境：Mac mini M4、16 GB unified memory。
- 正式輸入：iPhone／Android RTSP live stream，由 Frigate 持續 ingest、tracking、recording 與產生事件；ReplaySource 只用於測試、回歸與舞台備援。
- 本地視覺：`Qwen3-VL-8B-Instruct` 4-bit；若在 M4 16GB 的實測穩定性或延遲不達標，才降至 4B。
- 首波視覺事件：跌倒、喝水。
- 本地音訊：Mic capture → Silero VAD → Whisper；ASR 只處理 VAD 切出的 speech segment。
- 雲端模型：`MiniMax-M3`，由可設定的 OpenAI-compatible endpoint 呼叫。
- L3 通知：Telegram Bot，支援事件訊息、snapshot 與照護者 acknowledgement。
- 持久化：SQLite。跌倒與喝水的候選、確認結果、時間、信心、模型版本及證據索引都必須落庫。
- 前端：即時影片、系統狀態、健康資料、事件時間線、logs、飲水統計、MiniMax 分析及警報。
- 風險：以可設定時間窗查詢 SQLite 聚合結果；MiniMax 只讀必要摘要，不反覆讀取完整事件或影片。

## 文件順序

1. [產品範圍與完成定義](00_SCOPE_AND_DEFINITION_OF_DONE.md)
2. [系統元件、功能與邊界](01_SYSTEM_COMPONENTS_AND_BOUNDARIES.md)
3. [事件、Agent 與 Policy 契約](02_EVENT_AGENT_AND_POLICY_CONTRACTS.md)
4. [跌倒與喝水視覺 Pipeline](03_VISION_FALL_AND_HYDRATION.md)
5. [SQLite 資料模型與查詢](04_SQLITE_DATA_MODEL.md)
6. [Backend API 與即時通訊](05_BACKEND_API_AND_REALTIME.md)
7. [Web Dashboard](06_WEB_FRONTEND.md)
8. [MiniMax 健康與風險分析](07_MINIMAX_HEALTH_AND_RISK.md)
9. [實作順序、分工與驗證](08_IMPLEMENTATION_AND_VERIFICATION.md)
10. [Live Media、Frigate 與語音](09_LIVE_MEDIA_FRIGATE_AND_AUDIO.md)
11. [Long-term Observer](10_LONG_TERM_OBSERVER.md)
12. [完整部署與啟動](11_DEPLOYMENT_AND_OPERATIONS.md)
13. [Telegram L3 通知](12_TELEGRAM_L3_NOTIFICATION.md)
14. [前端 Setup 與模型管理](13_SETUP_AND_MODEL_MANAGEMENT.md)

## 規格優先級

衝突時依序採用：本文件集的具體契約 → 本文件集的完成定義 → 原 `docs/` → HTML 架構圖。完整架構與舞台簡化版共用資料與 API 契約；`demo/` 可以少啟動 adapter，不可建立另一套不相容 contract。
