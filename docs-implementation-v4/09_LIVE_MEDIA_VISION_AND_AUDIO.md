# 09 · Live Media、Vision Loop 與 Audio

## Video

OpenCV 或 PyAV/FFmpeg 直接解碼 RTSP，寫入 bounded ring buffer。硬體解碼可選 `auto`、`cpu`、`nvidia`、`amd`；backend probe 後才允許選取，不健康時回 CPU。domain frame contract 不包含 vendor-specific object。

Continuous Vision Loop 依前端設定的 interval/window/FPS/max frames/JPEG quality 呼叫 active `vision` model。最多一個 running 和一個 latest pending；不累積 FIFO。Local endpoint 和 cloud endpoint 使用完全相同的 image message、timeout、schema validation 與 model-call audit。

Cloud profile 顯示資料目的地與 requests/hour；local profile顯示 device、VRAM/RAM 與 server health。兩者都需限制 request bytes，並在 suspect/confirmed 時才依 retention 設定固化 evidence。

## Audio

```text
Host microphone → bounded PCM buffer → VAD → speech segment
  → active transcription model (`/v1/audio/transcriptions`)
  → Transcript Buffer → Agent context
```

VAD 可以是非模型式 local gate；若使用模型式 VAD，也必須由 model slot 經 OpenAI-compatible endpoint，不能成為隱藏的 vendor SDK 例外。Segment duration、silence、language、prompt、retention 與 queue limit 可在前端設定。

所有 frame、window、audio segment、transcript 使用 canonical system time。缺資料、stale、endpoint timeout 都顯式記錄，不解釋成「事件未發生」。
