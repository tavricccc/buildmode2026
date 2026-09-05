# 09 · Live Media、Vision Loop 與 Audio

## Video

FFmpeg 直接解碼 RTSP 寫入 bounded ring buffer。Vision job 從 buffer 取出時間窗切成**短片段**(P0:5 秒 @ 2fps,含音軌,容器格式依 provider 支援清單),經 Model Gateway 送出。domain frame contract 不包含 vendor-specific object。

硬體解碼可選 `auto`、`cpu`、`nvidia`、`amd`,backend probe 後才允許選取,不健康時回 CPU。**P0 為 cloud-only 部署,硬體解碼固定 `cpu`,多硬體 probe 屬 P2。**

Continuous Vision Loop 依 `03` 的三段頻率呼叫 active `vision` model:基準心跳、變化觸發 burst、狀態機強制 burst。最多一個 running 和一個 latest pending,不累積 FIFO。

片段長度必須大於等於單次 round trip 延遲,否則工作持續累積。實測延遲若超過片段長度,應延長基準心跳間隔,不得縮短片段——縮短片段會同時削弱時序判斷。

Local endpoint 和 cloud endpoint 使用完全相同的 media message、timeout、schema validation 與 model-call audit。Cloud profile 顯示資料目的地與 requests/hour;local profile 顯示 device、VRAM/RAM 與 server health。兩者都需限制 request bytes,並在 suspect/confirmed 時才依 retention 設定固化 evidence。

## Audio

P0 的音軌**隨影片片段一併送出**,不另外抽取:

```text
RTSP → bounded buffer → 5 秒片段(video + audio)
  → active vision model → VisionObservation
```

獨立的音訊管線維持規格但**列為 P1**,在 vision model 確認不理解音訊、或需要逐字稿供 Agent 使用時啟用:

```text
Host microphone → bounded PCM buffer → VAD → speech segment
  → active transcription model (`/v1/audio/transcriptions`)
  → Transcript Buffer → Agent context
```

VAD 可以是非模型式 local gate;若使用模型式 VAD,也必須由 model slot 經 OpenAI-compatible endpoint,不能成為隱藏的 vendor SDK 例外。Segment duration、silence、language、prompt、retention 與 queue limit 可在前端設定。

> **未決**:vision model 是否實際理解音軌內容,尚未實測(見 `03` 未決事項)。確認理解則 P0 不需獨立 ASR;確認忽略則 P1 的音訊管線需提前。在實測回填前,不得宣稱系統具備聲音事件偵測能力。

## 時間與缺漏

所有片段、window、audio segment、transcript 使用 canonical system time。缺資料、stale、endpoint timeout 都顯式記錄,**不解釋成「事件未發生」**。變化偵測未觸發同樣不等於無事件,故基準心跳無條件執行(見 `03`)。
