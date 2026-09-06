# 三層事件管線 (Pipeline Specification)

Care Agent 採用「端邊協同、分級過濾、深度覆核」的視覺與音訊事件處理管線。本文件詳述各階段運作邏輯、容錯機制與資料流轉規則。

---

## 1. 媒體擷取與環形緩衝區 (Media Ingest)

```text
[RTSP 網路攝影機 / Replay 影音檔案]
           │
           ▼ (FFmpeg 子程序截流)
┌────────────────────────────────────────┐
│  有界環形緩衝區 (Bounded Ring Buffer)   │
│  - 僅留存最近 30-60 秒影音視窗          │
│  - 不維護完整 NVR，杜絕本機磁碟耗盡     │
└────────────────────────────────────────┘
```

- **來源相容性**：正式環境接收標準 H.264/H.265 RTSP 網路攝影機串流；離線與測試環境使用 `ReplaySource` 讀取 JSON/MP4 測試重播檔案。兩者在下游提供完全一致的影音切片合約。
- **滑動視窗切片**：當觸發推論時，由緩衝區迅速封裝 5–10 秒的 MP4 短影音片段供模型調閱。

---

## 2. L1 本地端存在閘道 (Person Gate)

L1 負責在邊緣端以極低功耗進行初步篩選，避免空房時無意義消耗昂貴的雲端多模態推論費用。

- **可選實作**：支援 `stub`、motion 與 YOLO11n `person` 類別偵測。新安裝時預設為 `stub`；實際部署可在 Settings 切換，YOLO11n 需要使用者準備 ONNX Runtime 與模型權重。
- **輸出資料契約**：
  ```python
  class L1Decision(Enum):
      person_present = "person_present"  # 確認有人
      no_person = "no_person"            # 確認無人
      stale = "stale"                    # 訊號過期
      unavailable = "unavailable"        # 偵測器異常
  ```
- **防漏失（Anti-False-Negative）關鍵機制**：
  1. **遲滯防抖 (Hysteresis & Debounce)**：人物進入畫面需維持連續若干幀，離開畫面需經過冷卻視窗，避免走動遮擋引發閃爍誤判。
  2. **稀疏安全心跳 (Safety Heartbeat)**：在連續無人的狀態下，系統仍會每隔 30–60 秒強制執行一次稀疏的 L2 巡檢，使用目前選定的 Provider 確保房間背景狀態健全。
  3. **失效保全 (Fail-Open)**：若 L1 程式崩潰或畫面卡死超過設定閥值，決策轉為 `stale` 或 `unavailable`，此時 `permits_skip()` 回傳 `False`，強制啟動 L2 檢查。
  4. **高風險狀態覆寫**：若跌倒狀態機已處於 `suspect` 或 `confirmed`，無論 L1 是否判斷有人，均**強制繞過 L1** 進行連續 L2 追蹤。

---

## 3. L2 常規語意觀測層 (推薦 Gemini / 可選本地 vLLM)

L2 為系統日常運作的核心多模態理解層。目前建議採用 Google 原生之 `gemini-3.5-flash-lite`；也可切換至本機 vLLM OpenAI-compatible endpoint。新安裝的 runtime 預設使用本機 vLLM，方便無雲端金鑰的環境啟動。

- **通訊方式**：
  - 選擇 Gemini 時呼叫原生 REST API（`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`）。
  - Gemini **<= 20MB**：直接將短影音轉換為 Base64 透過 `inline_data` 發送；**> 20MB** 時使用 Google Files API，輪詢狀態至 `ACTIVE` 後以 `file_data.file_uri` 提交。
  - 選擇本機 vLLM 時使用 OpenAI-compatible chat endpoint，送入取樣影格與可選的瀏覽器音訊資料。
- **結構化輸出 (GeminiObservation)**：
  要求模型輸出符合 JSON Schema 的觀測結構，包含：
  ```json
  {
    "person_visible": true,
    "fall_observation": {
      "suspected": false,
      "confidence": 0.0,
      "details": "長輩正常坐在沙發上看電視"
    },
    "hydration_observation": {
      "drinking_detected": true,
      "vessel_type": "mug",
      "confidence": 0.85
    },
    "escalation": {
      "required": false,
      "reason_codes": [],
      "requested_evidence_window_sec": 10
    }
  }
  ```
- **容錯與修復**：若模型輸出 JSON 格式瑕疵，後端會啟動 1 次格式修復嘗試；若依然失敗，標記該視窗為 `invalid_schema`，絕不將髒資料寫入狀態機。

---

## 4. L3 深度覆核審查層 (推薦 MiniMax / 可選本地 vLLM)

L3 扮演高階覆核專家，專門處理具有高度爭議或高風險的異常視窗。目前建議採用 GMI Cloud 託管之 `MiniMaxAI/MiniMax-M3`；也可切換至本機 vLLM。

- **觸發條件（非全時運作）**：
  1. L2 回傳 `escalation.required = true`；
  2. 跌倒狀態機進入 `confirmed` 或長照高風險狀態；
  3. 確定性策略規則要求二次多模態驗證；
  4. 操作員於儀表板發起手動深度分析。
- **證據封包 (Evidence Bundle)**：
  L3 審查時必須獲得第一手原始影音素材，不可僅依賴 L2 的二手文字摘要。使用 MiniMax 時封包內含：
  - **10 幀等間距取樣之影格序列**（採 `WIRE_FORMAT_FRAMES` 格式傳輸）；
  - L2 產出之觀測報告與升級原因代碼；
  - 當前狀態機狀態、時間戳記與可選之語音逐字稿上下文。
- **覆核合約 (DeeperAnalysis)**：
  MiniMax 可同意或反駁 L2。例如在實測中，當 L2 誤報跌倒而影格實為灰階測試圖片時，MiniMax 成功產出：
  `supports_l2: false, contradicts_l2_reason: "影格均為單色灰階無人物，上游跌倒判定無法被證實"`。
- **降級機制**：若短影音因硬體故障丟失，允許以降級之純文字脈絡請求 MiniMax，並於日誌標明 `degraded_text_only`。

---

## 5. 語音事件與逐字稿管線 (Audio & ASR)

- **可選音訊**：瀏覽器 WebM 的音訊可送入支援的本機模型與變化閘道；目前 RTSP 擷取路徑以影像分析為主。
- **ASR 隔離區**：逐字稿資料表與 TTL 已準備，但目前尚未接入 ASR 引擎；需要逐字稿時仍須另外接入 VAD/ASR 流程。

---

## 6. 佇列管理與背壓機制 (Queues & Backpressure)

為防止所選模型 Provider 的網路延遲累積導致記憶體暴增，後端為 L2 與 L3 各維護一個有界佇列：
- **佇列容量**：預設各為 `1 running + 1 pending` 視窗。
- **淘汰策略**：當新視窗抵達且佇列已滿時，普通的常規視窗允許被後續最新視窗覆蓋（丟舊留新）；但**包含跌倒疑慮等高風險視窗受系統保護，嚴禁被覆蓋丟棄**。
- **模型故障隔離**：
  - L2 逾時：標記視窗降級，狀態機暫停推進，不假裝安全。
  - L3 遭遇速率限制（429）或逾時：記錄 `l3_outcome=failed`，主管線與狀態機持續運作，由策略守門員根據現有 L2 證據進行保全降級處理。
