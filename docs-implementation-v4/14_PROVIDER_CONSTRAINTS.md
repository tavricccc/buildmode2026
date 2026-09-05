# 14 · Provider 能力與限制(GMI Cloud / MiniMax-M3)

實測日期:2026-09-05。以下數字來自對 production endpoint 的實際呼叫,不是文件推論。
文件查證部分另註明出處;標「官方文件未載明」者表示官方沒有定義,只能以實測為準。

重跑方式見本頁最後一節。**更換 provider 或 model 後必須重跑**,本頁是快照而非長期契約。

## P0 採用配置

| 項目 | 值 |
|---|---|
| Provider | GMI Cloud |
| Base URL | `https://api.gmi-serving.com/v1` |
| 認證 | `Authorization: Bearer <GMI_API_KEY>` |
| Model ID | `MiniMaxAI/MiniMax-M3` |
| 輸入 | 5 秒窗口 @ 2fps = 10 張 base64 JPEG |
| 結構化輸出 | `response_format: {"type":"json_object"}` |

## 實測通過

| 項目 | 結果 |
|---|---|
| `GET /v1/models` | 200,83 個模型,M3 在列 |
| 單一 request 多圖 | **10 張通過**,無錯誤 |
| **影格順序保留** | **12/12 完全正確**(10 張 480×270) |
| **無靜默截斷** | 同上,每次都回報全部 10 張 |
| `json_object` | 12/12 可解析 |
| 影像辨識 | 自然影像描述正確;單張數字辨識正確 |

### 測試素材的設計

以七段式**單一位數 0–9** 標記影格。兩個理由,都來自實測踩到的坑:

- 模型對**純色影格**辨識不準,會讓「順序錯誤」與「辨識錯誤」無法區分。
- 標記用**兩位數**(1–10)時,「10」常被讀成「0」,污染順序判定 —— 這曾同時造成 frames 與 video 的誤判。

單一位數沒有歧義,答錯即為真正的傳輸問題。

### 延遲有長尾,會超過窗口

12 次呼叫(10 張 480×270):

| 指標 | 值 |
|---|---|
| 中位數 | 2,463 ms |
| p90 | 3,423 ms |
| 最小 / 最大 | 1,549 / **8,889** ms |
| **超過 5 秒窗口** | **2/12(約 17%)** |
| `prompt_tokens` 中位數 | 2,013 |

多數窗口遠快於 5 秒,但約六分之一會超過。`03` 的「窗口長度 ≥ round trip」在中位數成立、在長尾不成立。

**影響**:`最多一個 running + 一個 latest pending` 的設計下,慢窗口期間新產生的窗口會被後來的取代,實際取樣密度低於設定值。這是可接受的降級(不會累積、不會 OOM),但**不得把「沒有觀測」記錄成「沒有事件」**——與 `09` 的原則一致。UI 應顯示實際完成的窗口數而非設定值。

### Token 用量隨解析度變化

| 影格尺寸 | 10 張的 `prompt_tokens` | 每張約略 |
|---|---|---|
| 320×180 | 1,053 | ~100 |
| 480×270 | 2,017 | ~197 |
| 640×360 | 3,216 | ~316 |

解析度是成本的主要槓桿。官方沒有公布影像 token 換算公式,以上為實測。

## 實測不通過

### 音訊完全不被處理

送出音訊不會進入模型。四條獨立證據:

1. **`prompt_tokens` 不變**:無音訊 178、`audio_url` 178、`input_audio` 178、**60KB 隨機位元組 178**。
2. **損壞音訊不報錯** —— payload 在解析前就被丟棄。
3. **模型自述**:「I'm a text-only AI without audio capabilities」。
4. **對照組成立**:同樣方法換成影像,token 數與答案都會改變(數字辨識正確),證明 wire format 無誤。

補充:M3 的 catalog metadata 沒有任何音訊欄位;影片內嵌音軌問內容同樣回 `nothing`。

**影響**:`VisionObservation` 的 `audio_present`、`audio_events`、`speaker_emotion`、`speech_detected`、`speech_transcript` 在此 provider 下**沒有事實依據**。任何強制填入 `audio_present=true` 的邏輯都會產生假資料,必須移除或標為 `unavailable`。

`change_gate` 由本地 PCM 計算的音量 RMS 不受影響,那是主機端運算,可以保留。

### 影片輸入的時序不可靠

同樣 10 張影格包成 MP4,以 `video_url` 送出,同一支檔案重複 6 次(單一位數素材):

```
video  正確 0/6    失敗樣態為掉幀:
                   ['0','2','3','9','8']              只回 5 個
                   ['0','2','3','4','5','6','7','8']  只回 8 個
frames 正確 12/12  順序與張數每次都對(同一批素材)
```

