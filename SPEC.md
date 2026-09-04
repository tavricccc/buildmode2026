# Care Agent 規格書

> 從冰箱與門的行為觀測，產出可對接長照失能評估的證據。
> 本文件取代原架構圖，作為實作依據。

**版本** v0.1 · 2026-09-04
~~**唯一可用外部 API** MiniMax（無其他 LLM / VLM / ASR / TTS 供應商，設計上不得假設有 fallback）~~

**模型執行策略（本次產品方向）**：本機 vLLM 是主要推論入口；模型透過統一的 `ModelRuntime` 使用。MiniMax 若保留，僅作為特定 VLM 任務的可選 provider，不是唯一高階大腦，也不直接取得通知、政策或任意 SQL 權限。

---

## 0. 範圍宣告

### 我們做什麼

從長輩日常必然發生的行為（開冰箱、進出門、服藥）累積連續觀測，產出兩種輸出：

1. **急性事件的即時反應**（跌倒、長時間無活動）
2. **週／月尺度的失能評估證據**，對接既有量表項目，交給照管專員

### 我們不做什麼

- 不做醫療診斷。輸出是**行為代理指標**，不是量表分數
- 不自動通報社工或政府單位。系統產生依據，人做決定
- 不部署於浴室與臥室
- 不做 24/7 語音逐字記錄（見 §7 隱私硬性約束）

### 成功判準

Demo 能展示一份**自動填好的複評摘要**：每個欄位有趨勢曲線、有可回溯到日期的原始事件、有信心度。

### 0.1 新產品方向對齊

本規格保留原有急性事件與趨勢軌設計，但產品展示主軸改為三個邏輯 Agent：

1. **Context / World State Agent**：更新目前位置、活動、感測器狀態，明確區分已知、未知、正常與異常。
2. **Resident Interaction Agent**：資料不足且值得詢問時，以低侵入方式詢問長輩，建立經確認的事件記憶與提醒。
3. **Caregiver Agent**：從隱私過濾後的詳細事件與聚合指標產生日誌、趨勢與值得注意事項。

Risk、Policy、Scheduler、Retention 與 Audit 維持為確定性支援服務，不由模型自由決定外部行動。完整目標架構見 [docs/12_TARGET_ARCHITECTURE.md](docs/12_TARGET_ARCHITECTURE.md)。

---

## 1. 架構總覽

~~以下原始 L0–L6 骨架仍保留作歷史參考；實作與 Demo 以新的 World State 與三 Agent 邊界為準。~~

```
L0  感測層          手機鏡頭(RTSP) / 麥克風 / 磁簧 / Fake Health
                          ↓
L1  本地感知        Frigate / Silero VAD / Audio Event / GPIO
                          ↓
L2  事件層          Event Adapter → 三態判定 → Event Aggregator
                          ↓
L2b Context         Personal Baseline + Runtime State + Memory
                          ↓
                    ┌─────┴─────┐
              急性軌            趨勢軌
           (秒～小時)          (日～月)
                │                 │
        L3a Event Gate      L3b 每日彙總 (排程)
                │                 │
        L4a MiniMax M3      L4b Baseline 比對
                │                 │
        L5a Action Policy   L5b 量表對接 → 評估報告
                └─────┬─────┘
                      ↓
L6  收件人路由      分級揭露 + 升級逾時
```

兩軌的時間尺度差三個數量級，**必須是兩條獨立的程式路徑**：急性軌是事件驅動的，趨勢軌是排程批次的。不要試圖用同一套邏輯處理。

---

## 2. L0 感測層

