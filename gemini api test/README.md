# Gemini Multimodal REST API Client

支援影片（Video）、音訊（Audio）、圖片（Image）與純文字（Text）的原生 REST API 多模態調用客戶端。

* **預設模型**：`gemini-3.5-flash-lite`（亦可透過參數自由切換為其他模型如 `gemini-2.5-flash` 等）
* **零外部依賴**：完全使用 Python 標準函式庫（`urllib`、`base64`、`json`、`mimetypes`）
* **智慧傳輸**：小檔案（<= 20MB）自動使用 Base64 inline_data（極速）；大檔案自動走 Google Files API 可續傳上傳與處理輪詢。

---

## 設定 API 金鑰

複製 `.env.example` 為 `.env` 並填入金鑰：

```bash
cp .env.example .env
```

或設定環境變數：
```powershell
$env:GEMINI_API_KEY="your_api_key_here"
```

---

## 命令列 (CLI) 使用方式

### 1. 純文字問答
```bash
python gemini_client.py "你好，請簡短介紹你自己"
```

### 2. 影片理解
```bash
# 自動模式
python gemini_client.py "分析這部影片中的事件與細節" --video path/to/video.mp4

# 強制使用 Google Files API（適合長影片）
python gemini_client.py "詳細分析影片" --video path/to/video.mp4 --method files_api
```

### 3. 音訊辨識 / 語音分析
```bash
python gemini_client.py "請辨識這段錄音的對話內容並條列重點" --audio path/to/recording.mp3
```

### 4. 圖片分析
```bash
python gemini_client.py "這張圖表說明了什麼？" --image path/to/chart.png
```

### 5. 更多選項
* `-m` / `--model`：指定模型名稱（如 `gemini-2.5-flash`、`gemini-3.5-flash`）
* `--sys`：設定系統指令（System Instruction）
* `--verbose`：顯示連線與處理進度細節

---

## Python 程式碼引用

```python
from gemini_client import GeminiClient

client = GeminiClient()

# 純文字
ans = client.text("請寫一首五言絕句")

# 影片分析
ans = client.video("分析這個短片", "video.mp4")

# 音訊辨識
ans = client.audio("轉錄音訊內容", "speech.m4a")

# 圖片分析
ans = client.image("描述圖片", "photo.jpg")
```
