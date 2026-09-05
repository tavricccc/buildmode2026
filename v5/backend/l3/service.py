"""L3 service: escalation-only deep analysis (v5 01 §L3, v5 00 item 9).

Two guarantees this module owns:

*Video reaches the model.* v5 01 says MiniMax must see the clip itself,
not a Gemini summary. If the clip is missing we do not quietly send text
and call it an analysis — we set ``degraded_text_only``, say so in the
prompt, and record it so it shows in SQLite and the UI.

*L3 cannot block the pipeline.* Every failure returns an ``L3Result``
with a call record; nothing raises past this boundary. v5 00 item 9: a
MiniMax timeout must leave L1, L2, the state machines, SQLite and the
Dashboard running.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..domain.enums import L3Outcome, Layer
from ..domain.ids import content_hash
from ..domain.l3_contract import DeeperAnalysis, EvidenceBundle
from ..domain.model_call import ModelCall
from ..domain.schema import SchemaError
from ..jsonio import JsonExtractionError, extract_json
from .minimax_client import MiniMaxError
from .prompt import SYSTEM_INSTRUCTION, analysis_prompt, repair_prompt

PROMPT_VERSION = "l3.analysis.v1"


@dataclass
class L3Result:
    analysis: DeeperAnalysis | None
    call: ModelCall
    outcome: L3Outcome
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.analysis is not None


class L3Service:
    def __init__(self, backend: Any, provider: str = "minimax", redact: Any = None) -> None:
        self.backend = backend
        self.provider = provider
        self._redact = redact or (lambda text: text)

    def analyse(
        self,
        bundle: EvidenceBundle,
        frames: list[bytes],
        *,
        clip_url: str | None = None,
        allow_text_only: bool = True,
    ) -> L3Result:
        prompt = analysis_prompt(bundle)
        call = ModelCall(
            layer=Layer.l3_minimax.value,
            provider=self.provider,
            model=getattr(self.backend, "model", "unknown"),
            purpose=f"escalation:{bundle.trigger.value}",
            prompt_version=PROMPT_VERSION,
            schema_version=DeeperAnalysis.schema_version,
            input_hash=content_hash(prompt, bundle.escalation_id, str(len(frames))),
        )

        degraded = bundle.degraded_text_only or not frames
        if degraded and not allow_text_only:
            call.status = "failed"
            call.error_code = "no_video_evidence"
            call.error_message = "clip unavailable and text-only fallback is disabled"
            return L3Result(None, call, L3Outcome.failed, call.error_message)

        seed = getattr(self.backend, "set_bundle", None)
        if seed is not None:
            seed(bundle)

        parts: list[dict[str, Any]] = [self.backend.text_part(prompt)]
        if not degraded:
            try:
                parts.extend(self.backend.video_parts(frames, clip_url))
            except MiniMaxError as exc:
                degraded = True
                call.error_message = f"video encode failed, degraded to text: {exc.message}"

        outcome = L3Outcome.degraded_text_only if degraded else L3Outcome.called

        started = time.perf_counter()
        try:
            response = self.backend.analyse(parts, system_instruction=SYSTEM_INSTRUCTION)
        except MiniMaxError as exc:
            return self._fail(call, exc.code, exc.message, int((time.perf_counter() - started) * 1000))
        except Exception as exc:  # noqa: BLE001 - L3 must never propagate
            return self._fail(call, "unexpected_error", str(exc), int((time.perf_counter() - started) * 1000))

        call.latency_ms = response.latency_ms
        call.prompt_tokens = response.prompt_tokens
        call.output_tokens = response.output_tokens
        call.total_tokens = response.total_tokens
        call.response_text = self._redact(response.text)[:4000]

        analysis, error = _parse(response.text)
        if analysis is not None:
            call.status = "ok"
            return L3Result(analysis, call, outcome, bundle.describe())

        if response.truncated:
            return self._fail(call, "max_tokens", "response truncated by output limit", call.latency_ms)

        call.attempts = 2
        try:
            repaired = self.backend.analyse(
                [self.backend.text_part(repair_prompt(response.text, error))],
                system_instruction=SYSTEM_INSTRUCTION,
            )
        except MiniMaxError as exc:
            return self._fail(call, exc.code, f"repair failed: {exc.message}", call.latency_ms)

        call.latency_ms += repaired.latency_ms
        call.total_tokens = (call.total_tokens or 0) + (repaired.total_tokens or 0)
        call.response_text = self._redact(repaired.text)[:4000]

        analysis, error2 = _parse(repaired.text)
        if analysis is not None:
            call.status = "repaired"
            return L3Result(analysis, call, outcome, bundle.describe())

        call.status = "invalid"
        call.error_code = "schema_invalid"
        call.error_message = f"first: {error} | after repair: {error2}"
        return L3Result(None, call, L3Outcome.failed, call.error_message)

    def _fail(self, call: ModelCall, code: str, message: str, latency_ms: int) -> L3Result:
        call.status = "failed"
        call.error_code = code
        call.error_message = self._redact(message)[:600]
        call.latency_ms = latency_ms
        return L3Result(None, call, L3Outcome.failed, f"{code}: {call.error_message}")


def _parse(text: str) -> tuple[DeeperAnalysis | None, str]:
    try:
        payload = extract_json(text)
    except JsonExtractionError as exc:
        return None, f"extraction: {exc}"
    try:
        return DeeperAnalysis.parse(payload), ""
    except SchemaError as exc:
        return None, f"schema[{exc.code}] {exc}"


def build_minimax_l3(api_key: str, model: str, base_url: str, timeout_sec: float,
                     wire_format: str, max_frames: int, redact: Any = None) -> L3Service:
    from .minimax_client import MiniMaxClient

    client = MiniMaxClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_sec=timeout_sec,
        wire_format=wire_format,
        max_frames=max_frames,
    )
    return L3Service(client, provider="minimax", redact=redact)


def build_local_vllm_l3(api_key: str, model: str, base_url: str, timeout_sec: float,
                        redact: Any = None, enable_thinking: bool = False) -> L3Service:
    from ..local_vllm import LocalVllmClient

    client = LocalVllmClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_sec=timeout_sec,
        enable_thinking=enable_thinking,
    )
    return L3Service(client, provider="local_vllm", redact=redact)
