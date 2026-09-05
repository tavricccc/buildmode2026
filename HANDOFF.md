# HANDOFF — Care Agent v5 實作(2026-09-05)

_Branch: `feat/v5-three-layer-cascade`(base `origin/main` @ `fb065cd`)· 尚未 push_

## 這個分支做了什麼

依 `docs-implementation-v5/` 從頭實作 v5 的三層 cascade。**全新 `v5/` 目錄，沒有從舊分支挑任何檔案**(使用者指示「全部重寫」)。

`v4/` 骨架與舊分支的扁平 `backend/` 都原封不動保留,沒有動到。

## 交付狀態

`bun run verify` → **122 tests OK** + frontend typecheck 乾淨 + ffmpeg found。

| 層 | 狀態 |
|---|---|
| L1 person gate | ✅ 三種 detector(stub / motion / yolo11n),hysteresis、stale、fail-open 全部有測試 |
| L2 Gemini | ✅ 原生 REST(inline_data + Files API + ACTIVE poll)、一次 repair、offline stub |
| L3 MiniMax | ✅ OpenAI-compatible、frames wire format、degraded text-only、失敗不阻塞 |
| 狀態機 | ✅ fall / hydration 純函式 |
| Policy Gateway | ✅ 模型只能建議,不能指定通道或收件人 |
| SQLite | ✅ 含 v5 新增的 `pipeline_runs` |
| REST + WebSocket | ✅ 純標準庫,自己實作 RFC 6455 |
| Dashboard / Setup / Settings | ✅ React+TS,三層 panel、cascade trace、write-only secret |
| Telegram | ✅ allowlist、opaque single-use token、acknowledged / false_alarm / failed |
| Observer | ✅ 日彙總 + 7/30 日 baseline,只在超過門檻才花 L3,且只送 aggregate |
| Capability probes | ✅ Gemini 與 MiniMax 各一支 |

## 實測(對真實 provider)

**MiniMax M3 / GMI Cloud:probe 8/8 全過。** 細節見 `v5/docs/MEASURED_CAPABILITIES.md`。

關鍵兩點:
- **影格真的進到模型** —— prompt tokens 帶影格 1,594 vs 純文字 584(delta 1,010),外加 text part 的 canary 被正確回述,證明影片與文字在同一個 request 裡都活著。
- **真跑一次 fall replay 時,M3 主動反駁了 stub L2** —— `supports_l2=false`、confidence 0.2,正確指出 fixture 的影格是空白的,還推測「L1/L2 看到的畫面與送到 L3 的影格可能不一致」。這正是 escalation 層存在的理由。
- 過程中遇到一次真實 `rate_limited`,pipeline 照常運作(v5 00 item 9 得到真實驗證)。

**Gemini 尚未實測** —— 本機沒有 Gemini key。`bun run probe:gemini -- --key-file <path>` 就能跑。v5 01 明講音訊能力不可未測即假設,probe 裡有一項專門用 440 Hz 測試音去問。

## 怎麼跑

```bash
cd v5
bun install && bun run migrate && bun start
# 需要 Python 3.11+ / bun / ffmpeg。不需要 pip install、不需要 venv、不下載任何模型。
bun start -- --source fall     # 或 empty_room / hydration / l1_false_negative
bun run verify
```

沒有 API key 時,兩個 model slot 自動退回 offline stub —— stub 複製的是 provider 的**契約**不是品質,所以 schema 驗證、repair、狀態機、escalation、稽核全部照跑。

## 開發過程中被測試抓出來的三個真 bug

1. **gate 冷啟動預設「無人」** —— 第一筆健康 reading 就能授權 skip,完全繞過離開遲滯。改成冷啟動假設「有人」。
2. **每個 HTTP 連線洩漏一個 SQLite handle** —— ThreadingHTTPServer 一連線一 thread,而 Database 一 thread 一連線。
3. **`shutdown()` 沒有關掉 listening socket** —— 會讓立即重啟撞 EADDRINUSE。

另外跑起來才發現:source 停掉後 gate 讀數變 stale → fail-open → L2 對空 buffer 開工,原本被記成 L2 失敗,會讓 Dashboard 把「來源斷線」顯示成「模型有問題」。已改成不記錄該窗口,改由 source starvation 回報。

## Next

1. **拿 Gemini key 跑 `bun run probe:gemini`**,把結果補進 `v5/docs/MEASURED_CAPABILITIES.md`。這是目前唯一未實測的 provider 假設。
2. **決定要不要 push** `feat/v5-three-layer-cascade`(目前只在本機)。
3. **LICENSE 與 repo 根 README** 仍缺(書審「開源品質」佔 15%,`origin/main` 的新提案 README 自己點名了這個缺口)。選哪個 license 是你的決定,我沒有代選。
4. `03` 的狀態機數值仍是建議值:確認 2 段、confidence 0.5、confirmed 後 60 秒、喝水固定容量。目前全部在 `v5/backend/domain/policy.py` 一處,且可從 Settings 改並 rollback。
5. YOLO11n detector 需要 `onnxruntime` 與權重,Setup 目前不會自動抓。
6. 音訊/ASR 路徑:transcript 的儲存與 TTL 都在了,但沒有接上 ASR engine。

## 注意

- GMI API key 在 repo 根 `GMIAPI.txt`,已被 `.gitignore` 忽略,**勿印出內容**。
- M3 免費期到 **2026-09-06**(書審當天),之後計費。
- `v5/data/` 的 sqlite、clips、secrets.json 都已進 `.gitignore`。
