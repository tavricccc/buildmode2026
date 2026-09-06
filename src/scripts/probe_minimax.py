#!/usr/bin/env python3
"""Measure what this MiniMax deployment can actually do (docs/04_SETUP_DEPLOY_VERIFY.md).

The load-bearing check is #3: docs/01_PIPELINE.md requires L3 to see the clip *and* the
structured text in one request. A deployment that silently drops one of
them turns every escalation into a confident opinion about evidence the
model never received, which is worse than no escalation at all.
"""

from __future__ import annotations

import json
import sys

from _probe_common import (  # noqa: E402
    Check, Report, base_parser, clip_frames, make_clip, read_key, timed,
)

from backend.config import default_l3  # noqa: E402
from backend.domain.enums import EscalationTrigger  # noqa: E402
from backend.domain.l3_contract import DeeperAnalysis, EvidenceBundle  # noqa: E402
from backend.domain.schema import SchemaError  # noqa: E402
from backend.jsonio import JsonExtractionError, extract_json  # noqa: E402
from backend.l3.minimax_client import MiniMaxClient, MiniMaxError  # noqa: E402
from backend.l3.prompt import SYSTEM_INSTRUCTION, analysis_prompt  # noqa: E402

#: A token this only appears in the text part. If the reply cannot use it,
#: the text half of a multimodal request did not survive the wire.
CANARY = "ZEBRA-7741"


def main() -> int:
    parser = base_parser("Probe a MiniMax deployment's real capabilities")
    parser.add_argument("--wire-format", default="frames", choices=["frames", "video_url"])
    parser.add_argument("--frames", type=int, default=10)
    args = parser.parse_args()

    config = default_l3()
    model = args.model or config.model
    base_url = args.base_url or config.base_url
    client = MiniMaxClient(read_key("MINIMAX_API_KEY", args), model=model, base_url=base_url,
                           timeout_sec=args.timeout, wire_format=args.wire_format,
                           max_frames=args.frames)

    report = Report("minimax", model)
    print(f"Probing {base_url} · {model} · wire format '{args.wire_format}'\n")

    # 1. auth + model availability
    models, latency, error = timed(client.list_models)
    if error is not None:
        report.add(Check("auth / list models", False, str(error), latency))
        if isinstance(error, MiniMaxError) and error.code == "forbidden":
            print("\n  Note: a 403 here can be a gateway rejecting the client rather than\n"
                  "  the key. This client sends an explicit User-Agent for that reason.")
        return report.summarise()
    report.add(Check("auth / list models", True, f"{len(models)} models visible", latency))
    report.add(Check(f"configured model '{model}' is listed", model in models))

    # 2. structured output
    response, latency, error = timed(lambda: client.analyse(
        [client.text_part('Reply with {"interpretation": "ok", "risk_level": "none", '
                          '"recommendation": "no_action"} exactly.')],
        system_instruction="Reply with a single JSON object."))
    if error is not None:
        report.add(Check("json_object structured output", False, str(error), latency))
    else:
        ok, detail = _validate(response.text)
        report.add(Check("json_object structured output", ok, detail, latency))

    # 3. video AND text in one request — the requirement docs/01_PIPELINE.md turns on
    try:
        clip = make_clip(5.0)
        frames = clip_frames(clip, args.frames)
    except Exception as exc:  # noqa: BLE001
        report.add(Check("build a test clip with ffmpeg", False, str(exc)))
        return report.summarise()
    report.add(Check("build a test clip with ffmpeg", True,
                     f"{len(frames)} frames · {clip.stat().st_size / 1e6:.2f} MB"))

    bundle = EvidenceBundle(
        escalation_id="probe", trigger=EscalationTrigger.manual,
        reason_codes=["possible_fall"],
        l2_observation={"person_visible": True, "probe_canary": CANARY},
        event_state={"fall": {"status": "suspect"}},
        clip=None,
    )
    prompt = (analysis_prompt(bundle) +
              f"\n\nBefore anything else, copy the value of probe_canary into "
              f'interpretation, exactly. It is "{CANARY}".')
    try:
        parts = [client.text_part(prompt), *client.video_parts(frames)]
    except MiniMaxError as exc:
        report.add(Check("encode video parts", False, str(exc)))
        return report.summarise()

    response, latency, error = timed(lambda: client.analyse(
        parts, system_instruction=SYSTEM_INSTRUCTION))
    if error is not None:
        report.add(Check("video + text in one request", False, str(error), latency))
    else:
        saw_text = CANARY in response.text
        report.add(Check("video + text in one request", saw_text,
                         f"canary {'echoed' if saw_text else 'NOT echoed — the text part may have been dropped'}"
                         f" · {response.total_tokens} tokens", latency))
        ok, detail = _validate(response.text)
        report.add(Check("multimodal reply satisfies DeeperAnalysis", ok, detail))

    # 4. does the token count actually rise with the images attached?
    text_only, latency_a, error_a = timed(lambda: client.analyse(
        [client.text_part(prompt)], system_instruction=SYSTEM_INSTRUCTION))
    if error_a is None and error is None:
        delta = (response.prompt_tokens or 0) - (text_only.prompt_tokens or 0)
        report.add(Check("images measurably reach the model", delta > 50,
                         f"prompt tokens with frames {response.prompt_tokens} vs "
                         f"text only {text_only.prompt_tokens} (delta {delta})"))
    else:
        report.add(Check("images measurably reach the model", False,
                         "could not compare token counts", skipped=True))

    # 5. error shape
    _, latency, error = timed(lambda: client.analyse(
        [client.text_part("hi")], model="definitely-not-a-model"))
    report.add(Check("bad model id returns a structured error",
                     isinstance(error, MiniMaxError), f"{type(error).__name__}: {error}", latency))

    return report.summarise()


def _validate(text: str) -> tuple[bool, str]:
    try:
        payload = extract_json(text)
    except JsonExtractionError as exc:
        return False, f"not JSON: {exc}"
    try:
        DeeperAnalysis.parse(payload)
    except SchemaError as exc:
        return False, f"JSON parsed but failed the contract: {exc}"
    return True, "valid DeeperAnalysis"


if __name__ == "__main__":
    sys.exit(main())
