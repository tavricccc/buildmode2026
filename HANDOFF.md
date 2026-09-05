# HANDOFF — Care Agent 書審交付(2026-09-06 10:00)

_Updated: 2026-09-05 16:16 · 5h usage: 3% (resets 20:30) · 7d: 52% · ctx: 6%_

## Goal

書面資料 + code 於 **2026-09-06 10:00** 交付書審(剩約 17.7 小時)。書審看的是**規格書與 code 對不對得起來**,不是現場 demo(demo 要通過書審才會有)。簡報由組員處理。

## ⚠️ 本分支已封存 — 工作轉移到 main

使用者決定 **從 `origin/main` 重新開分支** 繼續寫。`codex/longcare-gmi-m3-flow` 到 `902b9bf` 為止,不再繼續開發、**不 merge 回 main**,保留作為挑揀來源。

新 session 請先:

```bash
git fetch --all --prune
git switch -c <新分支名> origin/main
```

### 三方狀態

| 分支 | HEAD | 內容 |
|---|---|---|
| `codex/longcare-gmi-m3-flow`(本分支) | `902b9bf`,已 push | 扁平 `backend/` + `frontend/` + `scripts/`,**實際打得到 GMI Cloud M3**,有 probe 實測 |
| `origin/main` | `d44e250` | v4 骨架 `v4/`(打 stub,無真實 model runtime)+ `gemini api test/` + 新提案 README |
| 共同祖先 | `c0bd3bf` | v4 規格書修改 |

兩邊是**兩套平行實作**:本分支有實跑但結構扁平;main 的 `v4/` 結構與規格書對得齊但只打 stub。

## Decisions

- **規格書以 `docs-implementation-v4/` 為準**,precedence `v4 → v3 → v2 → docs/`。
- **全雲端**,不再調本地 vLLM。本分支 Provider = **GMI Cloud** / `MiniMaxAI/MiniMax-M3`。
- Vision wire format **維持 `frames`**(10 張 base64 JPEG @ 2fps / 5 秒窗口);`video_url` 實測掉幀,列 P1。
- 結構化輸出用 **`json_object` + 驗證 + repair**,不依賴 `json_schema`/`strict`(provider 無保證)。
- 變化偵測是**加速器不是閘門**(基準心跳 + 事件未結案時強制觀測)。
- **本分支不回 main**(使用者指示),改從 main 重開分支。
- 交付分 **P0/P1/P2**,定義在 `docs-implementation-v4/00`。

## Done(本分支,全部已 push)

- **`91be771`** temporal care observation + GMI flow(引入 `backend/`、`frontend/`、`scripts/`)。
- **`bab8faa`** video_url wire format — `backend/adapters.py` 新增 `_encode_window_video`、`analyze_video`、`analyze_window`(依 `VISION_WIRE_FORMAT` 分派、失敗退回 frames)、`probe_video`;`backend/app.py:152` 改呼叫 `analyze_window`(預設 frames,行為不變)。
- **`de80fa1`** 修掉會讓跌倒永遠無法確認的 bug — 原 `backend/app.py:133` 是硬閘門,人躺著不動就沒有新 observation,`store.py:373` 的 `support >= 2` 永遠達不到。新增 `backend/change_gate.py:observation_override_reasons`(純函式),`app.py:114 session_observation_overrides` 接 session/store;`backend/tests/test_contracts.py` 加 5 個測試。
- **`10dfee5`** merge — 13 個衝突已解(docs/、SPEC.md、demo HTML 取 branch 版;`.gitignore` 取聯集保住 `GMIAPI.txt`;README 指向 v4)。
- **`97904f2`** 實測結果 — `docs-implementation-v4/14_PROVIDER_CONSTRAINTS.md` 全部換成實測數據;`scripts/probe_provider.py` 可重跑。
- **`902b9bf`** cloud model capability 與 audio contract(codex 所改,13 檔)—— flow model 可保留自訂 provider/endpoint/model ID;cloud flow model 不再依賴 `LOCAL_VLM_MODE`;model-call provenance 記錄實際 active model;cloud 預設 `json_object` 並明送 `context_length_exceeded_behavior=error`;GMI / 未 opt-in 的 cloud model **不送 audio 也不採信 audio/speech/sound candidate 回傳**;前端與 v4 文件的 audio unavailable/unknown 語意同步;`scripts/verify.mjs` 改用 `python3`。

### 本分支值得挑到新分支的東西(依重要性)

1. **`docs-implementation-v4/14_PROVIDER_CONSTRAINTS.md`** —— 本分支是**實測版**,`origin/main` 那份仍是**舊的文件推論版**(還寫著「輸入含 5 秒 16 kHz WAV」,實測音訊根本不進模型)。不挑過去會讓規格書寫著做不到的事。
2. **`backend/change_gate.py` + `app.py` 的 override 接線**(`de80fa1`)—— 跌倒確認的邏輯 bug 修復,`v4/` 骨架若照原設計實作會重蹈同一個坑。
3. **`scripts/probe_provider.py`** —— 零依賴、可重跑的 provider capability probe。
4. `backend/adapters.py` 的 GMI adapter 細節(UA、`context_length_exceeded_behavior`、audio 去假資料)。
5. `backend/tests/test_contracts.py` 的契約測試。

