# Care Agent 舞台 Demo 簡化版

交付時間：2026-09-06 10:00（Asia/Taipei）

本目錄定義舞台縮小版。完整書審架構位於 ../docs-implementation-v2/。簡化版沿用完整架構的 Event、SQLite、REST、WebSocket 與 Agent contracts，不建立第二套不相容程式。

使用相同頂層啟動命令：

    bun start

在前端 Setup Wizard 選擇 Demo mode、Qwen3-VL-8B、MiniMax 與選用的 Telegram Bot；模型下載與設定均由前端觸發 backend job。

## 展示鏈

    預錄跌倒／喝水影片，以即時速度播放
      → 現場 Qwen3-VL-8B 4-bit 推論
      → 跌倒／喝水 state machine
      → SQLite
      → WebSocket Dashboard
      → Fake Health + 事件 SQL 聚合
      → MiniMax-M3 健康／風險分析
      → Dashboard alert

## 必做

- ReplaySource load、play、pause、reset。
- 跌倒與喝水各一支正例影片。
- 本地 Qwen3-VL-8B 現場推論；4B 僅作明示 fallback。
- 每筆 confirmed event 寫 SQLite。
- 今日喝水次數、估算 ml、目標完成率。
- Fake Health scenario。
- MiniMax 分析 1h／6h／24h／7d 可選窗口。
- Dashboard 顯示影片、health、hydration、events、analysis、logs 與 alert。
- MiniMax failure 顯示 degraded，主流程不停止。

## 可以簡化

- 不啟動 Frigate，ReplaySource 直接產生與 Frigate adapter 相同的 contract。
- 不啟動 microphone、VAD、Whisper。
- Notify Tool 預設在 Dashboard 建立 alert；已設定 Telegram Bot 時可展示真實 L3 通知與 acknowledgement。
- Long-term Observer 必須實際執行；可用 seed historical records 加速產生 7／30 日資料，但 aggregation、baseline、finding 與 SQLite 寫入不能預先寫死。
- 不做 RTSP 斷線恢復展示。

## 不可假裝

- 預錄影片可以，但推論結果不能預先寫死。
- 使用 fallback model 時 UI 必須顯示實際模型。
- 飲水 ml 是設定容量估算，不是視覺精確測量。
- Fake Health 必須標示 simulated。
- 舞台未啟動的完整元件要標成停用，不能顯示 healthy。

## 舞台流程

1. 開啟 Dashboard 並確認 backend、DB、Qwen、MiniMax healthy。
2. Reset run。
3. 播放跌倒影片，展示 suspect → confirmed → 未恢復 → alert。
4. Reset run。
5. 播放喝水影片，展示 completed session → SQLite count → hydration progress。
6. 切換 health scenario，選 24h，呼叫 MiniMax。
7. 對 seed historical records 實際執行 Long-term Observer，再到後台展示 7／30 日趨勢、coverage 與 finding。
8. 展示 MiniMax 使用 SQL aggregate，而不是重傳全部影片。

## 完成判準

- 同一流程連續跑兩次不重複計數。
- Backend commit 後 2 秒內更新 Dashboard。
- 模型 timeout、invalid JSON 與 MiniMax unavailable 都有可見錯誤狀態。
- 所有事件、分析與 action 可從 SQLite 查回。
- 有一份錄屏 fallback，但現場首選仍為真實推論。
