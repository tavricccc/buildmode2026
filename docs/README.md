# Care Agent 技術文件庫

歡迎查閱 Care Agent（居家長照連續觀測與失能評估輔助系統）技術文件。本目錄為儲存庫唯一權威規格來源。

文件架構參照 **Diátaxis 框架**，區分為「快速入門（Tutorials）」、「操作指南（How-To）」、「架構解析（Explanation）」與「技術規格（Reference）」四個維度，協助開發者、評審與維護者快速定位資訊。

---

## 文件導覽

```text
docs/
├── README.md                  # 文件庫首頁與導覽（本文件）
│
├── [入門與操作指南]
│   ├── getting-started.md     # 系統安裝、環境配置、WSL/Linux 支援與 Setup 精靈
│   └── verification-and-testing.md # 驗證指令、重播測試情境與 14 項 Definition of Done (DoD)
│
├── [架構與設計原理]
│   ├── architecture.md        # 系統三層級聯、確定性狀態機與策略守門員架構
│   ├── pipeline.md            # 影像音訊管線、環形緩衝區、L1-L3 調度與背壓機制
│   ├── data-and-policy.md     # SQLite 資料模型、稽核足跡 (pipeline_runs) 與隱私防線
│   ├── caregiver-intervention-workflow.md # 長照端介入建議與狀態呈現（規劃中）
│   ├── operator-console.md     # Production 唯讀運作監看與 Debug 控制邊界（規劃中）
│   └── debug-and-simulation.md # Debug runtime、資料產生器與 Replay EOF（規劃中）
│
└── [規格與實測參考]
    ├── api-reference.md       # REST API 端點、WebSocket 事件協定與 JSON 資料結構
    └── measured-capabilities.md # 雙模型實測基準（Gemini 3.5 Flash Lite 與 MiniMax M3 實測數據）
```

---

## 文件對照與分類

| 分類 | 文件名稱 | 說明 | 適用對象 |
| --- | --- | --- | --- |
| **Tutorials** | [快速安裝與執行指南](getting-started.md) | 從零開始安裝相依、初始化資料庫並啟動 Setup 設定分頁 | 新手、初次建置者 |
| **How-To** | [測試驗收與情境回放](verification-and-testing.md) | 執行驗證套件、回放測試情境（跌倒、飲水、空房）與查驗 DoD | 開發者、CI、評選書審 |
| **Explanation** | [核心架構與設計原則](architecture.md) | 三層成本最佳化、Fail-open 機制、狀態機與確定性策略閘道 | 系統架構師、研究人員 |
| **Explanation** | [三層事件管線 (Pipeline)](pipeline.md) | RTSP 影音切片、L1 存在過濾、L2 常規分析與 L3 深度升級細節 | 演算法工程師 |
| **Explanation** | [資料模型、策略與隱私防線](data-and-policy.md) | SQLite 綱要、視窗可追溯性稽核與邊緣隱私隔離設計 | 後端工程師、資料工程師 |
| **Explanation** | [長照端介入建議與狀態呈現](caregiver-intervention-workflow.md) | 照護狀態、介入建議、Policy 與通知狀態的產品契約（規劃中） | 產品、前端、長照端 |
| **Explanation** | [運作監看與系統稽核頁](operator-console.md) | Production 唯讀監看、Debug 控制與逐步 Trace（規劃中） | 維運、開發者 |
| **How-To** | [Debug Mode 與模擬資料系統](debug-and-simulation.md) | 歷史回填、即時隨機事件、手動情境與 Replay EOF（規劃中） | 開發者、測試者 |
| **Reference** | [API 與 WebSocket 規格參考](api-reference.md) | 完整 REST API、WebSocket 即時串流格式與結構化 Payload | 前端開發者、系統整合者 |
| **Reference** | [模型能力實測報告](measured-capabilities.md) | 推薦雲端組合 Gemini 與 MiniMax M3 的多模態能力實測結果 | AI 工程師、評審委員 |

---

## 核心設計約束（不變原則）

1. **偵測器故障絕不等於空房**：L1 存在閘道採四值邏輯（`person_present`、`no_person`、`stale`、`unavailable`）。唯有新鮮且健全的 `no_person` 允許略過模型推論；超時或故障一律 fail-open，寧可耗費推論成本，不可忽視安全。
2. **模型負責提供觀測證據，確定性策略負責行動**：大語言與多模態模型不具備直接對外發送通知或調整門檻的權限。所有警報必須經由確定性狀態機確認與策略守門員（Policy Gateway）核准。
3. **全鏈路視窗皆可事後回溯**：每個被處理或略過的時間視窗，皆在 `pipeline_runs` 留存模型版本、決策代碼、延遲與短影音引用，支援端到端稽核。
4. **極簡環境依賴**：後端堅持僅依賴 Python 3.11+ 原生標準庫，啟動無需下載數 GB 模型權重，確保在任何標準開發環境皆能即開即測。