| 來源 | 實作 | 用途 | 備註 |
|---|---|---|---|
| 手機鏡頭 | RTSP → Frigate | 玄關進出、客廳活動 | 用隊員手機，不另購 |
| 冰箱鏡頭 | USB webcam 或第二支手機 | 冰箱內容辨識 | **必須補光**，直接影響辨識率 |
| 麥克風 | 24/7 收音 | VAD + 聲音事件 | 逐字稿限制見 §7 |
| 磁簧開關 | GPIO（ESP32 或直接接筆電 USB-serial） | 冰箱門、大門、藥盒 | 保留至少一顆，見 §7.3 |
| Fake Health | JSON 模擬器 | heart rate / activity / 步態速度 | Demo 用，介面比照真實穿戴 |

### 2.1 冰箱拍照時機

拍**關門前的最後一幀**，不是開門瞬間。

- 開門瞬間拍到的是上一次操作後的狀態，且人正伸手進去容易遮擋
- 關門前人已離開，畫面最乾淨，且反映本次操作後的真實庫存

實作：持續緩衝最近 N 幀，磁簧或 Frigate 偵測到關門即回溯取最後一張可用畫面。

### 2.2 冰箱辨識策略：差異比對，不是全景盤點

全景盤點（每次辨識所有物品）在遮擋、疊放、不透明容器下不可能準，且錯誤會累積成庫存錯誤。

改為：把**開門前**與**關門後**兩張圖一起送給 VLM，只問「這次拿走了什麼、放進了什麼」。

```
庫存 = 初始盤點 + Σ(所有 diff)
```

Diff 會累積漂移，因此需**定期校正**：每 7 天或使用者主動觸發一次全景盤點，覆蓋累積值。

---

## 3. L1 本地感知層

### 3.1 Frigate

負責 camera ingest、motion / object detection、tracking、recording、snapshot / clip、zone、event lifecycle。

Zone 設定：
- `entrance` — 玄關，用於進出與訪客
- `living` — 客廳，用於活動量
- 冰箱鏡頭不進 Frigate，走獨立的 capture 流程（觸發式，非常駐）

### 3.2 Silero VAD（24/7）

只輸出「當下有無人聲」的布林值。**VAD 本身不是逐字稿**，可以常駐。

彙總輸出：`voice_activity_seconds` 每分鐘一筆。

### 3.3 Audio Event 分類器

輕量分類器（YAMNet 類，或自錄樣本訓練的小模型），輸出事件標籤，**不涉語意**：

`washing_machine` · `microwave` · `rice_cooker` · `water_running` · `toilet_flush` · `dishes` · `range_hood` · `impact` · `tv_audio` · `cough`

用途：
- 洗衣機 → IADL 洗衣項
- 微波爐／電鍋 → 區分「加熱即食品」與「真正下廚」，強化備餐判讀
- 水流／沖水 → **取代浴室攝影機**。我們不在浴室裝鏡頭，但知道他今天有沒有使用浴室
- 撞擊 → 補鏡頭死角的跌倒偵測

### 3.4 Whisper（受限啟動）

**這是與原規劃差異最大的一項。** 原規劃是 VAD 觸發即全開 ASR，等於對家中所有對話逐字記錄，包含訪客與電話另一端從未同意的第三人。

改為只在**對話窗**內啟動：

```yaml
conversation_window:
  opens_when: Speak Tool 執行完畢（系統主動說話後）
  duration: 30s，若期間持續有語音則延長，上限 90s
  during:
    - 啟動 Whisper
    - transcript 進入記憶體 buffer
  closes_when: 逾時 或 該輪 decision 完成
  on_close:
    - buffer 內 transcript 立即刪除
    - 不寫入 SQLite

outside_window:
  - VAD 只輸出布林值
  - Audio Event 分類器輸出事件標籤
  - 不啟動 Whisper，不產生任何逐字稿
```

模型建議用 `faster-whisper` small 或 medium。Large V3（約 3GB）與 Frigate 物件偵測、RTSP 解碼同機常駐，demo 當天有卡住的風險；且限縮到對話窗後，大模型的邊際效益不高。

---

## 4. L2 事件層

### 4.1 三態判定

