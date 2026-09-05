# 14 · Provider 能力與限制(GMI Cloud / MiniMax-M3)

查證日期:2026-09-05。來源限官方文件與 production model catalog。

本文件記錄 P0 實際採用的 provider 能力邊界。**「未載明」表示官方文件沒有定義,不得當作已知能力寫進 contract**;這類項目一律以 capability probe 的實測結果為準。

## P0 採用配置

| 項目 | 值 |
|---|---|
| Provider | GMI Cloud |
| Base URL | `https://api.gmi-serving.com/v1` |
| 認證 | `Authorization: Bearer <GMI_API_KEY>` |
| Model ID | `MiniMaxAI/MiniMax-M3` |
| 輸入 | 5 秒窗口 @ 2fps = 10 張 base64 JPEG + 5 秒 16 kHz WAV |
| 結構化輸出 | `response_format: {"type":"json_object"}` |

M3 於 2026-08-24 至 2026-09-06 為活動免費期,之後恢復計費。成本模型須在免費期結束前以實測 `usage` 回填。

## 已有文件保證

- OpenAI-style `POST /v1/chat/completions`,提供 `GET /v1/models`。
- `response_format` 的 `json_object`。
- `tools` 欄位存在。
- Rate limit 以組織為單位、採 TPM 計算;Tier 1 為 1,000,000 TPM。

## 官方文件未載明(須以 probe 實測)

| 項目 | 影響 |
|---|---|
| 單一 request 的多圖上限 | **實測 10 張可通過**(2fps × 5 秒),官方仍未載明上限 |
| M3 的 `video_url` wire format | `video` 模式須 probe 通過才可啟用,預設維持 `frames` |
| 影片長度、大小、解析度上限 | 片段長度上限未知 |
| 影片的 token 換算公式 | 成本只能由 `usage` 回填 |
| `json_schema` / `strict` | **因此 `03` 採 `json_object` + 應用層驗證** |
| `tool_choice`、`tool_calls` response schema | function calling 不作為 P0 的結構化輸出手段 |
| RPM、最大並發數 | 併發上限以保守值設定 |

## 已知風險

**1. 靜默截斷**

GMI 提供 `context_length_exceeded_behavior`,**預設為 `truncate`**。超出 context 時會靜默截斷輸入且不回報錯誤,片段可能只有前段進入模型而回應看似正常。

→ Adapter 必須明確設定為報錯而非截斷,並在 probe 中以可辨識的尾段內容驗證輸入完整性。

**2. 官方文件互相矛盾**

- M3 的 catalog 卡片只標 `LLM`,未標視覺 tag,但說明文字稱支援 image/video 輸入。
- 通用 LLM reference 列出 text/image/audio,**漏列 video**。
- `max_tokens` 同頁同時記載「預設 2000」與「範圍 1–128」。
- `/v1/models` 範例將 model ID 放在 `object`、`id` 留空,與其下方欄位表相反。

→ Adapter 不得依這些文件數值做硬驗證;以 probe 實測為準。

**3. 非統一 serving backend**

GMI 在 vLLM、SGLang、TensorRT-LLM 間選擇並隱藏實作(依 catalog metadata,M3 指向 SGLang)。backend 可能變動,不構成能力承諾。

→ 這正是 `01` 要求「不得讓 domain code 依賴 runtime 私有 API」的實際理由。

## 替代模型

同一 GMI catalog 中,若 M3 的 probe 失敗或不穩,以下可直接替換而不動 domain code:

| Model ID | 備註 |
|---|---|
| `zai-org/GLM-5.3-Flash` | 官方頁同時有 `image_url` 與 function-call 範例,文件最完整 |
| `google/gemini-3.8-flash` | 官方頁有 `video_url` 範例 |
| `Qwen/Qwen3-VL-235B-A22B-Instruct-FP8` | 官方頁描述影像、OCR、空間與影片理解 |

實際可呼叫的模型以該 API key 的 `GET /v1/models` 回傳為準,不以 catalog 頁為準。

## `adapter_mode: gmi`

`04` 的 `model_endpoints.adapter_mode` 在 P0 需要 `gmi` 一種,封裝以下差異,不得外洩到 domain layer:

- 明確設定 `context_length_exceeded_behavior`,避免靜默截斷。
- 使用 `max_tokens`(該 provider 未列 `max_completion_tokens`)。
- 剝除回應中可能混入的 reasoning 包裝後再解析 JSON。
- `/v1/models` 回應的 `id` / `object` 欄位錯置容錯。
- 額外欄位 `top_k`、`ignore_eos` 視需要透傳,不進 domain contract。

## 這份文件存在的理由

P0 期間 vision endpoint 由本地 vLLM 換到 MiniMax 第一方 API、再換到 GMI Cloud。三次更換中 domain code 未變更,只換 endpoint 設定與 adapter mode——這是 `01`「模型差異只能存在於明示且受測的 adapter」與 capability slot 設計的直接驗證。

Provider 能力會變動,本文件是快照而非長期契約;每次更換 provider 須重跑 capability probe 並更新此頁。
