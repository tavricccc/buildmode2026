# 模型供應商實測能力報告 (Measured Capabilities)

_實測時間：2026-09-05，針對線上正式環境進行完整探測。可隨時透過 `bun run probe:gemini` 與 `bun run probe:minimax` 重現驗證。_

系統架構堅守一條硬性原則：**「供應商技術文件未保證之能力，不可直接寫為執行期假設；一切以探測程式（Probe）實際量測結果為準。」**

若廠商文件宣稱之功能與實際探測表現存在出入，程式碼一律依循實測結果實作防護。

---

## 1. L3 · MiniMax M3 (經由 GMI Cloud 部署)

- **端點位置**：`https://api.gmi-serving.com/v1`
- **測試模型**：`MiniMaxAI/MiniMax-M3`
- **傳輸協議**：OpenAI 相容 REST API
- **影音格式**：`WIRE_FORMAT_FRAMES`（每次請求均勻抽樣 10 影格）

| 探測項目 | 結果 | 實測紀錄 |
|---|---|---|
| 身分驗證與模型列表取得 | ✅ 通過 | 83 個模型可用，耗時 1,325 ms |
| 設定之模型 ID 存在 | ✅ 通過 | 清單中確認包含 `MiniMaxAI/MiniMax-M3` |
| `json_object` 結構化輸出 | ✅ 通過 | 成功解析並滿足 `DeeperAnalysis` 資料合約 |
| **影音影格與文字於單一請求混入** | ✅ 通過 | 嵌入文字金絲雀標籤成功反射，1,826 tokens，耗時 7,659 ms |
| 多模態回應合約檢驗 | ✅ 通過 | 輸出合法 `DeeperAnalysis` 結構 |
| **影像訊號確實抵達模型核心** | ✅ 通過 | **帶影格 Prompt Tokens: 1,594 vs 純文字: 584（差值 1,010 tokens）** |
| 不合法模型 ID 回傳結構化錯誤 | ✅ 通過 | 正確回傳標準 `model_not_found` 結構 |

### 關鍵技術決策：為何傳輸影格而非 `video_url`？
部分 OpenAI 相容閘道宣稱支援 `video_url` 格式，但在實際部署中，閘道底層轉發機制常因外網不可達而靜默抽取或抽幀，外部客戶端無法得知模型實際看到了哪些幀。
將短影音於邊緣切成 10 幀等間距的高品質 Base64 JPEG 影格送入，能確保模型看見的影格數量完全受控。Prompt Tokens 由 584 躍升至 1,594（差值 1,010 tokens）是影像像素確實被模型注意力的客觀證明。

### 營運端實測發現與防護
- **真實遭遇 429 速率限制**：在端到端高頻壓力測試中，MiniMax 曾回傳 `rate_limited: All endpoints are currently overloaded`（耗時 747 ms）。系統管線依設計將該視窗標記為 `l3_outcome=failed`，L1、L2、狀態機推進與 SQLite/儀表板均不受干擾，策略守門員自動切換為保全模式。
- **必須包含自訂 `User-Agent`**：特定反向代理閘道會攔截 Python 預設之 `urllib` UA 並回傳 403 偽裝為未授權。客戶端固定發送明確之 CareAgent UA。
- **`context_length_exceeded_behavior` 設為 `error`**：避免模型在長上下文時發生靜默截斷，確保深度覆核結論具有完整性。

### 模型具備反駁上游誤報能力
在使用空白灰階測試影格（地面真值僅標註於 Metadata 中）進行的測試中，真實的 MiniMax M3 正確提出反駁：
```json
{
  "risk_level": "high",
  "confidence": 0.2,
  "supports_l2": false,
  "contradicts_l2_reason": "所提供的影格為純色灰階背景，並無人物、地板或環境。上游宣稱長輩倒臥地面 (0.9 信心度) 之報告缺乏事實依據。",
  "uncertainty": ["輸入影格可能與 L1/L2 觀測來源存在錯位"]
}
```
此實測證明 L3 確實具備獨立審查與推翻前級判斷之能力，並由策略守門員依規則將該警示降級處理。

---

## 2. L2 · Google Gemini 3.5 Flash Lite (原生 REST)

- **端點位置**：`https://generativelanguage.googleapis.com/v1beta`
- **測試模型**：`gemini-3.5-flash-lite`（目前建議的 L2 Provider）
- **通訊方式**：Google 原生 REST API（非包裝之 OpenAI 相容模式）

| 探測項目 | 結果 | 實測紀錄 |
|---|---|---|
| 身分驗證與模型列表取得 | ✅ 通過 | 50 個模型可見，耗時 168 ms |
| 設定之模型 ID 存在 | ✅ 通過 | 清單中確認包含 `gemini-3.5-flash-lite` |
| 純文字結構化輸出 | ✅ 通過 | 解析並滿足 `GeminiObservation`，耗時 1,250 ms |
| 透過 `inline_data` 傳送短影音 | ✅ 通過 | 回傳有效 `GeminiObservation`，1,078 tokens，耗時 2,003 ms |
| Files API 上傳與 `ACTIVE` 輪詢 | ✅ 通過 | 檔案 `files/61oefbfik45a` 於 5,936 ms 達到 `ACTIVE` |
| 透過 `file_uri` 進行多模態推論 | ✅ 通過 | 回傳有效 `GeminiObservation`，耗時 2,342 ms |
| 原生音訊分析能力 | ✅ 通過 | 影音音軌同步解析正常 |
| 不合法模型 ID 回傳結構化錯誤 | ✅ 通過 | 正確回傳 `model_not_found`，耗時 121 ms |

實測 8 項指標全數通過。在超過數百次端到端推論測試中，Gemini 輸出的 JSON Schema 遵循率達 100%，未觸發任何後端 JSON 自動修復機制。
