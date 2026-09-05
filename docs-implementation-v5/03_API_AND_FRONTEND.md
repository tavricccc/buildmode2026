# 03 · Backend API 與 Frontend

## API

核心保留：`/api/status`、`/api/events`、`/api/events/{id}`、`/api/hydration/summary`、`/api/health/current`、replay、transcripts、observer、notifications、settings。

新增：

- `GET /api/pipeline/runs`
- `POST /api/integrations/person-gate/test`
- `POST /api/integrations/gemini/test`
- `POST /api/integrations/minimax/test`
- `POST /api/pipeline/cascade-test`

SQLite commit 後才發 WebSocket；WebSocket 丟失時用 REST resync。

## Dashboard

主畫面保留 video、event timeline、hydration、health、logs、analysis，另外加一個三層 pipeline panel：

- L1：health、last decision、latency、skipped count。
- L2 Gemini：health、last call、latency、calls、heartbeat、escalation count。
- L3 MiniMax：health、last escalation、latency、calls、usage/cost（provider 有回才顯示）。

點 event 可查看完整 cascade trace。

## Setup / Settings

首次啟動：Runtime/FFmpeg/camera/storage check → 選 L1 detector（這時才下載）→ 設 Gemini key/model（預設 `gemini-3.5-flash-lite`）→ 設 MiniMax endpoint/key/model → 分別測三層 → E2E cascade test → 設 cadence、heartbeat、threshold、retention、Telegram、Observer。

Secret 欄位只顯示 configured，不回填原值。Frontend 可改大部分運作設定；DB/media root、bind、secret-store implementation、OS driver 維持 host-managed。