**這是安全性上最重要的一項補強。** 原規劃是二元的（有 candidate event / 沒有），資料缺失會落進「沒事件 → 靜默」。但感測器無輸入可能是沒戴、沒電、鏡頭被遮——也可能是人倒了。

每個事件與每個時間窗都帶 `observability` 欄位：

| 狀態 | 意義 | UI |
|---|---|---|
| `observed_normal` | 有資料，指標在基準內 | 綠 |
| `observed_abnormal` | **有資料**，指標偏離基準 | 紅 |
| `unobservable` | **沒有資料** | 灰 |

`unobservable` 的處理**必須交叉驗證**，不可直接靜默：

```
某感測器無輸入
      ↓
檢查其他感測器同時段
      ↓
  ┌───┴───┐
其他有活動      全部靜默
→ unobservable  → 升級為 observed_abnormal
   標灰，不警報     觸發沉默事件
```

另需 heartbeat：每個感測器每 5 分鐘回報存活，連續 3 次未回報即產生 `sensor_down` 事件。

### 4.2 Event Aggregator

- **去重**：同一 zone 內 30 秒間隔的重複偵測合併
- **Session 合併**：冰箱在 5 分鐘內的多次開關（做菜情境）合併為一個 session，**關門後 5 分鐘無新開門才觸發一次 VLM 呼叫**
- **冷卻期**：同類型事件在冷卻期內只聚合不觸發

---

## 5. L3a Event Gate（急性軌）

### 5.1 原規劃的問題

~~原規劃寫的是「有 candidate event → 一律上 MiniMax」。~~ Frigate 的 person / motion event 產量很大，只要有人在鏡頭前走動就會觸發。新的 gate 先由 World State 判斷是否足夠、是否異常、是否需要詢問，再決定是否呼叫模型。

在只有一個 API 額度、沒有 fallback 的前提下，這一條必須修正。

### 5.2 分流規則

```python
def gate(event, budget, state):
    # 永不呼叫 — 本地聚合進趨勢軌
    if event.type in ("person_detected", "motion") and not state.anomaly_flag:
        return LOCAL_ONLY
    if state.in_cooldown(event.type):
        return LOCAL_ONLY

    # 必定呼叫
    if event.type == "fridge_session_closed":
        return CALL_M3          # 需要 VLM 辨識內容，這是核心
    if event.type == "anomaly_rule_hit":
        return CALL_M3
    if event.type in ("sensor_down", "silence_threshold_exceeded"):
        return CALL_M3
    if event.type == "user_reply" and state.conversation_open:
        return CALL_M3

    # 預算閘 — 依剩餘額度與優先度
    return CALL_M3 if budget.allows(event.priority) else LOCAL_ONLY
```

### 5.3 預算控制

~~只有一個 API 供應商，沒有備援，因此預算必須是硬約束：~~

模型 provider 與預算仍須是硬約束，但本機 vLLM 應作為主要路徑；外部 VLM 只處理明確授權且必要的事件。

```yaml
minimax_budget:
  daily_call_limit: 200        # demo 期間；正式部署另計
  priority_reserve:            # 保留額度，低優先事件不得佔用
    acute: 30
    fridge: 60
  on_exhausted:
    - 降級為本地規則引擎
    - 事件進入 queue，不丟棄
    - UI 顯示「AI 判讀暫停，本地監測持續」
    - 不得靜默失敗
```

### 5.4 M3 不可用時的降級

沒有第二家 API 可切，降級路徑必須明確設計：

| M3 狀態 | 行為 |
|---|---|
| 正常 | 完整流程 |
| 逾時 / 429 | 指數退避重試 3 次，期間本地規則繼續運作 |
| 持續失敗 | 進入降級模式：本地規則引擎判斷，事件入 queue，UI 明示降級中 |
| 急性事件 + M3 不可用 | **直接走本地規則的緊急路徑，不等 M3** |

最後一列很重要：跌倒偵測不能因為 API 掛了就不通知。

