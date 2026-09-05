# Care Agent

[![CI](https://github.com/tavricccc/buildmode2026/actions/workflows/ci.yml/badge.svg)](https://github.com/tavricccc/buildmode2026/actions/workflows/ci.yml)

An eldercare monitoring pipeline that watches a single resident's home for
falls and hydration, and spends as little as possible doing it.

The specification of record is [`../docs/`](../docs/README.md).
This directory is the implementation.

## The idea

An earlier iteration abstracted every model behind one OpenAI-compatible
serving runtime. That abstraction cost more than it bought: it forced
Gemini into a shape it does not speak, and it meant every window paid for
the most expensive model available.

This one replaces it with three fixed layers, each doing the cheapest thing that
is sufficient:

```
RTSP / Replay
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ L1 · local person gate            cost: ~0                  │
│ "is a person in frame?" — and nothing else                  │
└─────────────────────────────────────────────────────────────┘
      │ no person → skip, but keep a sparse safety heartbeat
      │ person, or L1 unhealthy, or a fall being tracked
      ▼
┌─────────────────────────────────────────────────────────────┐
│ L2 · local vLLM / Nemotron        cost: per window          │
│ structured observation + an explicit escalation decision    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼  deterministic state machines
      │  fall:      idle → suspect → confirmed → recovering → resolved
      │  hydration: idle → suspect → confirmed → active → completed
      │
      │ escalation.required, or a high-risk state
      ▼
┌─────────────────────────────────────────────────────────────┐
│ L3 · same local vLLM model        cost: per escalation      │
│ sees the clip itself, may contradict L2, recommends only    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ Deterministic Policy Gateway                                │
│ the only place an action is authorised — no model reaches   │
│ a threshold, a channel or a recipient                       │
└─────────────────────────────────────────────────────────────┘
      │
      ▼   SQLite → WebSocket → Dashboard / Telegram
```

## Three rules the code is built to make unbreakable

**A broken detector is not an empty room.** `L1Decision` is four-valued —
`person_present`, `no_person`, `stale`, `unavailable` — and only a fresh,
healthy `no_person` may authorise a skip. Staleness, an unavailable
detector, a degraded one, and a cold start all fail open toward spending a
model call. `L1Decision.permits_skip()` is the single predicate, and there
is a test asserting it returns `True` for exactly one member of the enum.

**A model may argue; only policy acts.** `DeeperAnalysis` has no
recipient, no channel and no threshold field — not as a convention, but
because those keys do not exist in the contract. When L3 recommends
contacting a caregiver and the operator has not enabled
`notify_on_l3_high_risk`, the recommendation surfaces as a dashboard alert
with the rule name `l3_advisory_not_authorised`. It is downgraded, and the
downgrade is recorded; it is never silently dropped.

**Every window is reconstructible.** One `pipeline_runs` row per window —
including the skipped ones — carries the L1 decision, why L2 was called or
skipped, whether it escalated and why, whether L3 ran, was degraded to
text-only or failed, the latencies, the model ids, the config version and
the evidence reference. Open an event from System Maintenance and you get
that path back, sourced entirely from the audit tables.

## Quick start

Requirements: **Python 3.11+**, **bun**, **ffmpeg**. No pip install, no
virtualenv, no model download — the backend imports only the Python
standard library, which is what lets a fresh clone reach the Setup UI on
Windows/WSL, macOS or Linux with nothing else installed.

```bash
cd src
bun install
bun run migrate          # create data/care.sqlite3
bun start                # http://127.0.0.1:8200
```

Both L2 and L3 are provider-selectable: local vLLM is available for either
slot, while the currently implemented and recommended cloud combination is
Gemini for L2 and MiniMax for L3. A fresh checkout still starts with one local
vLLM OpenAI-compatible endpoint (`VLLM_BASE_URL`, model `nemotron_omni`) so
the process can boot without cloud credentials. Use `--stubs` when vLLM is
unavailable; the stubs reproduce the provider
contracts so schema validation, repair, state machines, escalation and the
audit trail can still be exercised:

```bash
bun start -- --source fall     # or: empty_room, hydration, l1_false_negative
bun start -- --stubs --source fall  # offline contract trial
```

The care API uses port 8200 so it does not collide with local vLLM on port
8000. Switch to the recommended cloud combination with
`L2_PROVIDER=gemini L3_PROVIDER=minimax` and configure both keys. The same
provider choices are available from Settings.

```bash
bun run verify           # compile check + 128 tests + frontend typecheck
bun run probe:gemini     # measure what this Gemini deployment can do
bun run probe:minimax    # measure what this MiniMax deployment can do
```

### If the frontend build fails on macOS

Two failures here are the machine, not the code.

`ERR_DLOPEN_FAILED … library load disallowed by system policy` from rollup
or `Error: The service was stopped` from esbuild means Gatekeeper is
refusing the prebuilt native binaries `bun install` just unpacked: a
checkout made by a quarantining client (Sourcetree, a browser download)
passes `com.apple.quarantine` on to everything written under it. Clear it
for this project's dependencies and rebuild:

```bash
xattr -dr com.apple.quarantine node_modules frontend/node_modules
```

`OSError: [Errno 48] Address already in use` means something else already
holds port 8200. The port is host-managed, so pass it in the environment
rather than editing config:

```bash
CARE_PORT=8210 bun start
```

## Layout

```
backend/
  domain/        contracts and thresholds — no I/O, no provider knowledge
  media/         ring buffer, RTSP/replay sources, the only ffmpeg caller
  l1/            person detectors (stub · motion · YOLO11n) + the gate
  l2/            Gemini native REST client, prompt, service, offline stub
  l3/            MiniMax OpenAI-compatible client, prompt, service, stub
  cascade/       the scheduler, the bounded queues, the orchestrator
  state_machines/ pure fall and hydration transitions
  policy/        the Policy Gateway
  store/         SQLite schema, migrations, repositories
  api/           REST routes, the HTTP server, the RFC 6455 upgrade
  notify/        Telegram delivery and acknowledgement
  observer/      daily rollups and baseline comparison
  tests/         128 tests, including docs/04_SETUP_DEPLOY_VERIFY.md's required-scenario list
frontend/        React + TypeScript care dashboard, trends and maintenance UI
scripts/         bun orchestration and the capability probes
data/replays/    annotated scenarios — no camera or video file needed
```

## Choosing an L1 detector

| id | Install | Honest limitation |
|---|---|---|
| `stub` | none | Reads replay ground truth. Fixtures and tests only. |
| `motion` | none | FFmpeg frame differencing. **Cannot see a motionless person.** |
| `yolo11n` | `onnxruntime` + weights | The real one. Downloaded from Setup, never at startup. |

The motion detector's weakness is exactly the case that matters, so the
system is built to survive it structurally rather than to pretend
otherwise: leaving "present" takes twice as many readings as entering it,
an empty room still gets a sparse heartbeat, and a tracked fall bypasses
L1 completely.

## What is verified, and how

`bun run verify` runs 128 tests. The scenario classes in
`backend/tests/test_cascade.py` map one-to-one onto docs/04_SETUP_DEPLOY_VERIFY.md's 必測情境 list,
and run the real cascade against the real SQLite schema with only the
model backends stubbed:

| Scenario | Asserted |
|---|---|
| Empty room | Most windows skipped; the sparse heartbeat still calls L2 |
| L1 crash | Fails open; the fall is still caught while the detector is down |
| Fall suspect | Forced follow-ups bypass L1; hydration deliberately does not |
| Escalation | L3 receives frames **and** the structured reading |
| MiniMax timeout | Events, SQLite and deterministic policy keep working |
| Gemini timeout | Event state is **not** advanced — an unread window is not a safe one |
| Replay re-run | Hydration is not double-counted; dedup keys stay unique |
| Secret scan | A canary key never appears in `/api/status` or `/api/settings` |
| Config rollback | A new version is created and can be rolled back |

Live measurements against both real deployments are in
[`../docs/measured-capabilities.md`](../docs/measured-capabilities.md): Gemini
9/9 including native audio input, MiniMax 8/8 including the token-delta
evidence that the frames actually reach the model, and the runs where each
model correctly refused to confirm what it could not see.

One consequence is worth reading before trusting a green scenario: the
scripted replay fixtures exercise **contracts, not vision**. Their frames
are blank placeholders, so a real L2 correctly reports `occluded_view` and
creates no event; only the stub L2 drives the fall and hydration state
machines to `confirmed`. Validating semantics needs real footage.

## Secrets

API keys, the RTSP password and the Telegram token live in the backend
secret store (`data/secrets.json`, 0600) or the process environment. They
are never returned by any endpoint: `SecretStore.describe()` reports
`configured` / `source` / `length` and nothing else, and `redact()` runs
over every string bound for a log, an error response or a SQLite row —
because providers echo request context into their error bodies, which is a
realistic way for a key to end up in a database.

## Status

Implemented and verified: the full L1 → L2 → L3 → Policy cascade, the
original-flow-compatible change gate, browser WebM/audio ingress, Main Agent,
memory candidates and resident interaction, both state machines, the SQLite
schema with `pipeline_runs`, the REST API and WebSocket push, the care-first
Dashboard, health trends, one-click L3 period review, a separate maintenance
page with the three-layer panel and cascade trace, Setup and Settings with
versioning and rollback, Telegram delivery, the daily observer, RTSP and
replay ingest, and both capability probes.

Known gaps: the audio/ASR path is specified and has its storage and
retention in place, but no ASR engine is wired in; the YOLO11n detector
needs `onnxruntime` and weights that Setup does not yet fetch
automatically.


## License

Copyright (C) 2026 Artificial Illusion

Care Agent is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

The full text is in [`../LICENSE`](../LICENSE). Every runtime dependency is
MIT, ISC, BSD-3-Clause or Apache-2.0, all of which GPL-3.0 permits.
