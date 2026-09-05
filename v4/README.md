# Care Agent v4 — Hardware-Neutral Skeleton

v4 is the hardware-neutral successor to v3. The full specification lives in
[`../docs-implementation-v4/`](../docs-implementation-v4/README.md). This
directory contains the implementation skeleton:

- `backend/` — Python 3.11+ FastAPI + SQLAlchemy + Pydantic. All domain code is
  vendor-neutral: it never imports `mlx`, `mps`, `cuda`, `rocm`, `torch`, or any
  Apple/Metal-specific module. Hardware differences are confined to the
  `supervisor/` and `adapters/` layers.
- `frontend/` — React + TypeScript + Vite with a Setup Wizard, Settings page
  and Dashboard.
- `scripts/` — Bun orchestration (`bun start`, `bun run migrate`,
  `bun run verify`).
- `data/` — model catalog and replay manifests (no model weights are
  downloaded in this round).
- `backend/stub/` — a local OpenAI-compatible mock server that lets the
  Model Gateway and capability probes run end-to-end without a real LLM.

## Quick start

```bash
cd v4
bun install
bun run setup:backend
bun run migrate
bun start
```

`bun start` brings up the backend on `http://localhost:8000`, the stub OpenAI
server on `http://localhost:18181`, and the Vite frontend on
`http://localhost:5173`.

## Verify

```bash
bun run verify
```

Runs the Python unit tests and the frontend typecheck.

## What this round covers

- Every directory, every Pydantic schema, every Protocol, every SQLAlchemy
  model, every state-machine, every API route.
- The stub OpenAI server, the migrations runner, the settings/versioning
  service, the secret store, the WebSocket broadcaster.
- The 8-step Setup Wizard, the Settings page (with the write-only
  `SecretInput`) and the Dashboard.
- 19 unit tests, including the **hardware-neutral guard**
  (`test_health_neutral.py`) that greps the entire `backend/` tree and fails if
  any Apple/GPU-vendor identifier leaks into domain code.

## What is intentionally NOT in this round

- Real model runtime integration (llama.cpp / vLLM / Ollama / MLX).
- Real RTSP camera / microphone capture (the existing `capture/` package is
  the separate CLI used during host bootstrap).
- Real Telegram long-polling.
- End-to-end Replay→Event→SQLite→WebSocket→Dashboard walkthrough (that is the
  next commit).
- Captured-bundle ingestion bridge.
