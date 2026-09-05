# Measured provider capabilities

_Measured 2026-09-05, both providers against live deployments.
Re-run with `bun run probe:gemini` / `bun run probe:minimax`._

docs/04_SETUP_DEPLOY_VERIFY.md sets the rule this file exists to keep:

> Provider 文件沒保證的能力，不可直接寫成 runtime 假設，以 probe 結果為準。

Everything below is what the probes actually observed against a live
deployment. Where a measurement contradicts a vendor doc, the measurement
wins and the code follows the measurement.

## L3 · MiniMax M3 via GMI Cloud

Endpoint `https://api.gmi-serving.com/v1`, model `MiniMaxAI/MiniMax-M3`,
wire format `frames`, 10 frames per request.

| Check | Result | Measurement |
|---|---|---|
| Auth / list models | ✅ | 83 models visible, 1,325 ms |
| Configured model is listed | ✅ | `MiniMaxAI/MiniMax-M3` present |
| `json_object` structured output | ✅ | parsed and satisfied `DeeperAnalysis` |
| **Video + text in one request** | ✅ | text-part canary echoed back, 1,826 tokens, 7,659 ms |
| Multimodal reply satisfies the contract | ✅ | valid `DeeperAnalysis` |
| **Images measurably reach the model** | ✅ | prompt tokens **1,594 with frames vs 584 text-only — delta 1,010** |
| Bad model id returns a structured error | ✅ | `model_not_found` |

The token-delta check is the one that matters. A provider can accept an
`image_url` part, return a plausible answer, and never have shown the
model a pixel. Comparing prompt-token counts between an identical request
with and without the frames is the cheapest evidence that the images were
actually consumed.

### Why frames and not `video_url`

`WIRE_FORMAT_FRAMES` is the default in `backend/l3/minimax_client.py`.
OpenAI-compatible gateways advertise a `video_url` content part, but what
reaches the model behind one is deployment-dependent and can be silently
decimated — and a silently decimated clip is indistinguishable from a
complete one in the response. Sending an evenly sampled `image_url`
sequence means the frame count the model receives is the count we chose.
`video_url` stays selectable (`--wire-format video_url`) so a specific
deployment can be re-measured; it needs a clip URL the provider can
reach, which a local install does not have.

### Observed operational behaviour

- **Rate limiting is real.** During an end-to-end run one escalation came
  back `rate_limited: All endpoints are currently overloaded`, 747 ms.
  The pipeline continued: the window recorded `l3_outcome=failed` with
  the provider's code, and L1, L2, the state machines, SQLite and the
  Dashboard were unaffected (docs/00_SCOPE_AND_DEFINITION_OF_DONE.md item 9).
- **An explicit `User-Agent` is required.** Gateways in front of these
  deployments reject the default `urllib` UA with a 403 that reads
  exactly like an auth failure. The client always sends one.
- **`context_length_exceeded_behavior` is sent as `error`.** The
  alternative is silent truncation, and a truncated escalation looks like
  a considered answer about evidence the model never saw.

### The model disagrees when it should

In an end-to-end run against the scripted fixture — whose frames are
deliberately blank grey placeholders, with the ground truth carried in
metadata that only the stub L2 reads — real M3 returned:

```
risk_level: high     confidence: 0.2     supports_l2: false
contradicts_l2_reason: "The provided frames are entirely blank/uniform and
  contain no visible person, floor, or scene. The L2 report's claim of a
  person lying motionless on the floor at 0.9 confidence cannot be
  substantiated from the evidence I received."
uncertainty: [..., "Possible mismatch between the feed the L1/L2 model saw
  and the frames delivered to L3"]
```

That is the escalation layer earning its cost. It saw what was actually
sent, refused to rubber-stamp a confident upstream claim, and diagnosed
the real situation — the stub L2 had read an annotation rather than the
pixels. The Policy Gateway then downgraded the recommendation to a
dashboard alert, because `notify_on_l3_high_risk` was not enabled.