較早以兩位數素材測得 1/6,那次的「正確」與 frames 的「失敗」都是 `10`→`0` 的辨識誤差所致。素材修正後結果一致:**video 沒有一次正確**。

跌倒判斷依賴「站→躺」的先後,掉幀會直接讓 `vertical_transition` 失去依據。

成本上影片較省(1,133 vs 2,013 tokens),延遲相近(2,059–3,899 ms),但省下的 token 換來的是不可用的時序。

→ **`03` 的 `video` 模式 probe 未通過,維持 `frames` 為預設。** `analyze_video` 保留為 P1,預設不啟用;未來重測必須重複多次並使用單一位數素材 —— 單次通過不算數。

## 方案限制

**免費 key 只涵蓋 M3。** 其他模型一律回 `HTTP 402 Insufficient balance` / `model_access_denied`(實測 `google/gemini-3.8-flash`、`MiniMaxAI/MiniMax-M2.5`)。

- `03` 所說「probe 失敗可換模型」在免費期內做不到。
- `07` 的 analysis slot 同樣受限。
- M3 活動免費期為 2026-08-24 至 2026-09-06,之後恢復計費,屆時須重新評估。

**catalog 內沒有任何語音模型。** 83 個模型的名稱與 metadata 均不含 audio/speech/whisper/tts/omni,全為文字或視覺模型。`/v1/audio/transcriptions` 端點僅依 model 名稱轉發,沒有可用的 ASR target。

→ 音訊要落地只能外接:另一家 ASR endpoint,或本地 whisper.cpp。v4 `09` 的獨立管線設計支援這條路,model slot 指向另一 endpoint 即可,domain code 不變。

## 已知風險

**1. 預設 User-Agent 會被邊緣擋下**

Python 預設的 `Python-urllib/x.y` User-Agent 一律回 `HTTP 403 error code: 1010`,**且無認證、假 key、真 key 的回應完全相同**,看起來像認證失敗但不是。換任何其他 UA 即正常。

→ 所有 HTTP client 必須明確設定 User-Agent。`backend/adapters.py` 的 `_http_json` 已設 `Longcare/1.0`。診斷認證問題時務必先排除此項。

**2. 靜默截斷(尚未觸發,但未防範)**

GMI 提供 `context_length_exceeded_behavior`,官方預設為 `truncate`。目前 10 張影格的 payload 未觸及上限(實測第 10 張仍被讀到),但更高解析度或更多影格可能觸發,且**不會回報錯誤**。

→ Adapter 應明確設定為報錯而非截斷。

**3. 官方文件互相矛盾**

- M3 catalog 卡片只標 `LLM`,未標視覺 tag,但說明文字稱支援 image/video。
- 通用 LLM reference 列 text/image/audio,漏列 video,且 audio 實測不成立。
- `max_tokens` 同頁同時記載「預設 2000」與「範圍 1–128」。
- `/v1/models` 範例將 model ID 放在 `object`、`id` 留空,與其下方欄位表相反。

→ 不得依這些文件數值做硬驗證。

**4. serving backend 不固定**

GMI 在 vLLM、SGLang、TensorRT-LLM 間選擇並隱藏實作,可能變動,不構成能力承諾。這正是 `01` 要求「domain code 不得依賴 runtime 私有 API」的實際理由。

## 文件有保證但未逐項實測

- `response_format` 的 `json_object`(已實測可用);`json_schema` / `strict` **官方未載明**,故 `03` 不依賴。
- `tools` 欄位存在;`tool_choice`、`tool_calls` response schema **官方未載明**。
- Rate limit 以組織為單位、採 TPM;Tier 1 為 1,000,000 TPM。RPM 與並發上限**官方未載明**。

## `adapter_mode: gmi`

`04` 的 `model_endpoints.adapter_mode` 在 P0 需要 `gmi` 一種,封裝以下差異:

- 明確設定 User-Agent(否則 403,見上)。
- 明確設定 `context_length_exceeded_behavior`,避免靜默截斷。
- 使用 `max_tokens`(該 provider 未列 `max_completion_tokens`)。
- 剝除回應中可能混入的 reasoning 包裝後再解析 JSON。
- `/v1/models` 回應的 `id` / `object` 欄位錯置容錯。

## 重跑 probe

`scripts/probe_provider.py` 會重跑本頁全部項目並輸出對照表。更換 provider 或 model 時執行:

```bash
python3 scripts/probe_provider.py --base-url https://api.gmi-serving.com/v1 \
  --model MiniMaxAI/MiniMax-M3 --key-file GMIAPI.txt
```

只用標準函式庫,不需安裝套件;測試素材由 ffmpeg 產生。
