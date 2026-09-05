# HANDOFF — Care Agent v5 Frontend（接手第 2 輪）

_Updated: 2026-09-05 22:27 · 5h usage: 15%（03:10 重置）· 7d: 61% · ctx: 16%_

Branch: `frontend` · Head: `67a5222` · Base: `origin/main` @ `ceea44a`

## Goal

接手上一輪的 `v5/frontend` 重構交付，把環境裝起來、對著真的後端驗證，並修掉驗證過程中找到的缺陷。

## 這一輪做了什麼

### 環境（已可直接使用）

- `bun install` — 上一輪的 `@phosphor-icons/react` 在 `package.json` 與 root `bun.lock` 裡，但沒裝，typecheck 4 檔失敗。
- **macOS Gatekeeper 擋住 bun 解壓的原生二進位檔**（rollup、esbuild）。來源標記是 Sourcetree，整個 checkout 底下新寫入的檔案都繼承 `com.apple.quarantine`。解法已寫進 `v5/README.md`：
  `xattr -dr com.apple.quarantine node_modules frontend/node_modules`
- GMI key（repo 根目錄 `GMIAPI.txt`，是 JWT，L3/MiniMax 用）已寫入 secret store `v5/data/secrets.json`（0600，已 gitignore）。
- `GMIAPI.txt` 原本**沒有**被 gitignore，違反 v5 00 DoD 13。已加規則。
- port 8000 被另一個 Python 服務（PID 62210，FastAPI 風格）占用，非 v5。測試改用 `CARE_PORT=8010`。

### 驗證（對真後端，不是 mock）

- `bun run verify` → Python compile、**124 tests**、frontend typecheck、ffmpeg 全過。
- `bun run build` → Vite production build 過。
- `bun run probe:minimax` → **8/8 通過**。83 models、`json_object` 結構化輸出、video+text 同一請求、
  **prompt tokens 帶 frames 1594 vs 純文字 584（delta 1010）**、bad model id 回 `model_not_found`。
  與 `v5/docs/MEASURED_CAPABILITIES.md` 既有數字一致。
- `CARE_PORT=8010 bun start -- --source fall` 實跑：
  - L1 `skipped_l1` 14 個 window（DoD 3 ✓）
  - `forced_high_risk` 繞過 L1 持續 follow-up（DoD 8 ✓）
  - escalation rate limit 生效（`escalation_rate_limited_8s/12s`）
  - **L3 打到真的 MiniMax M3**：latency 4149 ms / 5462 ms，`l3_error: null`
  - `l3_risk_level: none` — 與 MEASURED_CAPABILITIES 記載一致：replay fixture 的影格是空白灰底，真 M3 正確拒絕背書 stub L2 的高信心跌倒宣稱。
- 新 API 全部實測 200：`/api/observer/status`、`/api/observer/records`、`/api/statistics`、`/api/observer/run`、`/api/source/snapshot`（回 image/jpeg）。
- Secret scan：production bundle 只含 `GEMINI_API_KEY` / `MINIMAX_API_KEY` 這兩個**欄位名稱**（write-only API 需要），key 值 0 筆。DoD 13 ✓
- TS `types/api.ts` 與實際 payload 逐欄比對，無 drift。

### 修掉的缺陷（commit `67a5222`）

1. **靜默失敗**。Dashboard 用 `Promise.allSettled` 逐面板降級，其他頁面都是 `void` 包單一呼叫且沒有 catch → unhandled rejection、畫面毫無反應。
   - `/api/observer/run` 重疊時回 **409 `observer_busy`**（已實測重現），「立即分析」完全沒有回饋。
   - Statistics 讀取失敗時顯示「Observer 尚未完成第一次分析」——把「問不到」講成「沒事發生」。
   - Settings / Setup 後端不通時永遠停在「載入中…」。
   - Policy rollback 失敗無提示 → 照護者以為切到別的版本。
   - Cascade 測試失敗時，畫面留著**上一次成功**的 trace。
   - 新增 `errorText()` / `ErrorBanner`（`components/ui.tsx`）統一處理。
2. **Observer `failed` 被顯示成「需要注意」**——把基礎設施失敗當成住戶健康訊號。改為「分析未完成」。
3. **「重新連線」是死按鈕**：只要來源在跑就 enabled，但它重送表單的 target，重整或用 CLI 啟動後 target 是空的 → `start()` 靜默 return。
4. Snapshot poller 不論有沒有影格都每 2 秒跑；飲水進度條寫死 1500 ml（Settings 可改）。
5. **`styles.css` 的 Google Fonts `@import` 阻塞首次繪製**。上一輪 handoff 說「無網路時安全退回」——不成立，離線時是等 DNS timeout 才顯示畫面。改為 index.html 的非阻塞 `<link>`。三個 webfont 都沒有漢字，所以中文一直是靠 stack 後面的字體在顯示，其中 3 條宣告根本沒有 fallback。改成 `--font-ui` / `--font-display` / `--font-mono`，每條都以真的 CJK 字體收尾（PingFang TC / Noto Sans TC / Microsoft JhengHei）。
6. `<html lang>` 是 `en`，但 UI 全是繁體中文 → `zh-Hant`。

## Next（從這裡繼續）

1. **Gemini（L2）仍未量測** — 這台機器上沒有任何 Gemini key（secret store、環境變數、`gemini api test/.env` 都沒有）。拿到 key 後：
   ```bash
   cd v5 && bun run probe:gemini -- --key-file /path/to/key
   ```
   然後更新 `v5/docs/MEASURED_CAPABILITIES.md` 的「L2 · Gemini」段（目前標示 **Not yet measured**）。
   特別注意 native audio：v5 01 明講「一定理解音訊」不可未經量測寫成 runtime 假設。
   目前 `providers.l2.stub = true`、`active = "stub-l2"`，L2 latency 恆為 5 ms 就是 stub。
2. **前端沒有跑過瀏覽器實測** — 這一輪只做到 typecheck、build 與 API 契約比對。playwright MCP 這個 session 沒掛上，`.playwright-mcp/` 是上一輪留下的。建議下一輪掛上後逐頁截圖，特別是 1150px / 760px 兩個斷點。

## ⚠️ Blockers / 需要決定

- **`v5/node_modules` 有 3119 個檔案被 commit 進 git。** `.gitignore` 只排除了 `v5/frontend/node_modules/`，漏掉 workspace root。這是上一輪就存在的問題，不是這輪造成的。修法是 `git rm -r --cached v5/node_modules` 並補 ignore 規則，但那是一個 3119 檔案的刪除 commit，會影響 `codex/longcare-gmi-m3-flow` 與 `feat/v5-three-layer-cascade` 兩條分支，所以**沒有動，等你決定**。
- 這也是為什麼 `git status` 會看到兩個 untracked 的 `v5/node_modules/.bun/@phosphor-icons*`。

## Commands

```bash
cd v5
xattr -dr com.apple.quarantine node_modules frontend/node_modules   # macOS 首次
bun install && bun run migrate
bun run verify                      # ✅ 124 tests + typecheck + ffmpeg
bun run build                       # ✅ Vite production build
CARE_PORT=8010 bun start -- --source fall
bun run probe:minimax               # ✅ 8/8
bun run probe:gemini                # ❌ 尚無 key
```

## Working tree

`67a5222` 已 commit。未追蹤：`GMIAPI.txt`（已 ignore）、`v5/node_modules/.bun/@phosphor-icons*`（見上方 blocker）。
尚未 push — `origin/frontend` 還在 `ab5eec6`。