---

## 6. L3b～L5b 趨勢軌（新增，原規劃完全缺少）

**這是本案的重要差異化部分。** ~~原規劃的 SQLite schema 只有 `events / transcripts / memories / tool_calls / decisions`，全是即時事件紀錄，沒有指標累積、沒有基準線、沒有量表對接。~~ 趨勢軌、基準線與照護摘要維持為長期價值，但 Demo 先用可重播的模擬資料展示。

趨勢軌是**排程批次**（每晚 03:00 執行一次），不是事件驅動。

### 6.1 指標定義

| metric_key | 計算 | 對應 |
|---|---|---|
| `fresh_produce_ratio` | 生鮮品項數 / 總品項數 | IADL 備餐 |
| `cook_ingredient_purchases` | 需烹調食材新增次數／週 | IADL 備餐 |
| `ready_meal_items` | 即食／微波品項數 | IADL 備餐 |
| `fridge_dwell_median` | 開門到關門秒數中位數 | IADL 備餐 |
| `fridge_open_count` | 每日開門次數 | 進食節律 |
| `protein_days_per_week` | 出現蛋白質來源的天數 | 營養 |
| `vegetable_variety` | 每週不同蔬菜種類數 | 營養 |
| `leftover_stagnant_days` | 同一容器連續未移動天數 | 進食（非庫存） |
| `outing_count` | 每日出門次數 | IADL 外出 |
| `outing_duration_median` | 出門時長中位數 | IADL 交通（推估活動範圍） |
| `consecutive_homebound_days` | 連續未出門天數 | 生活空間萎縮 |
| `visitor_events` | 訪客進入次數 | 社會連結 |
| `pillbox_compliance` | 藥盒開啟符合排程的比例 | IADL 服藥 |
| `duplicate_purchase_flags` | 既有存量 ≥2 時仍購入同品項 | 認知代理 |
| `non_food_in_fridge` | 非食品出現於冰箱次數 | 認知代理 |
| `circadian_regularity` | 每日活動時間戳分佈的標準差 | 作息 |
| `washing_events` | 洗衣機運轉次數／週 | IADL 洗衣 |

### 6.2 個人基準線

**基準線必須是這個人自己的過去，不是人口平均。** 孤僻獨居者本來就少出門，跟平均值比只會誤判。

```
baseline(metric) = 該住戶前 12 週的 mean 與 sd（滾動窗）
偏離判定 = 當前 4 週滾動平均 vs baseline，以 sd 為單位
排除期間 = 家屬手動標記的住院、外宿、旅遊、送餐服務日
```

### 6.3 交叉推論規則

以下規則是零額外硬體成本、但顯著提升判讀品質的組合：

```
外食判定（避免誤判為未進食）
  冰箱無活動 AND 有出門（時長 45min–2hr，落在用餐時段）
    → 外食，正常，IADL 外出項良好
  冰箱無活動 AND 無出門
    → 紅旗

購物能力（IADL 第 2 項）
  出門後冰箱新增品項  → 自行購物，能力完好
  未出門但冰箱新增    → 他人代買／外送，此項退步的訊號

備餐 vs 加熱
  冰箱取出生鮮 + 抽油煙機/瓦斯聲  → 真正下廚
  冰箱取出即食品 + 微波爐聲        → 僅能加熱

穿戴資料缺失
  手錶無資料 + 環境感測有活動  → 沒戴，unobservable
  手錶無資料 + 環境感測也靜默  → 紅旗
```

### 6.4 量表對接

輸出的是**行為代理指標**，不是量表分數。報告措辭必須是「提供可觀測的行為證據，輔助專業人員評估」，絕不可寫成「自動評定 IADL 等級」或「偵測失智症」。

每則判讀必須具備四要素，缺一則退化為推播：

1. **個人基準線**
2. **可回溯到日期的證據**
3. **趨勢與變化幅度**
4. **具體到科別或服務項目的建議行動**

