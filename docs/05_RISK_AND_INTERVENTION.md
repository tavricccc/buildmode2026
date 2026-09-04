# 05 · Risk 與 Intervention

## 1. 決策分層

Risk Agent 回答「目前證據顯示的風險與不確定性為何」；Intervention Agent 回答「在 Policy Gateway 允許的範圍內，現在如何回應」。兩者不可合併，避免語言模型把不確定的風險描述直接變成外部行動。

產品互動上，Resident Interaction Agent 是 L2 以前的低侵入回應入口：它只能使用已核准的問題、頻率與 conversation window。~~模型可以自行決定何時連續追問或直接通知。~~ 連續追問、通知與升級仍須通過 cooldown、consent 與 Policy Gateway。

## 2. Risk Assessment 輸入

Risk 不只看單一 confidence，至少綜合：

- 事件嚴重訊號：impact、floor posture、呼救語意、異常聲音、長時間未恢復。
- 多模態一致性或衝突：影像、ASR、音效是否互相支持。
- 個人化脈絡：Active Watchlist、已確認風險因子、CarePlan 與近期事件。
- 時間序列：短時間重複、趨勢、baseline deviation、前後序列。
- 資料品質：缺 clip、時鐘偏差、裝置離線、樣本不足。
- 可逆性與後果：錯誤介入的打擾、漏報、通知延遲與使用者安全。

輸出至少包含 `level`、`uncertainty`、`reason_codes`、supporting/contradicting refs、建議路由與 `expires_at`。Risk Assessment 會過期，不可無限沿用。

## 3. L0–L4 介入等級

| 等級 | 名稱 | 行為 | 進入條件 | 退出／升級 |
|---|---|---|---|---|
| L0 | Ignore / Log | 只存檔與供後續分析 | 明顯正常或不相關 | 被新證據重新開啟才升級 |
| L1 | Observe | 縮短觀察窗口、提高追蹤頻率 | 低風險但值得留意 | 時窗結束、恢復正常或新證據 |
| L2 | Soft Prompt / Check-in | 語音、手機或畫面詢問是否安全 | 需要被照護者確認且通道可用 | 安全回覆關閉；無回覆可升 L3 |
| L3 | Caregiver Alert | 通知家屬／照護者並附證據摘要 | Risk 高或 L2 超時且政策允許 | ack、取消、超時升級或人工接手 |
| L4 | Emergency Protocol | 執行預先授權的緊急流程 | 所有 deterministic gate 通過 | 已接手、取消、解除或記錄失敗 |

## 4. L4 Safety Gate

L4 只能由確定性執行器依版本化 policy 判定。示例條件如下，實際值必須由場域負責人、照護者與適用規範定義：

1. 事件 subject、地點與通道身份已確認。
2. Risk reason codes 命中已核准的 L4 policy；不能只有自由文字理由。
3. 證據最低品質達標，或有明確的人工／裝置確認。
4. 預先授權仍有效，且 consent scope 覆蓋此行動與聯絡對象。
5. L2/L3 確認流程依政策完成，或政策明確允許的無法回應條件成立。
6. cooldown、重複事件與目前 active intervention 檢查通過。
7. 建立 audit record，含 policy version、gate inputs、decision、執行器版本與取消方式。

LLM 可以建議「需要升級」與提供證據摘要，但不能直接發送 L4、修改 gate、繞過授權或擴大通知對象。

## 5. Intervention 狀態

建議狀態：`proposed → policy_pending → approved → dispatched → acknowledged / no_response / cancelled / expired → resolved`。L4 另需 `emergency_ready → emergency_active`，兩者之間不可自動省略 gate。

所有狀態變更都要有 actor、timestamp、reason、channel、recipient、correlation_id；同一 `intervention_key` 重送時必須回傳既有結果，而非再發送一次。

## 6. 通知內容

通知以可行動、可核查為原則：事件時間、位置、已觀察到的訊號、資料品質、模型信心、目前狀態、建議回覆方式與下一個 timeout。不要把「疑似跌倒」包裝成確診，也不要只傳送沒有證據引用的風險分數。

## 7. 安全測試案例

| 案例 | 預期結果 |
|---|---|
| 高 confidence 但沒有有效 evidence ref | 阻擋 L2 以上，建立資料品質錯誤 |
| LLM 輸出要求直接呼叫緊急服務 | Tool policy 拒絕，轉 Policy Gateway |
| 同一事件重送三次 | 一次介入、三筆 delivery audit 或一筆去重結果 |
| 照護者在 L3 前取消 | 狀態為 cancelled，不再自動升級，除非新事件符合 policy |
| L2 無回應但未授權 L3 | 保持 expired/人工隊列，不自行通知 |
| agent_suggested watchlist 要求 L4 | 保持 candidate，要求人工／政策審核 |

模型路由與 Risk 的交界見 [07_MODEL_ROUTING_AND_RUNTIME.md](07_MODEL_ROUTING_AND_RUNTIME.md)。
