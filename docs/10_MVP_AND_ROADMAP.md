# 10 · MVP 與 Roadmap

## 1. 交付策略

先交付可 replay、可觀測、只做 L0–L2 的事件閉環，再逐步加入照護者通知、個人化 baseline 與政策審核。L4 不列入黑客松 Demo 的自動執行範圍，除非已有明確場域政策、預先授權、測試環境與獨立安全審查。

## 2. Phase 0：文件與契約基線

目標是讓團隊先對責任與資料語意一致：

- 定義 Event、Evidence、Observation、Interpretation、Risk、Intervention、Hypothesis、Watchlist schema v1。
- 定義事件 ID、correlation ID、dedup key、provenance 與版本規則。
- 建立政策版本格式與 L0–L4 狀態表；明確標記未實作的 gate。
- 準備 replay dataset、人工標註格式與最小資料品質欄位。

完成條件：文件可被工程、照護與安全角色共同 review，且任何 record 能描述來源與狀態。

## 3. Phase 1：黑客松可演示閉環

範圍：單一住民、單一場域、少數事件類型（例如 impact、floor posture、scream/yell、夜間離床）。

實作順序：

1. Frigate event ingest 與本地證據索引。
2. Event Gateway、SQLite／簡易 Ledger、去重與 replay。
3. 本地 ASR、Video VLM、Audio Event Classification 的 stub 或可替換 adapter。
4. Multimodal Bundle 與 Event Understanding 輸出。
5. Risk Agent 只輸出 risk/uncertainty，不直接介入。
6. Policy Gateway + L0/L1/L2 check-in 模擬。
7. Demo UI 顯示證據、Observation、風險理由、route 與 intervention 狀態。

驗收案例：正常走動不打擾；影像與 impact 組合觸發 check-in；無回覆進人工隊列；同一事件重送不重複提示；模型失敗時顯示 degraded。

## 4. Phase 2：個人化與可觀測性

- 接入照護者設定與一個健康資料來源的受控同步。
- 建立 Context Normalizer、snapshot、Watchlist candidate 與審核介面。
- 建立 Long-term Observer 的夜間分析、baseline、frequency、trend 與 hypothesis。
- 建立模型 route、latency、cost、coverage、false positive／negative 的 dashboard 或匯出。
- 引入人工回饋，使 confirmed fact 與 hypothesis 有明確流程。

驗收條件：Observer 不會直接改 L4；資料不足時能顯示 insufficient_data；watchlist 變更有版本與審核者；背景工作不影響即時 queue。

## 5. Phase 3：照護者通知與政策治理

- 接入真實照護者 app／推播或其他核准 channel。
- 完成 L3 ack、timeout、cancel、handoff 與 escalation policy。
- 建立 policy editor、雙人審核、變更延遲、生效與 rollback。
- 進行權限、隱私、資料刪除、災難復原與 prompt injection 測試。

驗收條件：所有 L3 行動可追蹤 delivery 與 ack；政策變更可回溯；沒有 policy decision 就不能發通知。

## 6. Phase 4：受控 L4 評估

L4 僅在 sandbox、模擬通道或具體場域流程下評估：

- 由場域負責人定義觸發條件、預先授權、聯絡順序、人工確認與取消方式。
- 由 deterministic executor 執行，LLM 不具直接外呼／求助權限。
- 用 replay、故障注入、紅隊與人員演練驗證 false positive、false negative、延遲與錯誤恢復。
- 產出 go/no-go checklist；任何條件不滿足都退回 L3 或人工處理。

## 7. 開發優先順序

| 優先 | 工作 | 原因 |
|---|---|---|
| P0 | schema、Ledger、dedup、policy gate、replay | 沒有可重現與可審計基礎就無法安全擴展 |
| P1 | Frigate adapter、三支模態 adapter、Bundle、Risk | 建立核心事件價值 |
| P1 | L0–L2 UI 與人工回饋 | 先驗證使用者體驗與誤報成本 |
| P2 | Health context、baseline、Observer | 產生個人化與長期價值 |
| P2 | L3 通知與治理 | 需要可靠的 delivery 與權限管理 |
| P3 | L4 sandbox 評估 | 必須等政策、授權與安全驗證成熟 |

## 8. 未決定事項

- Frigate 事件 schema 與目前原型欄位的 mapping。
- 實際攝影機／麥克風／穿戴式型號、時鐘同步與斷線行為。
- 本地 ASR、VLM、Audio classifier 的硬體需求與可接受延遲。
- HealthKit／FHIR 的實際授權方、同步頻率與資料保存期限。
- 照護者角色、通知 channel、L3/L4 policy owner 與責任分工。
- 目標場域的適用法規、同意文字、資料刪除與事件保留政策。

## 9. 完成定義

本架構文件階段完成的判準：所有需求元件都有責任歸屬；文件間鏈接有效；資料層區分 Raw Evidence、Fact、Hypothesis；Risk 與 Intervention 分離；L4 有 deterministic gate；模型路由、錯誤、版本與 provenance 有可實作的欄位；每個 Phase 有可測試驗收條件。

相關實作原型：[care_agent_demo_frigate_vad_m3_sqlite.html](../care_agent_demo_frigate_vad_m3_sqlite.html)。

