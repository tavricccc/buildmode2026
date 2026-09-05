# Care Agent 完整程式實作文件 v4

版本：2026-09-04

v4 保留 v3 的事件、資料與安全契約，移除 Apple Silicon 專用假設。部署可使用 AMD、NVIDIA 或 CPU；模型可安裝在本機，也可設定為雲端服務，但應用程式一律透過 OpenAI-compatible API 呼叫。

## 已定案範圍

- RTSP live stream 為正式輸入；ReplaySource 用於測試與備援。
- 視覺、ASR、健康分析及未來 TTS／embedding 都以 capability slot 管理。
- 前端可從受信任 catalog 選擇、下載、驗證、安裝本地模型，或新增雲端 provider/model。
- 本地 runtime 必須暴露 OpenAI-compatible endpoint；domain code 不直接 import MLX、CUDA、ROCm、PyTorch 或 vendor SDK。
- AMD/NVIDIA 差異封裝在 runtime installer/launcher；支援 CPU fallback，不依賴 Apple Metal、MLX 或 unified memory。
- 絕大部分設定由 `/setup` 和 `/settings` 管理，驗證後保存為不可變 config version。

## 文件順序

1. [產品範圍與完成定義](00_SCOPE_AND_DEFINITION_OF_DONE.md)
2. [系統元件、技術棧與邊界](01_SYSTEM_COMPONENTS_AND_BOUNDARIES.md)
3. [事件、Agent、Policy 與設定契約](02_EVENT_AGENT_AND_POLICY_CONTRACTS.md)
4. [視覺、跌倒與喝水 Pipeline](03_VISION_FALL_AND_HYDRATION.md)
5. [SQLite 資料模型](04_SQLITE_DATA_MODEL.md)
6. [Backend API 與即時通訊](05_BACKEND_API_AND_REALTIME.md)
7. [Web Dashboard、Setup 與 Settings](06_WEB_FRONTEND.md)
8. [健康與風險分析](07_HEALTH_AND_RISK.md)
9. [實作順序與驗證](08_IMPLEMENTATION_AND_VERIFICATION.md)
10. [Live Media、Vision Loop 與 Audio](09_LIVE_MEDIA_VISION_AND_AUDIO.md)
11. [Long-term Observer](10_LONG_TERM_OBSERVER.md)
12. [部署與硬體相容性](11_DEPLOYMENT_AND_OPERATIONS.md)
13. [Telegram L3 通知](12_TELEGRAM_L3_NOTIFICATION.md)
14. [前端設定、Provider 與模型管理](13_SETUP_AND_MODEL_MANAGEMENT.md)
15. [Provider 能力與限制(GMI Cloud / MiniMax-M3)](14_PROVIDER_CONSTRAINTS.md)

## 統一模型介面

```text
Domain job → Model Gateway → OpenAI-compatible endpoint
                              ├─ local runtime (AMD/NVIDIA/CPU)
                              └─ remote cloud provider
```

前端的「安裝」依來源有兩種結果：本地模型會下載 allowlisted weights、建立 runtime 並啟動 localhost endpoint；雲端模型會保存 provider profile、執行 capability probe 並加入 registry，不下載遠端權重。兩者啟用後都產生相同的 model endpoint record。

## 設定原則

- `ui_editable`：model/provider、loop、audio、threshold、retention、Observer、通知等。
- `secret_write_only`：API key、RTSP password、Telegram token，可覆寫／清除但不回填。
- `host_managed`：DB/media root、bind address、secret store、GPU driver；只顯示狀態與修改說明。

交付分 P0/P1/P2 三階段,定義見 [00](00_SCOPE_AND_DEFINITION_OF_DONE.md)。P0 為 cloud-only,vision 輸入為短影片片段而非影格集合。

規格衝突時依序採用 v4 → v3 → v2 → `docs/`。v3 中固定 Qwen、MiniMax、M4、MLX 或 local-only/cloud-only 的描述均由 v4 取代。