## main 上的新東西(組員 / 使用者提供)

- **`e2de64b`** `gemini api test/` —— 獨立 Gemini REST client,**零外部依賴**(純標準庫 urllib/base64/json/mimetypes),支援 video / audio / image / text,預設 `gemini-3.5-flash-lite`,≤20MB 走 inline base64、>20MB 走 Google Files API。**這正好補上 GMI 完全做不到的音訊**。CLI 與 `GeminiClient` class 兩種用法,見該目錄 README;key 放 `gemini api test/.env`(有 `.env.example`)。
- **`b293ab7`** `v4/` —— 204 檔 / 9,834 行 v4 骨架:完整目錄、Pydantic schema、Protocol、SQLAlchemy model、狀態機、全部 API route、stub OpenAI server、migrations、Setup Wizard / Settings / Dashboard 前端、19 個測試(含 hardware-neutral guard)。**其 README 明說不含真實 model runtime 整合、不含真實 RTSP/麥克風擷取、不含 E2E walkthrough**。用 bun 起(`cd v4 && bun install && bun run setup:backend && bun run migrate && bun start`)。
- **`d44e250`** README 換成 **v4 失能評估提案**(冰箱作為量表)。新增「共享偏好與基準線層」(非第 4 個代理人)。內含書審四項計分對照:問題定義 35% / 技術實作 30% / 成果展示 20% / **開源品質 15%**,並自述 **repo 目前缺 LICENSE 與完整 README**,該項未解決。第 08 節有待決議事項。

## Next (resume here)

1. `git fetch && git switch -c <新分支> origin/main`。
2. 決定新分支的主體是 `v4/` 骨架還是既有扁平 `backend/` —— 書審看規格對應,`v4/` 佔優,但它一行真實 model 呼叫都沒有。
3. 依上面「值得挑到新分支的東西」清單挑檔案,**第 1 項(實測版 14)必做**,否則規格書與實測矛盾。
4. 補 P0 規格要求的 JSON repair 與 invalid model-call audit;目前仍是 parse/validation 失敗即回 invalid。
5. 收口 latency/backpressure:實際完成/跳過 window 的 persistence、`max_concurrency`/pending 上限與 v4 文件對齊。
6. 定案 `03` 的狀態機數值並跑 replay/E2E。
7. 補 **LICENSE 與 repo 根 README**(開源品質佔 15%,新 README 自己點名了這個缺口)。

## 實測結論(細節見本分支 `docs-implementation-v4/14`)

| 項目 | 結果 |
|---|---|
| 10 張影格順序與完整性 | **12/12** |
| 延遲 | 中位數 2,463ms / p90 3,423ms / max 8,889ms;**2/12 超過 5 秒窗口** |
| `json_object` | 12/12 可解析 |
| **音訊** | **完全不進模型**(token delta 0,含 60KB 亂碼也不報錯) |
| **`video_url`** | **0/6**,掉幀 |
| 免費 key | **只涵蓋 M3**,其他模型回 402 |
| 預設 UA | 403,且無 key / 假 key / 真 key 回應相同 —— 看起來像認證失敗但不是 |

## Commands

- `python3 scripts/probe_provider.py --key-file GMIAPI.txt --repeats 6` → 最後一次:frames 全過、audio FAIL、video 0/6 FAIL、UA FAIL(皆為預期)
- `python3 -m py_compile backend/*.py scripts/probe_provider.py` → OK
- `python -m pytest backend/tests` → **未執行**(本機無 pytest/pydantic,需請組員在他的環境跑)
- `cd v4 && bun run verify` → **未執行**(組員的骨架,本機未試)
- GMI API key 在 repo 根目錄 `GMIAPI.txt`,已被 `.gitignore` 忽略,**勿印出內容**

## Working tree (uncommitted)

clean(本 HANDOFF.md 為本次 commit 內容)。branch 與 `origin/codex/longcare-gmi-m3-flow` 同步於 `902b9bf`。

## Open questions / blockers

- **新分支主體要用哪一套**(`v4/` 骨架 vs 扁平 `backend/`)尚未定案 —— 見 Next 第 2 點。
- **Gemini 是否接進 pipeline 當音訊/ASR slot** 尚未定案。v4 `09` 的獨立管線設計支援這條路,model slot 指向另一 endpoint 即可,domain code 不變。
- 若之後要把 main 併進本分支:dry-run 顯示**唯一衝突是 `.gitignore`**(本分支那版含保住 `GMIAPI.txt` 的規則,別被覆蓋);`docs-implementation-v4/14` 會保留本分支的實測版。
- **`03` 的狀態機數值仍是「建議值,待確認」** —— 連續 2 段確認跌倒、confidence 門檻 0.5、confirmed 後 60 秒通知、喝水固定容量。產品決定,需使用者與組員定案。
- **基準心跳目前 15 秒**(`OBSERVATION_HEARTBEAT_SECONDS`),考慮 17% 窗口超時,可能要調整。成本影響:靜止時原本 0 次呼叫,現在最低每小時 240 次。
- 新提案 README 第 08 節有**待決議事項**,尚未確認。
- M3 免費期 **2026-08-24 至 2026-09-06** 到期(即書審當天),之後計費。
