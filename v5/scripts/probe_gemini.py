#!/usr/bin/env python3
"""Measure what this Gemini deployment can actually do (v5 04).

Checks, in the order the cascade depends on them:

1. auth and model availability
2. JSON-only output that our validator accepts
3. a small clip through ``inline_data``
4. the resumable Files API, including the ACTIVE poll
5. native audio input — v5 01 is explicit that "一定理解音訊" may not be
   assumed without measurement, so this reports what happened rather than
   what is documented
6. error shape on a deliberately bad model id
"""

from __future__ import annotations

import sys

from _probe_common import (  # noqa: E402
    Check, Report, base_parser, clip_frames, make_clip, read_key, timed,
)

from backend.config import default_l2  # noqa: E402
from backend.domain.observation import GeminiObservation  # noqa: E402
from backend.domain.schema import SchemaError  # noqa: E402
from backend.jsonio import JsonExtractionError, extract_json  # noqa: E402
from backend.l2.gemini_client import GeminiClient, GeminiError  # noqa: E402
from backend.l2.prompt import SYSTEM_INSTRUCTION, observation_prompt  # noqa: E402


def main() -> int:
    parser = base_parser("Probe a Gemini deployment's real capabilities")
    args = parser.parse_args()

    config = default_l2()
    model = args.model or config.model
    base_url = args.base_url or config.base_url
    client = GeminiClient(read_key("GEMINI_API_KEY", args), model=model,
                          base_url=base_url, timeout_sec=args.timeout)

    report = Report("gemini", model)
    print(f"Probing {base_url} · {model}\n")

    # 1. auth + model availability
    models, latency, error = timed(client.list_models)
    if error is not None:
        report.add(Check("auth / list models", False, str(error), latency))
        return report.summarise()
    report.add(Check("auth / list models", True, f"{len(models)} models visible", latency))
    report.add(Check(f"configured model '{model}' is listed", model in models,
                     "" if model in models else "the call may still work; some deployments hide models"))

    # 2. JSON-only output our validator accepts
    prompt = observation_prompt(4.0, "idle")
    response, latency, error = timed(lambda: client.generate(
        [client.text_part(prompt + "\n\n(No footage this time: report person_visible=false.)")],
        system_instruction=SYSTEM_INSTRUCTION))
    if error is not None:
        report.add(Check("text-only structured output", False, str(error), latency))
    else:
        detail, ok = _validate(response.text)
        report.add(Check("text-only structured output", ok, detail, latency))

    # 3-4. media paths
    try:
        clip = make_clip(4.0)
    except Exception as exc:  # noqa: BLE001
        report.add(Check("build a test clip with ffmpeg", False, str(exc)))
        return report.summarise()
    size_mb = clip.stat().st_size / 1e6
    report.add(Check("build a test clip with ffmpeg", True,
                     f"{clip} · {size_mb:.2f} MB · {len(clip_frames(clip))} frames"))

    response, latency, error = timed(lambda: client.generate(
        [client.text_part(observation_prompt(4.0, "idle")),
         {"inline_data": {"mime_type": "video/mp4",
                          "data": __import__("base64").b64encode(clip.read_bytes()).decode()}}],
        system_instruction=SYSTEM_INSTRUCTION))
    if error is not None:
        report.add(Check("video via inline_data", False, str(error), latency))
    else:
        detail, ok = _validate(response.text)
        report.add(Check("video via inline_data", ok,
                         f"{detail} · {response.total_tokens} tokens", latency))

    uploaded, latency, error = timed(
        lambda: client.wait_active(client.upload_file(clip, "video/mp4", "probe-clip")))
    if error is not None:
        report.add(Check("Files API upload + ACTIVE poll", False, str(error), latency))
    else:
        report.add(Check("Files API upload + ACTIVE poll", True,
                         f"{uploaded.name} · state {uploaded.state}", latency))
        response, latency, error = timed(lambda: client.generate(
            [client.text_part(observation_prompt(4.0, "idle")),
             {"file_data": {"mime_type": uploaded.mime_type, "file_uri": uploaded.uri}}],
            system_instruction=SYSTEM_INSTRUCTION))
        if error is not None:
            report.add(Check("generate from a file_uri", False, str(error), latency))
        else:
            detail, ok = _validate(response.text)
            report.add(Check("generate from a file_uri", ok, detail, latency))
        client.delete_file(uploaded)

    # 5. native audio — measured, never assumed
    try:
        audio_clip = make_clip(4.0, with_audio=True)
    except Exception as exc:  # noqa: BLE001
        report.add(Check("native audio input", False, f"could not build a clip: {exc}", skipped=True))
    else:
        response, latency, error = timed(lambda: client.generate(
            [client.text_part(
                "This clip contains a continuous 440 Hz sine tone on its audio track. "
                'Reply with {"audio_heard": true|false, "description": "<what you heard>"} '
                "and nothing else. Answer false if you received no audio."),
             {"inline_data": {"mime_type": "video/mp4",
                              "data": __import__("base64").b64encode(audio_clip.read_bytes()).decode()}}],
            system_instruction="Reply with a single JSON object."))
        if error is not None:
            report.add(Check("native audio input", False, str(error), latency))
        else:
            try:
                heard = bool(extract_json(response.text).get("audio_heard"))
            except JsonExtractionError:
                heard = False
            report.add(Check("native audio input", heard,
                             f"model reported audio_heard={heard} · raw: {response.text[:160]}",
                             latency))

    # 6. error shape
    _, latency, error = timed(lambda: client.generate(
        [client.text_part("hi")], model="definitely-not-a-model"))
    report.add(Check("bad model id returns a structured error",
                     isinstance(error, GeminiError),
                     f"{type(error).__name__}: {error}", latency))

    return report.summarise()


def _validate(text: str) -> tuple[str, bool]:
    try:
        payload = extract_json(text)
    except JsonExtractionError as exc:
        return f"not JSON: {exc}", False
    try:
        GeminiObservation.parse(payload)
    except SchemaError as exc:
        return f"JSON parsed but failed the contract: {exc}", False
    return "valid GeminiObservation", True


if __name__ == "__main__":
    sys.exit(main())
