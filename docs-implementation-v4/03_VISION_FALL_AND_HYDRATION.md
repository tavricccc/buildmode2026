# 03 · 視覺、跌倒與喝水 Pipeline

## Vision model contract

一次 job 接收 1–8 張有序 JPEG frame、時間資訊與固定 prompt，經 Model Gateway 送到 active `vision` model。Local 與 cloud endpoint 都必須支援 OpenAI-compatible image content，回傳 v3 相容 `VisionObservation`：posture、vertical transition、near-floor、容器、靠嘴、飲用動作、confidence、supporting frame indexes 與 uncertainty。

- Pydantic/schema 驗證失敗保存 invalid model call，不更新事件。
- 保存 input hash、frame offsets、endpoint/model/deployment type、latency/usage、prompt/schema/config version，不保存 secret。
- Cloud endpoint 顯示影格傳輸告知；local endpoint 不得被 UI 誤標為 cloud，反之亦然。
- 不支援 multi-image 或 structured output 的 model 不可安裝到 vision slot。

## 狀態機

跌倒沿用 `idle → suspect → confirmed → recovering → resolved`；單張 lying 不得直接確認。喝水沿用 `idle → suspect → confirmed → active → completed`；只有 completed session 計數，重試不得重複。

## 抽幀、成本與資源

baseline FPS、window、max frames、interval、JPEG edge/quality、request bytes、suspect burst 和 budget 都可在前端設定。Pending 永遠最多一筆。Cloud 顯示 rate/cost estimate；local 顯示 RAM/VRAM、queue 和 benchmark。Provider 不支援必要能力時 probe 必須失敗，不可靜默改變契約。

## Evidence

只有 suspect/confirmed 周邊抽樣影格依 retention 固化。Evidence 記錄是否離開主機、endpoint、傳送時間與 model call reference，讓操作者可稽核資料流向。
