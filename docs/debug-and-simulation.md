# Debug Mode 與模擬資料系統

> 狀態：Debug runtime、資料產生器與 Replay lifecycle 已落地；完整 Evaluation provider 驗證仍需另行執行。

## 模式與隔離

正式與除錯環境使用不同啟動入口：

```bash
bun start
bun run debug
bun run debug:seed --days 45 --profile gradual-decline --seed 20260906
bun run debug:stream --profile mixed --seed 20260906
```

Debug mode 使用獨立目錄：

```text
data/debug/
├── care.sqlite3
├── clips/
├── logs/
└── generated-scenarios/
```

隔離規則：

- Production 不註冊 `/api/debug/*`。
- Debug 資料都帶 `simulation_id`、`seed` 與 `generated=true`。
- Debug 預設使用 stub Provider，不得向正式 Telegram recipient 發送通知。
- Debug 介面常駐顯示「模擬資料」，不得只靠顏色區分。
- Production database 不讀取或匯入 Debug database。

## 歷史資料產生器

`debug:seed` 可產生 1–90 天資料，預設 45 天。支援穩定、逐步下降、事件密集與混合 profile。

產生器建立彼此一致的底層資料：健康量測、飲水 session、活動與姿勢 observation、跌倒事件、Pipeline runs、model calls、analyses、actions、來源中斷與模型失敗。

產生器不能只寫 `daily_summaries`。每一天完成後，應呼叫正式 Observer 彙總路徑產生 daily summary、7/30 日 baseline 與 Observer run，才能驗證真實聚合邏輯。

相同 seed、profile、開始日期與天數必須得到相同事件序列。重新執行同一 simulation 應拒絕重複寫入，或要求使用明確的 `--replace-simulation`；不得靜默污染既有資料。

## 即時隨機串流

`debug:stream` 持續產生正常生活視窗，依 profile 與 seed 插入事件。最小事件集合：

- 正常活動、無人、休息、飲水。
- 飲水不足、活動量下降、異常姿勢維持。
- 疑似跌倒、確認跌倒、恢復與解除。
- L1 stale/unavailable。
- 影像中斷與恢復。
- L2 timeout、invalid schema、repair success/failure。
- L3 high/critical、contradicts L2、timeout、text-only degradation。
- Policy 授權、抑制、通知設定不足與 delivery failure。

事件機率、時間倍率與資料更新頻率可設定。預設不得快到讓 queue 永久堆積；壓力測試另用明確的 `--stress`。

## 手動情境

Debug UI 可選擇情境、持續時間、風險等級及下一狀態。手動情境不能直接任意修改資料表，必須經過 Debug service 建立具名 simulation run。

API 規劃：

```text
GET  /api/debug/scenarios
POST /api/debug/history/generate
POST /api/debug/stream/start
POST /api/debug/stream/stop
POST /api/debug/scenarios/trigger
GET  /api/debug/simulations/{simulation_id}
```

## Contract 與 Evaluation

每個情境都可選兩種模式。

### Contract mode

情境帶有已知 observation、預期狀態轉移與 Policy 結果。Stub 依合約回傳結構化輸出，用來驗證下游狀態機、介入建議、通知降級、UI 與稽核紀錄。

Contract mode 的成功代表系統按既定契約運作，不代表模型能從原始影像辨識該事件。

### Evaluation mode

模型只收到模擬證據與目前事件脈絡，不收到預期答案。執行後以 scenario expectation 比對模型輸出，報告事件辨識、escalation、風險等級、禁止欄位、JSON schema、延遲、重試與降級結果。

Evaluation mode 不應因模型答錯而繞過正式 validator 或 Policy Gateway。

## 本機錄影播放完成

Replay source 使用 `starting`、`running`、`completed`、`stopped`、`failed` 五種 lifecycle。

FFmpeg exit code 0 代表 `completed`。播放完成後：

1. 不再建立新的分析 window。
2. 已進入 queue 的工作可以完成。
3. 最後一張預覽可保留，但標示「錄影播放完成」。
4. 不得使用最後一張畫面繼續推論現在的安全狀態。
5. 新來源啟動前清除舊 buffer、starved 狀態與來源識別。

非零 exit code 才是 `failed`。後端保留有限長度的 FFmpeg stderr，經遮蔽後提供診斷；正常 EOF 不寫成 error。

## 瀏覽器影片上傳

上傳影片使用 `/ws/media?mode=demo_upload&event_start_ms=<unix milliseconds>`。後端先把分片寫入 `data/uploads/incoming/`，完成後轉成 H.264 480p（若有音訊則轉成 mono 16 kHz AAC），再以 `ReplaySource(realtime=true)` 送入正式 Cascade。`event_start_ms` 定義影片第一幀的歷史時間，影片內第 N 秒的事件會記錄在這個時間加 N 秒。上傳檔案不會直接把原始 bytes 當成另一種模型輸入；它只是取得與瀏覽器攝影機相同的 `FramePacket`／來源介面。

## 驗收條件

1. Debug 與 Production 使用不同 SQLite、clips 與 logs。
2. Production 對所有 `/api/debug/*` 回傳 404。
3. 45 天資料能形成可用的 7/30 日 baseline。
4. 同一 seed 可重現同一事件序列。
5. Contract mode 能驗證完整 downstream，Evaluation mode 不洩漏預期答案。
6. 正常錄影 EOF 後不再新增失敗 run，也不顯示來源錯誤。
7. 壞檔案或 FFmpeg 非零結束會顯示可理解的 decode failure。