## L2 · Gemini

Endpoint `https://generativelanguage.googleapis.com/v1beta`, model
`gemini-3.5-flash-lite`, the config default.

| Check | Result | Measurement |
|---|---|---|
| Auth / list models | ✅ | 50 models visible, 168 ms |
| Configured model is listed | ✅ | `gemini-3.5-flash-lite` present |
| Text-only structured output | ✅ | parsed and satisfied `GeminiObservation`, 1,250 ms |
| Video via `inline_data` | ✅ | valid `GeminiObservation`, 1,078 tokens, 2,003 ms |
| Files API upload + ACTIVE poll | ✅ | `files/61oefbfik45a` reached `ACTIVE` in 5,936 ms |
| Generate from a `file_uri` | ✅ | valid `GeminiObservation`, 2,342 ms |
| **Native audio input** | ✅ | see below |
| Bad model id returns a structured error | ✅ | `model_not_found`, 121 ms |

9/9. The JSON parser never had to repair a response across the probe or
the end-to-end run below.

### Native audio is now measured

docs/01_PIPELINE.md is explicit that 「一定理解音訊」 may not be written into runtime
assumptions without measurement. It has now been measured. Sent a 4 s clip
carrying a continuous 440 Hz sine tone, the model answered:

```json
{"audio_heard": true,
 "description": "A continuous 440 Hz sine tone is playing on the audio track."}
```

It described the tone rather than restating the prompt, which is the part
that distinguishes a model that received the audio track from one that
inferred an answer from the wording. Audio may now be relied on for this
deployment — and only this one; the probe is the evidence, so re-run it
against any other endpoint before assuming the same.

### End-to-end with both layers real

`CARE_PORT=8010 bun start -- --source fall`, no stubs on either slot
(`providers.l2.stub=false`, `providers.l3.stub=false`):

| | Measurement |
|---|---|
| L2 windows | 12 (11 `called`, 1 `heartbeat`) |
| L2 latency | 1,241 / 1,731 / 2,337 ms (min/avg/max) |
| L2 repairs, L2 errors | 0, 0 |
| L3 escalations | 1 called, 11 `not_required` |
| L3 latency | 6,434 ms, `risk_level: none`, no error |

### The scripted fixtures test contracts, not vision

Real Gemini returned `escalation.reasons = [occluded_view,
low_confidence]` on every window of the `fall` scenario, and **no fall
event was created**. That is the correct answer, not a regression: the
scripted replay frames are 64×64, 242-byte grey placeholders, and the
ground truth lives in metadata that only the stub L2 reads. Asked what it
could actually see, the model said "not enough", escalated on degraded
evidence — which is what the escalation path is for — and M3 then agreed
there was nothing to act on.

This is the same effect already recorded for M3 above, now confirmed one
layer earlier, and it bounds what the fixtures can prove:

* They **do** exercise contracts, schema validation, the queues, the state
  machines, escalation routing, SQLite and the audit trail against live
  providers.
* They **cannot** exercise fall or hydration *semantics* against a real
  model, because there is nothing in the pixels to see. Only the stub L2
  drives those state machines to `confirmed`.

Validating the semantic layer needs real footage — an RTSP feed or a
recording through `replay_file` — not a scripted fixture.

## What the code does with all this

| Measurement | Where it is encoded |
|---|---|
| Frames beat `video_url` | `WIRE_FORMAT_FRAMES` default, `backend/l3/minimax_client.py` |
| Explicit UA needed | `USER_AGENT` in both clients |
| Truncation must fail loudly | `context_length_exceeded_behavior="error"` |
| Provider JSON is not guaranteed | `backend/jsonio.py` + one repair attempt |
| Audio works on this Gemini deployment | measured, not assumed; re-probe any other endpoint |
| Rate limits happen | L3 failure is contained; the cascade continues |
