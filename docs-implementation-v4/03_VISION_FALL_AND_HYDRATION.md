# 03 · 視覺、跌倒與喝水 Pipeline

## Vision model contract

一次 job 送出一個 **5 秒時間窗**與時間資訊,經 Model Gateway 送到 active `vision` model,回傳 v3 相容 `VisionObservation`。

| 參數 | P0 值 | 可調 |
|---|---|---|
| 窗口長度 | 5 秒 | `ui_editable` |
| 取樣率 | 2 fps(每窗 10 幀) | `ui_editable` |
| 音訊 | 5 秒 16 kHz mono,隨窗口一併送出 | `ui_editable` |
| detail | `low`(進 suspect 後拉高) | `ui_editable` |

### Wire format

同一個時間窗有兩種送出方式,由 endpoint 的 capability probe 決定,domain layer 不感知差異:

| 模式 | 內容 | 狀態 |
|---|---|---|
| `frames`(P0 預設) | 10 個 `image_url` content part(base64 JPEG)；音訊只有在 capability probe 通過後才附送 | **影像已實測可用**,10 張可通過 |
| `video` | 單一 `video_url` content part | provider 未文件化,須 probe 後才可啟用 |

`video` 模式在 provider 支援時可減少 payload 體積並保留完整時序;但目前 GMI 對 M3 的 `video_url` wire format 沒有官方定義(見 `14`),故不得作為預設。兩種模式回傳同一份 `VisionObservation`,切換不影響狀態機。

`VisionObservation` 欄位不變:posture、vertical transition、near-floor、容器、靠嘴、飲用動作、confidence、supporting frame indexes 與 uncertainty。

v3/v4 早期版本的「1–8 張」上限由實測取代:GMI 對多圖上限無文件保證,實測 10 張可通過。

## 結構化輸出

採 `response_format: {"type":"json_object"}` + 應用層 schema 驗證,**不依賴 `json_schema` 或 `strict`**。理由見 [14 · Provider 能力與限制](14_PROVIDER_CONSTRAINTS.md):目前 provider 只對 `json_object` 有文件保證。

流程固定為:

```text
json_object 回應 → 去除 reasoning 包裝 → Pydantic 驗證
  ├─ 通過 → VisionObservation → 狀態機
  ├─ 失敗 → repair(次數可設定,預設 1)
  └─ repair 仍失敗 → 保存 invalid model call,不更新事件
```

Repair 次數、timeout、retry 為 `ui_editable`。Repair 從 v3 的選配升為 P0 必要路徑。

## Model call 稽核

保存 input hash、片段長度/fps、endpoint/model/deployment type、latency、`usage` 實測值、prompt/schema/config version,不保存 secret。Cloud endpoint 顯示片段傳輸告知;local endpoint 不得被 UI 誤標為 cloud,反之亦然。

不支援影片輸入或 `json_object` 的 model 不可啟用到 vision slot;capability probe 失敗即不可 activate。

## 取樣策略

變化偵測作為**加速器,不作為閘門**。三段頻率皆為 `ui_editable`:

| 狀態 | 頻率 | 說明 |
|---|---|---|
| 基準心跳 | 每 15 秒一段 | 無論有無變化都執行,保證覆蓋 |
| 偵測到變化 | 每 5 秒一段 | 變化觸發的 burst |
| suspect / confirmed | 每 5 秒一段 | 由狀態機強制,忽略變化偵測 |

理由:跌倒後人躺著不動會**停止產生變化**,若以變化偵測當閘門,會在最需要持續觀測時停止供料,狀態機永遠無法從 suspect 升到 confirmed。這與 `09`「缺資料不得解釋為事件未發生」一致。

變化偵測本身只記錄輕量 metadata(時間、變化幅度、是否觸發 job),不固化影像。

Pending 永遠最多一筆:最多一個 running 和一個 latest pending,不累積 FIFO。

**延遲有長尾,不能只看中位數。** 實測(見 `14`)中位數 2.5 秒、p90 3.4 秒,但約 17% 的呼叫超過 5 秒窗口,最差近 9 秒。因此:

- 慢窗口期間產生的窗口會被後續窗口取代,**實際取樣密度低於設定值**。這是刻意的降級(不累積、不 OOM),不是錯誤。
- **被略過的窗口必須記錄**,UI 顯示實際完成數而非設定值。缺觀測不得解釋為「沒有事件」。
- 若略過率過高,應**延長基準間隔**而非縮短窗口——縮短窗口會同時削弱時序判斷。
- suspect/confirmed 期間的強制觀測優先於基準心跳,確保關鍵時段不被略過。

## 狀態機

跌倒沿用 `idle → suspect → confirmed → recovering → resolved`;喝水沿用 `idle → suspect → confirmed → active → completed`,只有 completed session 計數,重試不得重複。

確認規則(數值為建議值,待團隊確認後定案):

- **單一片段的 lying observation 不得直接確認跌倒。** 需連續 N 段(建議 2 段,約 10 秒)維持 near-floor 才升 confirmed。
- confidence 低於門檻(建議 0.5)的 observation 可進 suspect,但不得作為升 confirmed 的依據。
- confirmed 後持續 M 秒(建議 60 秒)無 recovering 跡象即觸發通知,見 `12`。
- 喝水採固定容量模型:一次 completed session 記為一個設定容量,不估算實際毫升數。這是刻意簡化,非量測。

## Evidence

只有 suspect/confirmed 周邊的窗口依 retention 固化,單位是**時間窗**而非單張影格。Evidence 記錄是否離開主機、endpoint、傳送時間與 model call reference,讓操作者可稽核資料流向。

## 未決事項

以下需實測後回填,不得先寫入規格當作已知:

1. **單次 round trip 延遲** — 決定基準心跳與片段長度是否可維持即時處理。
2. **模型是否實際使用音軌** — 必須由 capability probe 明確 opt-in；未通過時 adapter 不送音訊，也不採信模型回傳的音訊欄位，需啟用 `09` 的獨立 ASR 管線。
3. **`usage.prompt_tokens` 實測值** — 影片無官方 token 換算公式,成本模型只能由實測回填。
