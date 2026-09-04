# 09 · Deployment 與 Security

## 1. 部署目標

Demo 先支援單機本地優先運作；產品化需把感測、推論、記憶、通知與管理面分區。任何會產生外部行動的元件，都要在 Policy Gateway 後方並可獨立稽核。

## 2. 建議拓撲

| Zone | 元件 | 可連線對象 | 主要安全邊界 |
|---|---|---|---|
| Sensor zone | Camera、Mic、Wearable gateway、Frigate | 僅 Event Gateway、必要的本地管理面 | 不可直接連外部 LLM 或通知服務 |
| Edge inference zone | Event Gateway、Bus、ASR、Audio、VLM、Router | Sensor、Ledger、有限的 context API | 本地處理、隊列隔離、資源限制 |
| Data zone | Object Store、Event Ledger、Context Store、Audit Store | 具 scope 的 Agent API | 加密、版本化、TTL、不可任意覆寫 |
| Control zone | Agent Runtime、Policy Gateway、Scheduler、Consolidation | Data zone、模型 runtime、通知 adapter | 最小權限、schema gate、審計 |
| Care channel zone | App、SMS／推播／電話 adapter、照護者入口 | 只接收 Policy Gateway 核准的 command | recipient allowlist、delivery audit |
| Admin zone | 管理、標註、政策審核與維運 | 透過 RBAC 的管理 API | MFA、操作審計、不可直接改 Ledger |

## 3. 身份與權限

採 subject、tenant／場域、role、purpose、resource scope 的組合授權。建議角色包括被照護者、家屬、照護者、臨床審核者、標註者、維運者與系統服務帳號。服務帳號只能取得所需資料與工具；強模型 worker 不得取得通知、政策寫入或原始健康資料的權限。

所有請求驗證：身份、scope、目的、資料有效期與 correlation ID。權限變更、政策變更、同意撤回、人工確認與 L4 gate 都要寫入 Audit Store。

## 4. 資料保護

- 傳輸使用加密連線；儲存中的影片、音訊、健康資料與 token 以分層金鑰保護。
- Raw Evidence 使用短 TTL 與明確 retention class；Ledger 與 audit 的保存期限分開定義。
- 出站到強模型前做 pseudonymization／脫敏，只送必要窗口、摘要與 evidence reference。
- 下載、播放、匯出、刪除與重新識別均需審計；UI 不因方便而暴露全量影音。
- 備份也要繼承同意、保留與刪除策略；撤回不可只刪主資料而留下可還原副本。

## 5. Policy 與 L4 執行器

Policy 設定以版本化、可測試、可回滾格式保存，至少包含：適用場域、subject scope、觸發 reason codes、證據品質、確認流程、cooldown、聯絡對象、timeout、允許 level、有效期與審核者。

L4 executor 不解析自然語言來判定政策，只接受已驗證的 policy decision。執行前再次檢查 consent、policy version、recipient、active intervention、gate inputs 與時間有效性；所有結果寫入 immutable audit event。

## 6. 可靠性與復原

- Event Gateway 有本地 spool；Bus 有重試、dead-letter 與 dedup。
- Ledger 寫入失敗時，禁止 L3/L4 外部通知；保留待處理狀態。
- Notification adapter 要有 delivery、ack、timeout、cancel、expired、escalated 狀態。
- Router、Model Runtime、外部 connector 都要有 timeout、circuit breaker 與 degraded mode。
- 恢復後以事件時間與優先級補送，不直接補發已過期的介入。
- 每次 schema／model／policy 升級前做 replay、權限、資料留存與安全回歸測試。

## 7. 可觀測性

應監控事件延遲、模態缺失率、模型錯誤率、route 分布、強模型升級率、風險與介入轉換、通知 ack/timeout、重複介入、資料同步延遲、GPU/CPU 使用率與 retention job 結果。Log 不應包含未必要的原始語音、影像或健康欄位。

## 8. 威脅與對策

| 威脅 | 對策 |
|---|---|
| prompt injection／惡意語音指令 | ASR 內容只是 evidence；工具與政策權限獨立，所有行動走 gate |
| 偽造 sensor payload | source authentication、payload schema、時間／hash 驗證、異常來源標記 |
| 模型幻覺或越權 | evidence required、schema validation、scope sandbox、human review |
| 重複事件造成重複通知 | event dedup、intervention idempotency key、cooldown |
| 健康資料過度暴露 | context minimization、field-level scope、出站脫敏與 audit |
| 管理者誤改緊急規則 | 雙人審核、版本化、回滾、變更審計與生效延遲 |

安全邊界與介入條件的行為規格見 [05_RISK_AND_INTERVENTION.md](05_RISK_AND_INTERVENTION.md)。