範例輸出：

```
觀測期  2026-07-01 ~ 2026-08-26（8 週）
基準線  該住戶自身前 12 週

  fresh_produce_ratio    68%  →  21%      ▼47pp   (-2.8 sd)
  cook_ingredient_purch  2.4  →  0.6 次/週
  ready_meal_items         1  →  7   項
  fridge_dwell_median    45s  →  12s

對應    IADL「食物烹調」由「能獨立計畫、烹煮並取用足夠餐食」
        降至「僅能加熱、供應已備妥餐食」
信心度  0.72（依證據筆數與 observability 覆蓋率計算）

建議    此項變化建議於下次複評時提出；若確認，
        可評估申請長照 2.0 送餐服務
```

---

## 7. 隱私硬性約束

以下為 MUST／MUST NOT，實作時視同測試項目。

### 7.1 必須

- **邊緣運算**：影像與音訊在本地處理。只有通過 Gate 的事件才上傳 snapshot / clip 至 MiniMax
- **骨架化**：活動量統計只保留 pose skeleton，原始畫面即時丟棄
- **Transcript TTL**：對話窗結束即刪除，不寫入 SQLite
- **本地媒體保留期**：Frigate recording 保留上限 7 天，逾期自動清除
- **分項同意**：「異常時通知里長」與「將生活紀錄提供給照管專員」是兩份獨立勾選

### 7.2 禁止

- **禁止**在對話窗外啟動任何 ASR
- **禁止**於浴室、臥室部署鏡頭
- **禁止**未經 Gate 的影像離開本機
- **禁止**系統自動聯繫社工或政府單位（見 §8.3）

### 7.3 感測器分級

即使主力走影像，**保留至少一顆磁簧開關**。它買的不是那 30 元的功能，而是這句可驗證的陳述：

> 我們刻意用隱私成本最低的感測器處理它能處理的事，只在必要時才動用影像。

藥盒微動開關（單價 10–20 元、一個 GPIO、兩小時完成）同時補上 IADL 服藥項，是全案性價比最高的一項硬體。

---

## 8. Tool 規格

原規劃的 `Notify Tool = 通知家屬 / 照護者` 過於扁平，缺少收件人分流、資訊粒度分級與升級逾時。

### 8.1 介面

```typescript
// 原：notify(message)
// 改：
notify({
  recipient_role: "neighborhood_head" | "home_care_worker" | "meal_delivery"
                | "care_manager" | "family" | "emergency",
  severity: "acute" | "silence" | "mid" | "trend",
  payload_level: "L1_presence_only" | "L2_single_domain" | "L3_full_evidence",
  message: string,
  evidence_ref?: string,      // 指向 assessment_report 或 event id
  escalation: {
    timeout_minutes: number,
    next_role: string | null
  }
})

speak({ text, expect_reply: boolean })   // expect_reply=true 才開啟對話窗
memory_search / memory_save / memory_update / memory_invalidate
state_get / state_update
health_read
frontend_update({ timeline?, state?, decision_log? })
```

### 8.2 路由表

| severity | 收件人 | payload_level | 逾時 | 升級至 |
|---|---|---|---|---|
| `acute` | emergency + family | L3 | — | — |
| `silence` | neighborhood_head | **L1** | 240 min | care_manager / 1966 |
| `mid` | home_care_worker / meal_delivery | L2 | 下次訪視 | care_manager |
| `trend` | care_manager | L3 | 下次複評 | — |

**每個事件必須有唯一責任人。** 三個人同時收到，等於每個人都假設另外兩個會處理。其他角色可收副本，但 UI 須標明誰是負責人。

### 8.3 分級揭露

長輩的飲食、活動、認知狀況屬個資法特種個資（健康資料）。里長不是醫事人員也不是社工師，無專業保密義務。

