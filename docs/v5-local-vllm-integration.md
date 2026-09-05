# v5 / local vLLM 整合邊界

這份文件記錄目前可執行版本的組合方式：以 `origin/feat/v5-complete-flow` 的住民互動、社工紀錄、報告、稽核與 reset 為保留功能，採用 `origin/main` 的文件基線、照護首頁、運作監看、Debug runtime 與 pipeline step 稽核。

## 實際 runtime

目前唯一的 implementation root 是 `src/`：

```text
source → L1 person gate → L2 observation → state machines → L3 review → Policy Gateway
                                                         ├→ care dashboard
                                                         ├→ notifications
                                                         └→ SQLite + WebSocket audit
```

`src/backend/local_vllm.py` 使用 OpenAI-compatible API。預設設定是：

- L2：`local_vllm`、`VLLM_BASE_URL`（預設 `http://127.0.0.1:8000/v1`）、`VLLM_MODEL`（預設 `nemotron_omni`）。
- L3：同一個 local vLLM slot；可用 Settings 或 `L3_PROVIDER` 切換到 MiniMax。
- Care API：預設 `127.0.0.1:8200`，避免與 vLLM port 衝突。

模型只能回傳結構化觀察或建議；事件狀態、通知與外部行動仍由 deterministic state machine 和 Policy Gateway 決定。

## main 設計如何落地

| main 設計 | 現在的實作 | 證據邊界 |
|---|---|---|
| Care-first dashboard | `/api/care/summary`、Dashboard 首頁 | 可用 stub/replay 驗證；L3 live 能力仍需實際 provider 測試 |
| Operator Console | `operations` 頁、`pipeline_steps`、`/api/pipeline/active`、`pipeline.step` | pipeline 狀態可由 SQLite/WebSocket 驗證 |
| Debug isolation | `--debug`、獨立 data dir、simulation runs、debug routes | Production 不註冊 debug routes；不把 debug DB 匯入 production |
| Replay EOF | source lifecycle `completed`／`failed` | 正常 EOF 不建立新的分析 window；FFmpeg 非零結束才是 failure |
| Video upload replay | upload WebSocket → `uploads/*-480p.mp4` → `ReplaySource(realtime=True)` | 起始秒數在本機裁切；完成後以影片內時長節奏進入同一條 Cascade |
| Provider failure contract | L2/L3 都回傳一致的 failure outcome | contract 可測，不等於本地模型一定有正確影像或音訊理解 |

## feature 功能保留

- `social_work_records` 與 `status_reports` 是人工紀錄和 AI 草稿的不同資料邊界。
- 社工自動彙整保留事件、觀察、健康量測、互動與原始紀錄的 source IDs，結果必須人工覆核。
- `resident interaction` 是可回覆的 interaction driver；background understanding 只提供 advisory insight。
- `care-system.log` 與 SQLite `app_logs` 同時保留有界系統紀錄。
- `reset history` 只清 runtime history，不清設定版本、schema migrations 或 secrets。

影片上傳不是另一條推論流程：WebSocket 只負責分片接收，轉檔完成後由 `AppContext.start_source("replay_file", ...)` 啟動與 RTSP／本機 replay 相同的 FrameWindow、L1、L2、L3、Policy、SQLite 與 WebSocket 路徑。`ReplaySource(realtime=True)` 以影片內 FPS 等待，不將整部影片瞬間灌進 queue；壓縮後檔案會留在 `src/data/uploads/`，原始分片只作轉檔暫存。

## local vLLM 的驗證分層

目前已驗證的是 Python／SQLite／stub contract 與前端 build；這些不能代替真實 Nemotron 的多模態品質驗證。正式測試應分開記錄：

1. `/v1/models` 與文字請求：只證明 endpoint／model 可連線。
2. 影像 window：需保留實際 payload、模型回應與可重現的 replay context。
3. 音訊 PCM：需有音訊衍生證據，不能以文字 API 成功推論 ASR 或 audio understanding 已可用。
4. L3 escalation：需確認模型輸出通過 validator，並由 Policy 決定是否產生 action。

離線驗證指令：

```powershell
cd src
python -m compileall -q backend
python -m unittest discover -s backend/tests -t .
cd frontend
bun run typecheck
bun run build
```

`--stubs` 只驗證下游契約；啟用 local vLLM 前，應先確認本機 vLLM 已由外部流程啟動且 `/v1/models` 可用，系統本身不會下載模型或自動啟動 vLLM。

## 尚未宣稱完成的能力

ASR／完整語音事件分類、FHIR／HealthKit、Frigate 主 trigger、長期 world-state 與多住民／RBAC 仍屬目標架構或後續工作，不因 main 文件提到它們就視為目前 v5 runtime 已完成。
