# 11 · 部署與硬體相容性

## Processes

- Care backend、React frontend、audio/media worker。
- Local Model Supervisor：只有啟用本地模型時必要，可管理一或多個 OpenAI-compatible runtime。
- Cloud-only 部署不啟動 local model server。

## Runtime 策略

本地 catalog entry 必須宣告支援的 runtime、OS、CPU architecture、quantization、RAM/VRAM、CUDA/ROCm/Vulkan需求與 OpenAI-compatible capabilities。可採用具相容 API 的 llama.cpp server、vLLM 或其他受版本鎖定 runtime，但不得讓 domain code依賴其私有 API。

- NVIDIA：優先 CUDA-capable runtime。
- AMD：優先 ROCm-capable runtime；無 ROCm 的平台可選 Vulkan/CPU-capable runtime。
- CPU：功能 fallback，效能由安裝前 benchmark 告知。
- Apple/MLX 不屬於 v4 驗收目標，也不是必要依賴。

Setup Service 不自動安裝 GPU driver 或修改系統。它只做 probe、提供相容建議、安裝受信任 user-space runtime/model，失敗時保留既有 active model。

啟動順序：prerequisite/device probe → DB migration → local supervisor（如需）→ model endpoint health/probe → media/audio → frontend → smoke test。

Health check 分別回報 DB、camera、frame buffer、vision loop、audio、每個 endpoint/model、analysis、Telegram、model store、scheduler。Shutdown 停止新 job、處理或取消 current job、flush SQLite，再停止 endpoint；local runtime 單獨失效不得拖垮歷史 API。
