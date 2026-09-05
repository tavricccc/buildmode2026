# 07 · Model Routing 與 Runtime

## 1. 共享模型、分離能力

流程模型可依 provider 路由。當前 development profile 使用本機 Nemotron Omni vLLM；住民互動與理解／動機是同一個 agent 的不同驅動層。GMI Cloud `MiniMaxAI/MiniMax-M3` 只保留給獨立 ASR adapter，差異在 prompt、context、tools、permission 與 output schema，不在複製三個 agent。

目前影像／音訊路徑：

```text
L0 change gate：2 FPS × 5 秒窗口，只輸出有／無
→ 有變化才送 10 ordered frames
+ 5 秒 16 kHz mono audio
→ 本機 nemotron_omni /v1/chat/completions
→ compact change description / only high-risk confirmation

住民語音互動的 ASR 是獨立路由：`audio → GMI MiniMax M3`；回覆文字與理解層仍回到本機 vLLM。TTS 目前先走瀏覽器本機 Web Speech API；MiniMax `speech-2.8-turbo` 保留為未來可選 fallback，沒有獨立 TTS key 時保持 unavailable，不用 GMI key 冒充。

一般 Observation 不啟動 Main Agent；高風險候選才會啟動 5 FPS confirmation、10 秒 Focus、Main Agent 與住民危急詢問。無變化 30 秒時，才進行 3 秒間隔、10 張影像的 quiet probe。
```

## 2. 路由等級

| Route | 用途 | 預設動作 |
|---|---|---|
| T0 Sensor | 收到 raw sensor metadata | 不叫 LLM |
| T1 Local rule | 去重、cooldown、event correlation、coverage | SQLite/local state |
| T2 Multimodal | 影像/音訊跨模態、重要或不確定 situation | 本機 Nemotron Omni vLLM |
| T3 Interaction | 已經過 attention policy 的 Ask/Remind | Resident Interaction prompt |
| T4 Caregiver | 日／週 privacy aggregate、baseline finding | Caregiver prompt |

## 3. 不應呼叫模型的情況

每個 `motion`、`person_present`、VAD transition 或一般 sensor event 不應單獨叫模型。先合併成 situation；只有 ambiguous、important、information-gap value 足夠時才升級。`SILENT` 與 local-only 都是合法結果。

## 4. Runtime 約束

- Omni request 以 `VLLM_MAX_CONCURRENCY` bounded semaphore 控制，預設可並行 2 個 request；Observation、Focus、Main Agent、摘要與住民互動／理解共用同一上限。
- media sampler 以 `VLLM_MAX_PENDING_WINDOWS` 限制尚未完成的窗口 task，超出時明確記錄 skipped/backpressure，不假裝完成分析。
- 2 FPS、5 秒、10 frames；window stride 預設 5 秒。沒有新 Observation 30 秒時，quiet probe 使用 3 秒間隔共 10 frames。
- vLLM 使用本機 `nemotron_omni`、FP8 KV cache、已驗證的模型啟動參數；不使用 CPU offload。
- 本機路由的音訊只以短暫 WAV local URI 供單次 request，完成即刪除；GMI 路由改用 request 內 data URL，不在本機落地保存。
- GMI M3 只在住民互動 ASR 明確需要且取得同意後啟用；API key 從 `GMIAPI.txt` 讀入記憶體，不進前端、SQLite 或 logs。主影像流程不送雲端。
- 原始 prompt、raw response、完整 audio/video 不進 logs。

## 5. Main Agent 輸出與判斷

Main Agent 使用同一 Omni endpoint，但 purpose、prompt、schema 與 audit record 與 observation 分離。它輸出 facts、跨 frame 時序、existing-first event assessment、hypothesis、unknown、uncertainty、risk、attention、proposed action 與 next action；不輸出 hidden chain-of-thought。

模型輸出後進 `MainAgentPolicy`：先檢查 evidence/confidence，再計算可重現的 attention score，最後套 critical overrides 與 fail-closed。所有 `ask`／`dashboard_alert` 都只是 policy proposal；未來接 Resident Interaction 或 Notify 前仍需 consent、recipient、cooldown 與 idempotency gate。

## 6. 觀察輸出

Model 只能輸出 typed `Observation`：visual posture/transition、audio events/emotion、confidence、supporting indexes、uncertainty 與 exceptional `event_candidates`。`fall`／`hydration` 仍交給既有 state machine；未知欄位保留 unknown。

## 7. 降級

GMI／vLLM unavailable、timeout、schema invalid 時，保留 sensor metadata、最近可靠 Observation 與 local rule 結果，Main Agent run 標記 failed，policy 固定為 `insufficient_data → silent`，並明確標記 `degraded=true`。不可把缺失資料解讀成正常，也不可因模型失敗自動升級 L4。

## 8. 驗收

每個 route 保存 model/prompt/schema/config version、input hash、latency、status、retry 與 fallback。測試需覆蓋 multimodal valid/invalid、Main Agent judgment schema、policy gates、timeout、missing audio、10-frame limit、parallel queue/backpressure、dedup 與 model reconnect。
