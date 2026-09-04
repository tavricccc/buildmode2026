# 13 · 前端設定、Provider 與模型管理

## 統一安裝流程

使用者在 `/setup/models` 選擇 capability：vision、transcription、analysis、可選 speech/embedding，再選來源：

### Local catalog

1. Backend probe OS、AMD/NVIDIA/CPU、RAM/VRAM、driver/runtime。
2. 前端只選 allowlisted catalog ID、quantization/runtime/device；不得輸入 URL/path/package。
3. 建立可取消、可恢復 job，下載 weights/runtime、驗證 checksum/revision。
4. 啟動 localhost OpenAI-compatible server，執行 `/v1/models` 與 capability fixture probe。
5. 成功後寫入 installed model；使用者明確按「啟用」才切換 active slot。

### Cloud provider

1. 前端輸入 display name、HTTPS base URL、API key 與受限 custom headers。
2. Backend 測試 auth並列出 models；若不支援 listing，可手動輸入 remote model ID。
3. 選擇 capability，執行相同 fixture probe。
4. 成功後將 endpoint/model 加入 installed registry；不下載遠端 weights。

所有模型無論來源，runtime 呼叫都必須經 Model Gateway 使用 OpenAI-compatible API。私有 provider 差異只能存在於明示且受測的 adapter mode，不能讓 domain code分支。

## 前端設定保證

日常運作所需設定原則上都能從前端修改：models/endpoints、device/runtime、camera/audio、vision sampling、cost/rate limits、timeouts/retries、events/policy、hydration、analysis、Observer、retention、Telegram、locale/timezone。

例外只限 host bootstrap/security：DB/media root、server bind/port、secret store、OS service account、GPU driver。前端仍需顯示其值的安全摘要、health、restart requirement 與修正說明。

設定流程固定為 draft → schema validation → integration test → impact preview → apply new config version → targeted restart/reload → health verification。失敗自動保留前版；可從前端 rollback。

Secret GET 永遠只回 configured/updated/fingerprint suffix。模型下載來源由 backend catalog allowlist 控制；cloud URL 需 SSRF 防護。安裝、啟用、刪除、rollback 與高風險 policy 修改都寫 audit log。

## 驗收

1. 前端能各安裝一個 local vision model 與 cloud vision model，切換後不用改 code。
2. Vision、transcription、analysis 均能選 local 或 cloud endpoint並通過相同 contract tests。
3. NVIDIA/AMD/CPU 不相容選項會被阻擋並說明原因。
4. 中斷下載可恢復；probe/activation 失敗不破壞 active model。
5. Secret 不回填、不進 logs；設定可版本化與 rollback。
6. 除明列 host-managed 項目外，完整配置不需手改 `.env`。
