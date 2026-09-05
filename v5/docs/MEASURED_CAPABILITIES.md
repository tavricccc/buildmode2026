# Measured provider capabilities

_Measured 2026-09-05. Re-run with `bun run probe:gemini` / `bun run probe:minimax`._

v5 04 sets the rule this file exists to keep:

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
  Dashboard were unaffected (v5 00 item 9).
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

`scripts/probe_gemini.py` covers auth and model listing, JSON-only output
validated against `GeminiObservation`, a clip through `inline_data`, the
resumable Files API including the ACTIVE poll, native audio input, and
the error shape for a bad model id.

**Not yet measured** — no Gemini key was configured on the machine that
ran the L3 probe. Until it is, treat the L2 numbers in the spec as
unverified, and in particular do not assume native audio works: v5 01 is
explicit that "一定理解音訊" may not be written into runtime assumptions
without measurement, which is why the probe reports what the model said
about a 440 Hz test tone rather than what a docs page claims.

Run it with:

```bash
bun run probe:gemini -- --key-file /path/to/key
```

## What the code does with all this

| Measurement | Where it is encoded |
|---|---|
| Frames beat `video_url` | `WIRE_FORMAT_FRAMES` default, `backend/l3/minimax_client.py` |
| Explicit UA needed | `USER_AGENT` in both clients |
| Truncation must fail loudly | `context_length_exceeded_behavior="error"` |
| Provider JSON is not guaranteed | `backend/jsonio.py` + one repair attempt |
| Audio is unproven | never sent as a runtime assumption; probe-gated |
| Rate limits happen | L3 failure is contained; the cascade continues |
