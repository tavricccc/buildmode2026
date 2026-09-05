# 09 · Live Media、Frigate 與語音

> **v3 amendment：** Frigate 不再是 current VLM path 的必要前置。Browser MediaStream 直接進 backend；Nemotron 以 2 FPS/5 秒取 10 frames，同時取 5 秒 PCM audio。Frigate RTSP/MQTT adapter 保留作未來異質 sensor。

## 1. Video ingest

目前 live ingest 由 HTTPS browser 直接提供 camera + microphone MediaStream。Frontend 以 `MediaRecorder` 將 continuous WebM chunks 經 `/ws/media` 傳給 backend；這是 virtual camera stream，不是週期性 screenshot 上傳。Backend 負責 bounded buffering、抽幀與音訊對齊，再送 Nemotron Omni vLLM。

Browser WebM 會以 rolling segment 暫存最近 60 秒。5 FPS description sampler 預熱收集但只有第一層回傳 change/warning 才送模型；Main Agent 一般只接 description/context，attention gate 通過後才取 2 FPS × 10 秒 focus window。

資料流：

    Browser camera + microphone MediaStream
      → HTTPS/WSS `/ws/media`
      → backend continuous session
      → 2 FPS frame sampler + 5 秒 audio sampler
      → 10 frames + 16 kHz mono audio window
      → Nemotron Omni vLLM
      → typed observation / existing events / recognition_events
      → SQLite + `/ws` Dashboard updates

    （optional）RTSP → Frigate/go2rtc/MQTT adapter → same normalized downstream contract

Optional Frigate adapter 必須：

- 將 Frigate event ID、camera、label、zones、start/end time、snapshot/clip availability 正規化。
- 使用 Frigate event ID 與 update type 做 idempotency。
- 媒體尚未 ready 時有限次重試，不阻塞 event consumer。
- camera offline、clip missing、clock drift 形成 status 與 data-quality record。
- 只在 retention window 內保存本地 media reference。

## 2. Frigate／RTSP adapter 部署

- Frigate 使用與 host 相容的 Docker image；本機 Windows/WSL 開發若未啟用，狀態要明確為 disabled。
- backend 只有在啟用此 adapter 時才檢查 Frigate API、MQTT broker、camera 與 detector endpoint。
- Frigate event 不得繞過 Event Correlator；snapshot/clip 只作 evidence reference，不改變 existing-first 規則。
- Port、volume、camera URL 與 credentials 由環境變數或未追蹤設定注入；不得寫進 frontend bundle 或 Git。

## 3. Audio pipeline

    Browser microphone MediaStream
      → WebM audio chunk
      → backend bounded ring buffer
      → 5 秒 audio window / 16 kHz mono WAV
      → Nemotron Omni audio observation
      → audio_events / speaker_emotion / uncertainty
      →（後續）Silero VAD → Whisper → Transcript Buffer
      → Event Assembler / Agent context

- Browser capture session 只產生 timestamped bounded media chunks；raw audio 預設不保存。
- Current Omni path 產出窗口級 `audio_present`、`audio_events`、`speaker_emotion`、confidence 與 uncertainty。
- VAD worker（後續）產生 speech start/end、probability 與 segment ID。
- Whisper adapter（後續）只接完整 speech segment，輸出 timestamped Chinese transcript。
- Transcript Buffer 依 retention 設定清除文字；清除工作需可測試。
- Nemotron 與後續 Whisper 共用 GPU/CPU 資源時由 Resource Arbiter 排程，realtime window 優先。

## 4. Multimodal 對齊

- 系統時間為 canonical clock。
- 每個 frame、Frigate event、audio segment 與 transcript 都保存 occurred time。
- Assembler 以 configurable pre/post window 找出事件附近 transcript。
- 缺音訊、缺影像或時間偏差不等同沒有發生；Bundle 顯式保存 missing／stale 狀態。

## 5. 共用 Source contract

FrigateSource、RtspSource 與 ReplaySource 均輸出相同的 SourceStatus、FramePacket、EventCandidate 與 EvidenceReference。下游 state machine 不得依來源型別寫分支；來源差異只存在 adapter。

## 6. 驗收

1. Browser 停止 permission 或 WebSocket 後，Dashboard 顯示 offline/degraded；重新授權後可建立新 stream session。
2. Frigate 同一事件的 start/update/end 不產生三筆獨立 domain event。
3. Nemotron 可取得事件窗口的 10 張有序 frames、audio duration 與 offset。
4. Current gate：有實際環境聲時 Omni 能回傳 audio metadata；VAD/Whisper transcript 為後續 gate。
5. Nemotron realtime-critical job 可優先於一般 ASR job，不造成程序 OOM。

