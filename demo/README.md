# Ambient Care Agent 舞台 Demo

這個目錄描述可控的舞台流程。完整產品與技術規格見 [../SPEC.md](../SPEC.md)，實作契約見 [../docs-implementation-v2/README.md](../docs-implementation-v2/README.md)。Demo 不假裝是全天候 surveillance，也不把模型自由文字當成事實。

## 舞台展示鏈

```text
Browser camera + microphone
  → continuous MediaStream
  → 2 FPS / 5 秒 / 10 frames + audio
  → local Nemotron Omni VLM
  → Known / Unknown / Hypothesis + event candidate
  → fall/hydration state machine or exception ledger
  → Active Inquiry / Silent policy
  → Memory / Caregiver aggregate / Dashboard
```

## 必做

- HTTPS camera/microphone permission 與 live preview。
- VLM live panel 顯示 frame window、audio、sound、emotion、confidence。
- 既有 `fall`、`hydration` 事件；例外聲音、人物、物件事件使用 generic event contract。
- Unknown、uncertainty、coverage 與 model latency 可見。
- Event Ledger 可回查 evidence、window、model、版本與 dedup。
- Active Inquiry 至少一個「資訊不足但值得問」的可控示例。
- Default Silent，不把每個 sensor event 都交給模型。
- Caregiver view 只展示 aggregate、baseline 與 finding，不展示 raw camera。

## 可控 fallback

現場可用 `Demo Event Injector` 注入 typed event，例如 `fridge_open`、`fridge_closed`、`person_entered`、`door_knock` 或 `fall`；後續 correlation、World State、policy、memory 與 dashboard 仍走正式程式。Injected event 必須在 UI 標示 `demo_injected`，不得冒充真實 sensor。

## 不可假裝

- Browser stream 是 continuous media，不是 screenshot polling。
- `audio_present` 只代表 audio track 已提供；audio event 仍要有模型證據。
- `fall` 不能由單張 lying 確認；`hydration` 只有完成 session 才計數。
- VLM unavailable 時顯示 degraded，不能把 Unknown 寫成正常。
- Fake Health 必須標示 simulated。
- 系統不做診斷、治療或 L4 emergency executor。

## 舞台流程

1. 啟動本機 `nemotron_omni` 與 Care Agent，開啟 HTTPS Dashboard。
2. 允許 camera/mic，確認 2 FPS、5 秒、10 frames 與 audio window。
3. 展示人物離開視野後 `current_location=UNKNOWN`，不硬猜。
4. 展示冰箱開關／購物袋等事件被合併成 situation；物品看不清時建立 information gap。
5. 在可打擾條件下詢問住戶，將回答寫成 resident-confirmed memory。
6. 展示 `fall`／`hydration` 仍使用既有 state machine，例外聲音與物件事件使用 generic ledger。
7. 切換 caregiver view，展示 privacy aggregation、baseline 與 finding。

## 驗收

- 同一 stream/window 重送不重複事件或 action。
- VLM timeout、invalid JSON、缺 audio/frame、WSS 重連與 reset 都有可見狀態。
- 每筆 event 有 Known/Unknown/Hypothesis 邊界與 provenance。
- Demo 可在沒有 Frigate 的情況下完成；Frigate 只作未來 adapter。
