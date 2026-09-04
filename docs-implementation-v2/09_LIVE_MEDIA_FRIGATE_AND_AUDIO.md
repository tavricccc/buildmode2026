# 09 · Live Media、Frigate 與語音

## 1. Video ingest

手機 app 輸出 RTSP，Frigate 與 go2rtc 負責連線、重連、decode、detect、recording、snapshot 與 clip。Backend 不重造 NVR，只透過 Frigate API／MQTT adapter 取得事件與媒體。

資料流：

    iPhone / Android RTSP
      → go2rtc restream
      → Frigate camera
      → person / motion tracked event
      → MQTT event adapter
      → normalized EventCandidate
      → snapshot / clip fetch
      → Frame Sampler
      → Qwen3-VL-8B

Frigate adapter 必須：

- 將 Frigate event ID、camera、label、zones、start/end time、snapshot/clip availability 正規化。
- 使用 Frigate event ID 與 update type 做 idempotency。
- 媒體尚未 ready 時有限次重試，不阻塞 event consumer。
- camera offline、clip missing、clock drift 形成 status 與 data-quality record。
- 只在 retention window 內保存本地 media reference。

## 2. Apple Silicon 部署

- Frigate 使用 ARM64 Docker image。
- Apple Silicon detector 跑在 macOS host，透過 ZMQ endpoint 提供 Frigate detection。
- Backend 啟動前檢查 Frigate API、MQTT broker 與 detector endpoint。
- Port、volume、camera URL 與 credentials 由環境變數或未追蹤設定注入。

## 3. Audio pipeline

    Host microphone 16 kHz mono PCM
      → bounded ring buffer
      → Silero VAD
      → speech segment
      → Whisper job
      → Transcript Buffer
      → Event Assembler / Agent context

- MicCapture 只產生 timestamped PCM chunks。
- VAD worker 產生 speech start/end、probability 與 segment ID。
- Whisper adapter 只接完整 speech segment，輸出 timestamped Chinese transcript。
- Transcript Buffer 依 retention 設定清除文字；清除工作需可測試。
- Qwen 與 Whisper 共用 unified memory 時由 Resource Arbiter 排程，realtime fall job 優先。

## 4. Multimodal 對齊

- 系統時間為 canonical clock。
- 每個 frame、Frigate event、audio segment 與 transcript 都保存 occurred time。
- Assembler 以 configurable pre/post window 找出事件附近 transcript。
- 缺音訊、缺影像或時間偏差不等同沒有發生；Bundle 顯式保存 missing／stale 狀態。

## 5. 共用 Source contract

FrigateSource、RtspSource 與 ReplaySource 均輸出相同的 SourceStatus、FramePacket、EventCandidate 與 EvidenceReference。下游 state machine 不得依來源型別寫分支；來源差異只存在 adapter。

## 6. 驗收

1. 手機關閉 RTSP 後，Dashboard 顯示 offline；恢復後自動重連。
2. Frigate 同一事件的 start/update/end 不產生三筆獨立 domain event。
3. Qwen 可取得事件窗口的有序 frames 與 offset。
4. 說一句中文後，VAD 建立 segment、Whisper 產生 transcript、到期後文字被清除。
5. Qwen realtime-critical job 可優先於一般 ASR job，不造成程序 OOM。