| payload_level | 內容 | 範例 |
|---|---|---|
| `L1_presence_only` | 僅存在與時間，**無任何健康細節** | 「王先生已三天無活動紀錄，請協助探視」 |
| `L2_single_domain` | 單一面向的提示 | 「本週訪視時留意進食狀況」 |
| `L3_full_evidence` | 完整趨勢、證據鏈、量表對應 | 見 §6.4 |

保護性案件（疑似受虐、嚴重疏忽）**不由系統自動觸發**。系統僅標記「建議人工評估是否需通報」，由專業人員依法定程序判斷。軟體不是法定通報義務人。

---

## 9. 資料模型

```sql
-- ── 即時層 ──────────────────────────────────
CREATE TABLE events (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  source        TEXT NOT NULL,      -- frigate | vad | audio_event | gpio | health
  type          TEXT NOT NULL,
  zone          TEXT,
  payload_json  TEXT,
  observability TEXT NOT NULL       -- observed_normal | observed_abnormal | unobservable
);

CREATE TABLE media (
  id        INTEGER PRIMARY KEY,
  event_id  INTEGER REFERENCES events(id),
  kind      TEXT,                   -- snapshot | clip | pose
  path      TEXT,
  expires_at TEXT                   -- 保留上限 7 天
);

-- transcript 僅在對話窗內存在於記憶體；此表只記錄「發生過對話」的中繼資料
CREATE TABLE conversations (
  id            INTEGER PRIMARY KEY,
  ts            TEXT,
  opened_by     TEXT,               -- speak_tool call id
  reply_received INTEGER,           -- 0/1，不存內容
  closed_at     TEXT
);

CREATE TABLE m3_calls (
  id           INTEGER PRIMARY KEY,
  ts           TEXT,
  trigger_event_id INTEGER REFERENCES events(id),
  priority     TEXT,
  tokens_in    INTEGER,
  tokens_out   INTEGER,
  latency_ms   INTEGER,
  status       TEXT                 -- ok | timeout | rate_limited | error
);

CREATE TABLE decisions (
  id          INTEGER PRIMARY KEY,
  ts          TEXT,
  m3_call_id  INTEGER REFERENCES m3_calls(id),
  action      TEXT,                 -- silent | speak | notify | act | emergency
  severity    TEXT,
  rationale   TEXT,
  degraded    INTEGER               -- 1 = 由本地規則做出，非 M3
);

CREATE TABLE tool_calls (
  id          INTEGER PRIMARY KEY,
  decision_id INTEGER REFERENCES decisions(id),
  tool        TEXT,
  args_json   TEXT,
  result_json TEXT
);

CREATE TABLE notifications (
  id             INTEGER PRIMARY KEY,
  decision_id    INTEGER REFERENCES decisions(id),
  recipient_role TEXT,
  payload_level  TEXT,
  sent_at        TEXT,
  ack_at         TEXT,
  escalated_at   TEXT,
  escalated_to   TEXT
);

-- ── 趨勢層（新增）────────────────────────────
CREATE TABLE daily_metrics (
  date        TEXT,
  metric_key  TEXT,
  value       REAL,
  n_events    INTEGER,
  coverage    REAL,                 -- observability 覆蓋率 0–1
  PRIMARY KEY (date, metric_key)
);

CREATE TABLE baseline (
  metric_key   TEXT PRIMARY KEY,
  window_start TEXT,
  window_end   TEXT,
  mean         REAL,
  sd           REAL,
  updated_at   TEXT
);

CREATE TABLE indicator_series (
  date        TEXT,
  instrument  TEXT,                 -- iadl | frailty | nutrition | cognition
  item_code   TEXT,                 -- 例：iadl_food_preparation
  level       TEXT,
  confidence  REAL,
  evidence_json TEXT,               -- 指向支撐此判讀的 event ids 與指標值
  PRIMARY KEY (date, instrument, item_code)
);

CREATE TABLE assessment_report (
  id           INTEGER PRIMARY KEY,
  period_start TEXT,
  period_end   TEXT,
  generated_at TEXT,
  content_json TEXT
);

CREATE TABLE excluded_periods (
  id      INTEGER PRIMARY KEY,
  start   TEXT,
  end     TEXT,
  reason  TEXT                      -- hospitalized | staying_with_family | travel | meal_service
);

-- ── 狀態 ────────────────────────────────────
CREATE TABLE runtime_state (
  key        TEXT PRIMARY KEY,
  value      TEXT,
  updated_at TEXT
);

CREATE TABLE observability_log (
  date            TEXT,
  sensor          TEXT,
  observed_minutes INTEGER,
  gap_minutes     INTEGER,
  PRIMARY KEY (date, sensor)
);
```

