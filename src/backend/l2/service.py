"""L2 service: one window in, one validated observation out (docs/01_PIPELINE.md §L2).

The only interesting decision here is the repair path. docs/01_PIPELINE.md allows
exactly one repair, and this module spends it on the right thing:

* transport failure   -> no repair. Retrying a timeout with a repair
                         prompt just doubles the outage.
* extraction failure  -> repair. The model answered; the envelope was
                         wrapped in prose or a fence that ``extract_json``
                         could not recover.
* schema violation    -> repair, quoting the exact validator error.
* still invalid       -> status ``invalid``. docs/01_PIPELINE.md: the event state is
                         *not* updated from an invalid observation. A
                         window we could not read is not a safe window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain.enums import Layer
from ..domain.ids import content_hash
from ..domain.l3_contract import VideoClip
from ..domain.model_call import ModelCall
from ..domain.observation import GeminiObservation
from ..domain.schema import SchemaError
from ..jsonio import JsonExtractionError, extract_json
from ..providers import ProviderError
from .gemini_client import GeminiClient, GeminiError, GeminiResponse
from .prompt import SYSTEM_INSTRUCTION, observation_prompt, repair_prompt

PROMPT_VERSION = "l2.observation.v1"


@dataclass
class L2Result:
    observation: GeminiObservation | None
    call: ModelCall

    @property
    def ok(self) -> bool:
        return self.observation is not None


class L2Backend(Protocol):
    """Everything the service needs from a provider."""

    model: str

    def generate(self, parts: list[dict[str, Any]], *, system_instruction: str | None = None,
                 json_output: bool = True, temperature: float = 0.0,
                 max_output_tokens: int = 1024, model: str | None = None) -> GeminiResponse: ...

    def media_part(self, path: str | Path, mime_type: str,
                   cleanup: list[Any] | None = None) -> dict[str, Any]: ...

    @staticmethod
    def text_part(text: str) -> dict[str, Any]: ...


class L2Service:
    def __init__(self, backend: L2Backend, provider: str = "gemini", redact: Any = None) -> None:
        self.backend = backend
        self.provider = provider
        #: SecretStore.redact, or identity in tests
        self._redact = redact or (lambda text: text)

    def observe(
        self,
        clip: VideoClip | None,
        *,
        frames: list[bytes] | tuple[bytes, ...] | None = None,
        audio_pcm: bytes | None = None,
        event_state: str = "idle",
        transcript: str | None = None,
        heartbeat: bool = False,
        purpose: str = "window_observation",
        simulation_context: dict[str, Any] | None = None,
    ) -> L2Result:
        window_sec = clip.duration_sec if clip else 0.0
        prompt = observation_prompt(window_sec, event_state, transcript, heartbeat)
        if simulation_context:
            prompt += (
                "\n\nDEBUG EVALUATION CONTEXT\n"
                + self._redact(str(simulation_context))[:1200]
                + "\nReturn the normal observation contract. The context describes evidence, not an expected answer."
            )
        call = ModelCall(
            layer=Layer.l2_gemini.value,
            provider=self.provider,
            model=self.backend.model,
            purpose=purpose,
            prompt_version=PROMPT_VERSION,
            schema_version=GeminiObservation.schema_version,
            input_hash=content_hash(prompt, clip.path if clip else "no-clip", str(window_sec)),
        )

        # Replay fixtures carry their ground truth on the clip; the stub
        # backend consumes it here so the orchestrator never has to know
        # which backend it is talking to.
        seed = getattr(self.backend, "set_annotation", None)
        if seed is not None:
            seed(clip.annotation if clip else None)

        cleanup: list[Any] = []
        parts: list[dict[str, Any]] = [self.backend.text_part(prompt)]
        try:
            if clip is not None:
                frame_builder = getattr(self.backend, "frame_parts", None)
                if frames and frame_builder is not None:
                    try:
                        parts.extend(frame_builder(frames, clip.mime_type, audio_pcm))
                    except TypeError:
                        parts.extend(frame_builder(frames, clip.mime_type))
                else:
                    parts.append(self.backend.media_part(clip.path, clip.mime_type, cleanup))
        except (ProviderError, OSError) as exc:
            return self._fail(call, "media_upload_failed", str(exc), 0)

        started = time.perf_counter()
        try:
            response = self.backend.generate(parts, system_instruction=SYSTEM_INSTRUCTION)
        except ProviderError as exc:
            return self._fail(call, exc.code, exc.message, int((time.perf_counter() - started) * 1000))
        finally:
            self._cleanup(cleanup)

        call.latency_ms = response.latency_ms
        call.prompt_tokens = response.prompt_tokens
        call.output_tokens = response.candidate_tokens
        call.total_tokens = response.total_tokens
        call.response_text = self._redact(response.text)[:4000]

        observation, error = _parse(response.text)
        if observation is not None:
            call.status = "ok"
            return L2Result(observation, call)

        if response.truncated:
            # Repairing a MAX_TOKENS truncation with the same budget just
            # truncates again; report it honestly instead.
            return self._fail(call, "max_tokens", "response truncated by output limit", call.latency_ms)

        # -- the one permitted repair attempt -------------------------------
        call.attempts = 2
        repair_parts = [self.backend.text_part(repair_prompt(response.text, error))]
        try:
            repaired = self.backend.generate(repair_parts, system_instruction=SYSTEM_INSTRUCTION)
        except ProviderError as exc:
            return self._fail(call, exc.code, f"repair failed: {exc.message}", call.latency_ms)

        call.latency_ms += repaired.latency_ms
        call.total_tokens = (call.total_tokens or 0) + (repaired.total_tokens or 0)
        call.response_text = self._redact(repaired.text)[:4000]

        observation, error2 = _parse(repaired.text)
        if observation is not None:
            call.status = "repaired"
            return L2Result(observation, call)

        call.status = "invalid"
        call.error_code = "schema_invalid"
        call.error_message = f"first: {error} | after repair: {error2}"
        return L2Result(None, call)

    # -- helpers ---------------------------------------------------------

    def _fail(self, call: ModelCall, code: str, message: str, latency_ms: int) -> L2Result:
        call.status = "failed"
        call.error_code = code
        call.error_message = self._redact(message)[:600]
        call.latency_ms = latency_ms
        return L2Result(None, call)

    def _cleanup(self, uploaded: list[Any]) -> None:
        deleter = getattr(self.backend, "delete_file", None)
        if deleter is None:
            return
        for file in uploaded:
            deleter(file)


def _parse(text: str) -> tuple[GeminiObservation | None, str]:
    try:
        payload = extract_json(text)
    except JsonExtractionError as exc:
        return None, f"extraction: {exc}"
    try:
        return GeminiObservation.parse(payload), ""
    except SchemaError as exc:
        return None, f"schema[{exc.code}] {exc}"


def build_gemini_l2(api_key: str, model: str, base_url: str, timeout_sec: float,
                    inline_limit_bytes: int, redact: Any = None) -> L2Service:
    client = GeminiClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_sec=timeout_sec,
        inline_limit_bytes=inline_limit_bytes,
    )
    return L2Service(client, provider="gemini", redact=redact)


def build_local_vllm_l2(api_key: str, model: str, base_url: str, timeout_sec: float,
                        redact: Any = None, enable_thinking: bool = False) -> L2Service:
    from ..local_vllm import LocalVllmClient

    client = LocalVllmClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_sec=timeout_sec,
        enable_thinking=enable_thinking,
    )
    return L2Service(client, provider="local_vllm", redact=redact)
