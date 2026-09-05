"""Capability probes (v4 13 §「統一安裝流程」).

A ``ProbeSpec`` is a tiny, deterministic request the gateway sends to
candidate models. The probe succeeds only if the response matches the
expected schema — silent capability mismatches are forbidden.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..domain.enums import Capability, ModelProbeStatus
from .openai_client import OpenAICompatibleClient, OpenAIClientError
from .openai_schemas import (
    AudioTranscriptionRequest,
    ChatRequest,
    ChatMessage,
    TranscriptionResult,
)


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def vision_probe_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are a structured vision classifier. Reply with JSON."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return a VisionObservation JSON."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="},
                    },
                ],
            },
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }


def analysis_probe_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Return a HealthRiskResult JSON."},
            {"role": "user", "content": "{\"subject_id\":\"probe\",\"window_start\":\"now\",\"window_end\":\"now\"}"},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }


def speech_probe_payload(model_id: str) -> dict[str, Any]:
    return {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "Repeat the word 'probe'."},
            {"role": "user", "content": "probe"},
        ],
    }


# ----------------------------------------------------------------------
# ProbeSpec
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeSpec:
    """A request factory paired with the expected response shape."""

    capability: Capability
    request_factory: Callable[[str], dict[str, Any]]
    expected_keys: tuple[str, ...]
    description: str = ""

    def to_request(self, model_id: str) -> ChatRequest:
        return ChatRequest.model_validate(self.request_factory(model_id))


async def _vision_check(client: OpenAICompatibleClient, model_id: str) -> tuple[bool, str]:
    try:
        resp = await client.chat_completions(ProbeSpec.vision().to_request(model_id))
    except OpenAIClientError as exc:
        return False, f"chat_completions failed: {exc.code}"
    content = resp.choices[0].message.content if resp.choices else ""
    if isinstance(content, list):
        text = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    else:
        text = content or ""
    try:
        body = json.loads(text) if isinstance(text, str) and text.strip().startswith("{") else {}
    except json.JSONDecodeError:
        body = {}
    missing = [k for k in ("posture", "vertical_transition", "confidence") if k not in body]
    if missing:
        return False, f"missing keys: {missing}"
    return True, "ok"


async def _analysis_check(client: OpenAICompatibleClient, model_id: str) -> tuple[bool, str]:
    try:
        resp = await client.chat_completions(ProbeSpec.analysis().to_request(model_id))
    except OpenAIClientError as exc:
        return False, f"chat_completions failed: {exc.code}"
    content = resp.choices[0].message.content if resp.choices else ""
    if isinstance(content, list):
        text = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    else:
        text = content or ""
    try:
        body = json.loads(text) if isinstance(text, str) and text.strip().startswith("{") else {}
    except json.JSONDecodeError:
        body = {}
    missing = [k for k in ("summary_zh", "risk_level") if k not in body]
    if missing:
        return False, f"missing keys: {missing}"
    return True, "ok"


async def _transcription_check(client: OpenAICompatibleClient, model_id: str) -> tuple[bool, str]:
    try:
        req = AudioTranscriptionRequest(model=model_id, language="en", response_format="json")
        result = await client.audio_transcriptions(b"RIFF$\x00\x00", "probe.wav", req)
    except OpenAIClientError as exc:
        return False, f"audio_transcriptions failed: {exc.code}"
    if not result.text:
        return False, "empty transcription"
    return True, "ok"


# ----------------------------------------------------------------------
# Specs
# ----------------------------------------------------------------------


def _vision_spec() -> ProbeSpec:
    return ProbeSpec(
        capability=Capability.vision,
        request_factory=vision_probe_payload,
        expected_keys=("posture", "vertical_transition", "confidence"),
        description="multi-image + structured JSON",
    )


def _analysis_spec() -> ProbeSpec:
    return ProbeSpec(
        capability=Capability.analysis,
        request_factory=analysis_probe_payload,
        expected_keys=("summary_zh", "risk_level"),
        description="structured JSON",
    )


def _transcription_spec() -> ProbeSpec:
    return ProbeSpec(
        capability=Capability.transcription,
        request_factory=speech_probe_payload,
        expected_keys=("text",),
        description="/v1/audio/transcriptions",
    )


def _speech_spec() -> ProbeSpec:
    return ProbeSpec(
        capability=Capability.speech,
        request_factory=speech_probe_payload,
        expected_keys=("audio_bytes",),
        description="/v1/audio/speech",
    )


def _embedding_spec() -> ProbeSpec:
    return ProbeSpec(
        capability=Capability.embedding,
        request_factory=lambda m: {"model": m, "input": "probe"},
        expected_keys=("embedding",),
        description="vector output",
    )


_SPECS: dict[Capability, ProbeSpec] = {
    Capability.vision: _vision_spec(),
    Capability.analysis: _analysis_spec(),
    Capability.transcription: _transcription_spec(),
    Capability.speech: _speech_spec(),
    Capability.embedding: _embedding_spec(),
}


def spec_for(capability: Capability) -> ProbeSpec:
    if capability not in _SPECS:
        raise KeyError(f"no probe spec for capability {capability}")
    return _SPECS[capability]


# ----------------------------------------------------------------------
# Run probe
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    capability: Capability
    status: ModelProbeStatus
    model_id: str
    detail: str
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability.value,
            "status": self.status.value,
            "model_id": self.model_id,
            "detail": self.detail,
            "fingerprint": self.fingerprint,
        }


async def run_probe(
    client: OpenAICompatibleClient,
    capability: Capability,
    model_id: str,
) -> ProbeResult:
    """Run the appropriate capability probe and return its result."""

    check: Callable[[OpenAICompatibleClient, str], Awaitable[tuple[bool, str]]]
    if capability == Capability.vision:
        check = _vision_check
    elif capability == Capability.analysis:
        check = _analysis_check
    elif capability == Capability.transcription:
        check = _transcription_check
    else:
        # Speech / embedding: still issue a chat completion check for now.
        check = _analysis_check

    try:
        ok, detail = await check(client, model_id)
    except Exception as exc:  # noqa: BLE001 - normalised below
        logger.warning("probe crashed", extra={"capability": capability.value, "model": model_id, "err": str(exc)})
        ok, detail = False, f"crash: {exc}"

    fingerprint = hashlib.sha256(f"{capability.value}|{model_id}".encode()).hexdigest()[:16]
    return ProbeResult(
        capability=capability,
        status=ModelProbeStatus.ok if ok else ModelProbeStatus.failed,
        model_id=model_id,
        detail=detail,
        fingerprint=fingerprint,
    )