---

## 10. MiniMax 使用規格

### 10.1 冰箱辨識 Prompt 契約

送出：`before_image` + `after_image` + 已知庫存清單。

要求結構化輸出：

```json
{
  "removed": [{"item": "青江菜", "quantity": 1, "unit": "把", "confidence": 0.83}],
  "added":   [{"item": "雞蛋",   "quantity": 10, "unit": "顆", "confidence": 0.91}],
  "non_food_detected": [{"item": "遙控器", "confidence": 0.76}],
  "notes": ""
}
```

限制條件：

- **限定辨識範圍**至 50–80 項台灣家庭常見食材清單，讓模型從中選擇。開放式辨識會輸出「一個綠色的物體」這類無用結果
- **必須輸出 confidence**，低於 0.6 標記為不確定，交由使用者一鍵確認
- 給 2–3 個 few-shot 範例
- `non_food_detected` 是獨立欄位。異物錯置的臨床意義高，且異常物件偵測在技術上比精確盤點容易

### 10.2 Day 1 必做：能力驗證

MiniMax 是唯一 API，沒有換供應商的餘地。**開發第一天就要用 20–30 張真實冰箱照片測一次辨識品質**，並依結果決定降級層級：

| 測試結果 | 對策 |
|---|---|
| diff 辨識可用（>70% 正確） | 照規格走 |
| diff 勉強，全景不行 | 只做 diff，全景校正改為人工輸入 |
| 品項辨識不可靠 | 降級為「有無變化 + 粗分類（生鮮／即食／飲品）」，不報品名 |
| 完全不可用 | 冰箱改走純事件（開門次數、停留時間），影像僅作 demo 展示 |

最後一列仍然成立——**開門日誌本身永遠是準的**，而它就是進食節律的核心訊號。這是全案的保底敘事：即使辨識全掛，趨勢軌仍然產得出東西。

### 10.3 待確認

- MiniMax 的視覺輸入格式、單張大小上限、單次可送圖片數
- MiniMax 是否提供 TTS（`speak` tool 的實作依賴，若無則改用本地 TTS 或螢幕文字）
- Tool calling 的介面規格與併發限制
- 速率限制與每日額度

---

## 11. Demo 範圍

以環境變數 `DEMO_MODE = live | replay | simulated` 切換。

| 模態 | 內容 | 理由 |
|---|---|---|
| **Live** | 冰箱影像辨識（當場放食材）、diff 比對、pose skeleton、磁簧觸發 | 可當場驗證，有戲劇性 |
| **預錄** | 聲音事件辨識、玄關進出與訪客 | **會場噪音會殺死 live 音訊 demo** |
| **模擬** | 六個月趨勢曲線、量表對接、複評摘要、探視名單 | 現場跑不出六個月 |

**必備**：三路即時影像在現場容易出事，一鍵切換的預錄備援是必須，不是可選。

**哪些是實作的、哪些是模擬的，簡報時要主動說明**，不要讓評審自己發現。

### 11.1 模擬資料劇本

曲線要有雜訊與起伏，不能是一條乾淨的下坡線。

