# 11 · 本機 Capture Layer

~~本文件原本描述的是目前產品的 capture 主路徑。~~ 最新 v3 的 canonical path 已改為 `RtspSource / ReplaySource → bounded frame buffer → fixed-rate QwenVL loop`；本文件與 `capture/` 程式保留作早期 bounded capture 參考，不覆蓋 v3 的 source contract。

## 1. 目前實作範圍

本階段提供一個不依賴雲端服務的本機 capture layer：

- 使用 OpenCV 從本機攝影機讀取影像。
- 使用 sounddevice 從本機麥克風讀取 PCM 音訊。
- 以同一個 `event_id` 與 `correlation_id` 綁定音訊、影片與關鍵影格。
- 產生 `bundle.json`，供後續 ASR、Video VLM、Audio Event Classification adapter 使用。
- 原始 capture 只做事件證據收集，不做風險判斷、不呼叫外部 API、不執行 L4。

~~目前固定秒數的 CLI 錄製不是完整產品事件流程。~~ 下一階段由 Sensor Adapter 或 Frigate／磁簧事件開啟 bounded pre-buffer／post-buffer，再交給 Event Normalizer 與 World State Agent；capture layer 不負責決定是否詢問長輩。

程式碼位於 `capture/`；資料契約沿用 [04_MEMORY_AND_DATA_MODEL.md](04_MEMORY_AND_DATA_MODEL.md) 的 provenance、timestamp、version 與 evidence reference 原則。

## 2. 安裝

需要 Python 3.10 以上，以及 macOS 對 Terminal／Python 執行檔開啟的 Camera、Microphone 權限。

```bash
cd buildmode2026
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

若 macOS 尚未授權，請到「系統設定 → 隱私權與安全性 → 相機／麥克風」允許你實際執行程式的 Terminal、IDE 或 Python app。權限變更後要重新啟動該 app。

## 3. 執行

錄製 10 秒的本機麥克風與攝影機：

```bash
.venv/bin/python -m capture --duration 10 --camera 0 --output data/captures
```

執行完成後會產生類似以下目錄：

```text
data/captures/
└── evt_<id>/
    ├── bundle.json
    ├── audio.wav
    ├── video.mp4
    └── frames/
        ├── frame-00000.jpg
        └── ...
```

`bundle.json` 會包含 subject、source、事件時間窗、correlation ID、影音 evidence refs、模態狀態、frame/audio 數量、資料品質與 capture version。capture data 已加入 `.gitignore`，不會被意外提交到 repository。

## 4. 常用參數

| 參數 | 預設 | 用途 |
|---|---:|---|
| `--duration` | `10` | 錄製秒數 |
| `--camera` | `0` | OpenCV camera device index |
| `--audio-device` | 系統預設 | sounddevice input device 名稱或 index |
| `--subject-id` | `resident_001` | 被照護者識別碼；Demo 請使用 pseudonymous ID |
| `--source-id` | `local-mac` | 感測來源識別碼 |
| `--fps` | `10` | 影片讀取與寫入的目標 FPS |
| `--sample-rate` | `16000` | 麥克風取樣率 |
| `--no-video` | 關閉 | 只測試麥克風 |
| `--no-audio` | 關閉 | 只測試攝影機 |

例如只測試攝影機：

```bash
.venv/bin/python -m capture --no-audio --duration 5 --output data/captures
```

## 5. 輸出契約

`bundle.json` 的重要欄位：

| 欄位 | 意義 |
|---|---|
| `schema_version` | `multimodal_event_bundle.v1` |
| `event` | event_id、subject_id、source_id、correlation_id、時間窗與 trigger |
| `evidence` | WAV、MP4、JPG 的相對路徑、content type、sha256 與建立時間 |
| `modalities.audio` | captured／unavailable 與下一個 adapter：ASR / audio classifier |
| `modalities.video` | captured／unavailable 與下一個 adapter：Video VLM |
| `quality` | camera/audio open 狀態、frame/audio 數量、capture duration |
| `provenance` | local source、component 與 capture version |

缺少某一種設備時，另一種模態仍可輸出；缺失會在 `modalities` 與 `quality` 明確記錄，不代表該模態判定為「沒有事件」。

目標 bundle 另需補上：`event_type`、`zone`、`observability`、`dedup_key`、`session_id`、`consent_scope`、`retention_class` 與 `context_snapshot_id`。這些欄位由事件層補齊，capture 不應自行猜測。

## 6. 權限與隱私

- Capture 是 bounded window，預設 10 秒；不做 24/7 語音逐字記錄。
- 影片與音訊只寫入本地指定 output directory；本階段不傳送到外部服務。
- `subject_id` 應使用 pseudonymous ID，不要把姓名、電話或病歷直接放進檔名或 metadata。
- 原始 evidence 的 TTL、播放、匯出與刪除政策仍需依 [09_DEPLOYMENT_AND_SECURITY.md](09_DEPLOYMENT_AND_SECURITY.md) 落實。
- 啟用真實場域前，先取得被照護者與場域必要的錄音／錄影同意。

## 7. 測試與驗證

不需要硬體即可執行資料模型測試：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

有設備時，先執行 5–10 秒 capture，再檢查：`bundle.json` 可解析、`event.window.end` 存在、evidence refs 指向檔案、WAV 可播放、關鍵影格可開啟、frame/audio count 大於零。若設備不可用，CLI 會回報錯誤，不會產生看似成功的 bundle。

## 8. 後續 TODO

- [ ] 將 Frigate event adapter 接到 `EventCandidate`，由 trigger 決定 capture window，而不是只由 CLI 啟動。
- [ ] 加入 pre-buffer／post-buffer，保存事件前後的證據窗口。
- [ ] 加入本地 ASR、Audio Event Classifier 與 Video VLM adapter；各自輸出 Observation schema。
- [ ] 加入事件去重、Event Ledger、SQLite index 與 replay command。
- [ ] 加入裝置時鐘偏差、音畫同步與 data quality calibration。
- [ ] 加入 camera/mic device listing 與 macOS 權限診斷。
- [ ] 在完成人工確認流程前，不接 L3/L4 真實通知或緊急通道。
