# 09 · Live Media、全時 QwenVL Loop 與語音

## 1. Video ingest

手機 app 輸出 RTSP，Backend 以 OpenCV 或 PyAV 持續連線、decode、重連並將最新影格寫入 bounded ring buffer。不使用 Frigate、go2rtc、MQTT、person／motion detector 或任何事件式前置篩選。

資料流：

```text
iPhone / Android RTSP
  → RtspSource decode / reconnect
  → bounded ring buffer
  → fixed-rate Continuous Vision Loop
  → Frame Buffer / Sampler
  → Qwen3-VL-8B
  → structured VisionObservation
  → fall / hydration state machines
```

Source Manager 必須：

- 為每個 frame 產生單調遞增 sequence、captured time 與 source status。
- RTSP 中斷時使用有上限的退避重連；不得讓 read 永久阻塞 shutdown。
- 只保留最近窗口，不把 raw stream 無界存入記憶體或磁碟。
- camera offline、frame stale、decode error 與 clock drift 形成 status 與 data-quality record。

## 2. 全時 QwenVL loop

Continuous Vision Loop 不等待 candidate event。只要 source healthy，就依 `VISION_LOOP_INTERVAL_MS` 建立最新視覺窗口並呼叫 QwenVL；背景無人或無動作時仍會得到 `none` observation。

排程規則：

- Local VLM concurrency 固定為 1。
- 同時只能有 1 個 running job 與 1 個 latest pending job。
- 新 tick 到達而 pending 尚未開始時，以新窗口覆蓋舊窗口並增加 `dropped_windows`；不得排出無界 FIFO。
- 每個 job 固定保存 window start/end、frame sequences、queue delay、inference latency、model revision 與 prompt version。
- timeout、invalid JSON、low confidence 只形成可觀測結果，不得停止下一個 tick。
- interval 必須根據 M4 16GB 的 p95 latency 設定；初始 benchmark 建議從 1 FPS、最多 8 frames、每 3 至 5 秒一次推論開始。

這裡的「全時」是持續排程，不代表每一個 camera frame 都各跑一次模型。逐幀推論在單一 M4 16GB 上會造成延遲與記憶體 backlog，也沒有必要。

## 3. Evidence 與短期媒體

- Frame Buffer / Sampler 預設只保留最近 15 秒的記憶體窗口。
- state machine 進入 suspect 或 confirmed 時，將相關抽樣 frames 固化為 EvidenceReference。
- 若要保存短 clip，由 backend 在事件時從 ring buffer 匯出；v3 不需要完整 NVR recording。
- evidence retention 由設定控制，到期刪除不影響 SQLite 中的事件與模型稽核資料。

## 4. Audio pipeline

```text
Host microphone 16 kHz mono PCM
  → bounded ring buffer
  → Silero VAD
  → speech segment
  → Whisper job
  → Transcript Buffer
  → Event Assembler / Agent context
```

- MicCapture 只產生 timestamped PCM chunks。
- VAD worker 產生 speech start/end、probability 與 segment ID。
- Whisper adapter 只接完整 speech segment，輸出 timestamped Chinese transcript。
- Transcript Buffer 依 retention 設定清除文字；清除工作需可測試。
- Qwen 與 Whisper 共用 unified memory 時由 Resource Arbiter 排程，vision loop 優先，但不能讓 ASR 永久 starvation。

## 5. Multimodal 對齊

- 系統時間為 canonical clock。
- 每個 frame、vision window、audio segment 與 transcript 都保存 occurred time。
- Assembler 以 configurable pre/post window 找出 observation 附近 transcript。
- 缺音訊、缺影像或時間偏差不等同沒有發生；Bundle 顯式保存 missing／stale 狀態。

## 6. 共用 Source contract

RtspSource 與 ReplaySource 均輸出相同的 SourceStatus 與 FramePacket。Continuous Vision Loop 統一產生 VisionJob；下游 state machine 不得依 live／replay 來源型別寫分支。

## 7. 驗收

1. 手機關閉 RTSP 後，Dashboard 顯示 offline；恢復後自動重連。
2. 畫面沒有 person／motion 事件時，loop 仍依節拍產生 `none` observation。
3. Qwen 可取得有序 frames、source offset 與完整 window metadata。
4. 推論慢於 tick 時不累積 backlog；pending 永遠最多 1，dropped metric 可見。
5. 說一句中文後，VAD 建立 segment、Whisper 產生 transcript、到期後文字被清除。
6. 連續運作 30 分鐘不發生程序 OOM，RTSP、Qwen timeout 與 invalid JSON 都可自行恢復。
