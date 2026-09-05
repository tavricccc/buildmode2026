# 快速安裝與執行指南 (Getting Started)

本指南說明如何在 Windows (原生 / WSL2)、macOS 或 Linux 環境下建置、設定並啟動 Care Agent。

---

## 系統需求

在開始之前，請確保系統已安裝以下工具：

1. **Python 3.11+**：後端程式碼堅持僅使用 Python 原生標準庫（Standard Library），**無需執行任何 `pip install`**。
2. **Bun 1.1+**：用於管理前端相依、建置靜態資源與執行協調腳本（[官方安裝指南](https://bun.sh/)）。
3. **FFmpeg 6.0+ 與 ffprobe**：用於處理 RTSP 串流截取、影音分段與影格抽取，指令需存在於系統 PATH 中。

---

## 步驟一：下載儲存庫與安裝相依

複製專案並安裝前端建置相依：

```bash
git clone https://github.com/tavricccc/buildmode2026.git
cd buildmode2026/src

# 安裝前端相依套件與腳本工具
bun install
```

> **設計守則**：執行 `bun install` 與初次啟動時，系統**絕不會自動下載數 GB 的深度學習模型權重**。所有本機模型（如 L1 YOLO 偵測器）均於瀏覽器進入設定精靈時按需下載。

---

## 步驟二：初始化資料庫

執行資料庫結構遷移，於 `src/data/care.sqlite3` 建立 SQLite 表格結構與 WAL 模式：

```bash
bun run migrate
```

驗證環境相依與 Python 語法相容性：

```bash
bun run verify
```

---

## 步驟三：啟動伺服器

### 正式執行模式
```bash
bun start
```
伺服器預設監聽於 `http://127.0.0.1:8200`。

### 開發熱重載模式 (Development Mode)
```bash
bun run dev
```
此模式會同時啟動後端 API 伺服器與 Vite 前端熱重載（HMR）開發伺服器。

---

## 步驟四：初次設定精靈 (/setup)

初次啟動且尚未設定金鑰或偵測器時，瀏覽器開啟 `http://127.0.0.1:8200` 會自動導引至 `/setup` 介面：

1. **硬體與環境自我檢測**：
   - 自動檢查 Python 執行期版本、FFmpeg 執行檔路徑、攝影機 RTSP 來源可用性及磁碟儲存空間。
2. **L1 存在感測器選擇**：
   - 選擇使用 `YOLO11n (CPU/GPU)` 或 `Stub (離線模擬)`。選擇實際模型時，系統於此步驟按需下載約數十 MB 輕量權重。
3. **L2 Gemini 常規語意層配置**：
   - 輸入 Google Gemini API 金鑰。
   - 預設模型名稱：`gemini-3.5-flash-lite`（原生 REST 端點：`https://generativelanguage.googleapis.com/v1beta`）。
4. **L3 MiniMax 深度覆核層配置**：
   - 輸入 MiniMax / GMI Cloud API 金鑰。
   - 預設端點：`https://api.gmi-serving.com/v1`，模型名稱：`MiniMaxAI/MiniMax-M3`。
5. **分層連線測試與級聯測試 (Cascade Test)**：
   - 提供個別測試按鈕驗證 L1、L2、L3 連線能力，並執行一次完整的 E2E 模擬資料流測試。
6. **通報與安全設定**：
   - 設定 Telegram Bot Token 與受信照護者聊天室 ID。
   - 配置心跳頻率（無人時建議 30–60 秒）、事件佇列與觀察者日報時間。

---

## 敏感資訊與金鑰安全規範

專案採用嚴密的金鑰隔離機制：

- **Secret Store**：由後端專屬之 `secretstore.py` 管理，敏感金鑰以權限 `0600` 存放在 `data/` 目錄中。
- **無洩漏保證**：
  - 前端發送 `GET /api/settings` 時，金鑰欄位僅回傳 `is_configured: true`，絕不回填真實金鑰明文。
  - 前端 JavaScript Bundle、API 回應、SQLite 稽核日誌與 Git 歷史中絕不包含金鑰字串。
- **容器化／無人值守部署**：
  - 可複製 `src/.env.example` 為 `src/.env`，並透過環境變數傳入金鑰：
    ```bash
    cp .env.example .env
    # 編輯 .env 填入 GEMINI_API_KEY 與 MINIMAX_API_KEY
    ```

---

## 離線樁模組模式 (Stubs Mode)

若暫時缺乏外部 API 金鑰或處於無網路測試環境，系統提供完整離線樁模組。Stubs 嚴格重現真實 Provider 的資料結構與例外行為（包含狀態機流轉、Schema 驗證與多模態回傳），可用於完整演練前端介面：

```bash
# 指定使用離線 Stubs 啟動
L2_PROVIDER=stub L3_PROVIDER=stub bun start
```
