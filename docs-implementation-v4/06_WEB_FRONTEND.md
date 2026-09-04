# 06 · Web Dashboard、Setup 與 Settings

Dashboard 保留 v3 的 live/replay video、health、hydration、analysis、timeline、logs、agent trace、Observer 與 Telegram 狀態。模型狀態顯示 deployment type、endpoint/model、latency、queue、rate limit、runtime/device 與最近 probe。

## Setup Wizard

1. Runtime：Python/Bun、FFmpeg、磁碟、camera/mic、AMD/NVIDIA/CPU capability。
2. Model source：選擇本地 catalog 或新增 OpenAI-compatible cloud endpoint。
3. Vision：選擇並安裝 model，執行 image + structured-output probe後啟用。
4. ASR：選擇並安裝 model，執行 `/v1/audio/transcriptions` probe後啟用。
5. Analysis：選擇並安裝 model，執行 structured-output probe後啟用。
6. 可選 TTS：安裝並測試 `/v1/audio/speech`，或保持 disabled。
7. Camera/audio、loop、事件、飲水、Observer、retention、Telegram。
8. Review：本地下載大小或 cloud data destination、請求頻率、變更摘要、secret 狀態。

「安裝雲端模型」不下載權重；它會驗證 endpoint/model/capability 並加入 registry。「安裝本地模型」才會下載權重並建立本地 endpoint。兩者後續選擇和切換體驗一致。

## 前端可修改範圍

必須可改：endpoint/profile、active models、本地 runtime/device、camera credential、source、frame/JPEG/loop、VAD/audio segment、timeout/retry/rate budget、event threshold/cooldown、飲水容量/目標、analysis window、Observer schedule/coverage、retention、Telegram recipient/policy、語言與時區。

只能查看：DB/media absolute root、bind address、secret-store implementation、driver/codec 安裝狀態。這些 host-managed 項目顯示修改說明，不提供任意 path/command。

Secret 欄位只提供保持／覆寫／清除。Apply 前顯示 errors、warnings、受影響服務與 restart；套用後顯示 config version 和 rollback。切換 active model、降低安全 threshold、改 recipient、移除本地 artifact 都需二次確認。