```
第 1 –  8 週   基準期，各項指標穩定
第 9 – 16 週   fresh_produce_ratio 緩降、outing_duration 縮短
第 17– 20 週   duplicate_purchase_flags 出現、pillbox_compliance 下降
第 21– 24 週   protein_days_per_week 明顯下降 → 觸發評估報告
```

---

## 12. 開發順序

| 優先 | 項目 | 理由 |
|---|---|---|
| P0 | MiniMax 視覺能力驗證（§10.2） | 決定整條路線，第一天必做 |
| P0 | 趨勢層 schema + 每晚彙總 job | 核心差異化，缺了就只是通用 agent |
| P0 | 複評摘要頁面 | Demo 主畫面 |
| P0 | 模擬資料產生器 | 沒有它 demo 沒東西看 |
| P1 | Event Gate 分流 + 預算控制 | 沒有它 API 額度會爆 |
| P1 | 三態與 heartbeat | 安全性 |
| P1 | Frigate 接上 + 冰箱 diff 流程 | Live demo 的主體 |
| P2 | Pose skeleton | 隱私論述的視覺化，性價比高 |
| P2 | Notify 分級與路由 | 被問到個資時要有 |
| P2 | 藥盒磁簧 | 兩小時，補 IADL 服藥項 |
| P3 | 聲音事件分類 | 預錄展示即可 |
| P3 | Speak / 對話窗 | 有時間再做 |

**至少保留 8 小時給簡報製作與排練。**

---

## 13. 待查證清單

本規格中的政策與量表細節係依既有知識整理，**未經一手來源核對**。政策細節講錯，在長照場合會被內行評審當場抓到。

- [ ] **Lawton IADL 台灣版是否有性別計分差異**（若男性不計備餐項，直接影響核心賣點——優先查）
- [ ] 現行 CMS 照顧管理評估量表的結構與計分方式
- [ ] CMS 複評週期，各縣市執行差異
- [ ] 長照 2.0 服務代碼與給付額度（送餐服務申請條件）
- [ ] IADL 衰退階層順序的文獻依據
- [ ] 各量表的授權與版權狀態
- [ ] 老人保護法定通報義務人規定與程序

另建議：**訪談一位實際的照管專員、居服督導或老年醫學科醫師 30 分鐘**。對提案的提升遠大於多寫五百行程式，且簡報上可寫「訪談過 N 位第一線人員」。第一天就做，現場業師與評審是最快的來源。

---

## 附錄：與原架構圖的差異

原架構圖（`care_agent_demo_frigate_vad_m3_sqlite.html`）的骨幹沿用：分層感知、Frigate 作為影像基礎設施、VAD 閘控 ASR、SQLite 記錄決策軌跡、Silent 作為有效輸出、cooldown。以下為本規格所做的修正：

| # | 原規劃 | 本規格 | 原因 |
|---|---|---|---|
| 1 | VAD 觸發即啟動 Whisper Large V3，transcript 存 SQLite | 僅對話窗內啟動，用完即刪 | 24/7 逐字稿會記錄未同意的第三人，且推翻整份提案的隱私防線 |
| 2 | 有 candidate event → 一律上 MiniMax | 四級分流 + 預算閘 | Frigate 事件量大，唯一 API 無 fallback，成本與延遲會失控 |
| 3 | 無趨勢層 | 新增趨勢軌、指標定義、baseline、量表對接 | 核心差異化原本完全不在實作規劃中 |
| 4 | `notify(通知家屬/照護者)` | 收件人路由 + 三級揭露 + 升級逾時 | 責任分散問題；里長無保密義務 |
| 5 | 二元事件判定 | 三態 + heartbeat + 交叉驗證 | 「沒資料」被當成「沒事」，會漏掉倒下的人 |
| 6 | 無降級設計 | M3 不可用時的本地規則路徑 | 只有一個 API，急性事件不能因 API 掛掉而不通知 |
