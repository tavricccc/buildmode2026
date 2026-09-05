# 05 · Backend API 與即時通訊

v3 的 status、camera、source、event、hydration、health、replay、transcript、observer、notification 與 tool-call API 保留；`local_vlm` 統一改名 `vision_model`。

## Model Endpoint 與安裝 API

| Method | Path | 功能 |
|---|---|---|
| GET/POST | `/api/model-endpoints` | 列出／新增 local 或 cloud OpenAI-compatible endpoint |
| PATCH/DELETE | `/api/model-endpoints/{id}` | 修改或安全移除 endpoint |
| POST | `/api/model-endpoints/{id}/test` | 測 TLS/auth/API compatibility |
| GET | `/api/model-endpoints/{id}/models` | 代理取得 `/v1/models` |
| GET | `/api/models/catalog` | allowlisted 本地模型與 runtime compatibility |
| POST | `/api/models/install` | 安裝本地 artifact 或登錄 cloud model，建立 job |
| GET | `/api/models/installed` | 已安裝模型、能力、probe、active 狀態 |
| POST | `/api/models/{id}/probe` | 重跑 capability probe |
| POST | `/api/models/{id}/activate` | 綁定 vision/analysis/transcription/speech slot |
| DELETE | `/api/models/{id}` | 移除 registry；本地 artifact 需另行確認刪除 |

本地安裝會下載 allowlisted weights、驗證 checksum、選擇 AMD/NVIDIA/CPU runtime、啟動 localhost OpenAI-compatible server。雲端安裝只建立 endpoint/model record。vision、transcription、analysis、speech 各用真實小型 fixture probe；只有成功者能 activate。

## Settings API

- `GET /api/settings/schema`、`GET /api/settings`
- `PATCH /api/settings/draft`、`POST /api/settings/test`
- `POST /api/settings/apply`
- `GET /api/settings/versions`、`POST /api/settings/rollback/{id}`

PATCH/apply 必須帶 base version。禁止任意 SQL、shell、package name、filesystem path 或不受信任的下載 URL。Cloud base URL 預設只允許 HTTPS；localhost endpoint 由 backend 產生，並防 SSRF。

## Realtime 與錯誤

沿用 `/ws` commit-after-broadcast 與 REST resync，新增 `model.install.progress`、`model.probe.completed`、`model.activated`、`endpoint.updated`、`settings.applied`、`settings.rollback.completed`。

錯誤至少區分 `CONFIGURATION_REQUIRED`、`ENDPOINT_AUTH_FAILED`、`MODEL_CAPABILITY_MISMATCH`、`MODEL_SCHEMA_INVALID`、`RATE_LIMITED`、`LOCAL_RUNTIME_FAILED`、`CONFIG_VERSION_CONFLICT` 與 `RESTART_REQUIRED`。
