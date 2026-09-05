# 測試驗收、回放測試與完成定義 (Verification & Testing)

本文件說明 Care Agent 的系統檢驗工具、內建重播情境（Replay Scenarios）與 14 項專案完成定義（Definition of Done, DoD）。

---

## 1. 系統自動化驗證工具

在根目錄或 `src/` 目錄執行內建驗證指令：

```bash
cd src

# 執行語法編譯、單元測試、前端型別檢查與相依性檢查
bun run verify
```

`bun run verify` 依序執行四大檢查關卡：
1. **Python 語法與字節碼編譯檢驗**：`python -m compileall -q backend`，確保無語法損毀。
2. **後端單元與整合測試套件**：`python -m unittest discover -s backend/tests -t .`，涵蓋狀態機躍遷、策略閘道、L1 存在判讀、資料表結構等 11 組測試模組。
3. **前端 TypeScript 型別安全檢查**：在 `src/frontend` 執行 `bun run typecheck`。
4. **媒體工具鏈存在檢驗**：確認系統 PATH 中包含有效之 `ffmpeg` 執行檔。

---

## 2. 內建回放測試情境 (Replay Scenarios)

專案內建預製的結構化事件序列（位於 `src/data/replays/`），用於在無實體攝影機環境下進行 100% 可重現之邏輯驗收：

| 情境檔案 | 模擬情境 | 驗證重點 |
| --- | --- | --- |
| `empty_room.json` | 客廳空房無人時段 | 驗證 L1 正確輸出 `no_person`，常規推論大量被略過，但週期性稀疏心跳（Heartbeat）仍能正常發起 |
| `hydration.json` | 長輩至飲水機倒水並飲用 | 驗證 `HydrationStateMachine` 流轉歷程，確保僅有完整飲用結束才計入每日總量，避免拿起水杯即誤算 |
| `l1_false_negative.json` | 偵測器訊號異常或延遲 | 驗證系統正確轉為 `stale`/`unavailable`，並依 **Fail-Open 原則**放行至 L2 巡檢 |
| `fall.json` | 長輩步態不穩滑倒倒地 | 驗證 `FallStateMachine` 進入 `suspect` 後強制繞過 L1，發起密集追蹤並觸發 L3 MiniMax 深度覆核 |

### 執行單一情境之端到端級聯測試
可透過設定介面或直接發送 API：
```bash
curl -X POST http://127.0.0.1:8200/api/pipeline/cascade-test \
  -H "Content-Type: application/json" \
  -d '{"scenario": "fall"}'
```

---

## 3. 專案完成定義 (Definition of Done, DoD)

系統開發與審查嚴格依循以下 14 項可量測之驗收標準：

1. **零權重開箱**：在全新環境執行 `bun start`，無需預先下載數 GB 深度學習權重即可開啟 Setup 設定分頁。
2. **動態配置能力**：可於 Web 設定中選擇或更換 L1 偵測器與 L2/L3 Provider；目前建議組合為 Gemini 及 MiniMax。
3. **L1 省流驗證**：在 `no_person` 空房情境下，絕大多數常規視窗被略過，儀表板可清晰看見 `skipped_by_l1` 計數累積。
4. **稀疏安全心跳**：空房時仍會按照預設週期發起一次目前選定 L2 Provider 的巡檢。
5. **Fail-Open 斷言**：當 L1 偵測器離線、拋出例外或訊號過期時，系統自動放行，絕不將異常視為安全空房。
6. **合約保證之語意觀察**：畫面有人時，5–10 秒短影音可成功送入目前選定的 L2 Provider 並獲得合法符合 Schema 之 `GeminiObservation`。
7. **按需升級覆核**：僅在 L2 要求 `escalation.required` 或處於高風險狀態時，才建立目前選定的 L3 任務。
8. **高風險狀態繞過 L1**：當跌倒進入 `suspect` 或 `confirmed` 時，不受 L1 略過規則抑制，持續追蹤直到狀態解除。
9. **異常隔離與彈性**：所選 L3 Provider 遭遇超時或 429 速率限制時，主管線、狀態機、資料庫與儀表板持續正常運作。
10. **全鏈路可追溯性**：每個時間視窗皆可在 SQLite 反查 L1 決策、所選 L2/L3 Provider 呼叫代碼、延遲與影音證據檔案引用。
11. **狀態機去重與冪等**：重播跌倒或飲水資料流時，狀態序列精確可重現，重送不重複累計事件次數。
12. **通報與排程閉環**：Telegram 告警確認、Observer 每日基準線比對、設定版本 Rollback 皆能端到端完成驗證。
13. **零金鑰外洩保證**：API Key 絕不出現在前端 Bundle、GET 回應、系統日誌、SQLite 原始資料表或 Git 儲存庫中。
14. **跨平台開發相容**：系統可在 Windows 11 (原生及 WSL2)、macOS 與 Linux 正常開發與執行驗證。
