"""MiniMax M3 client over an OpenAI-compatible endpoint (docs/01_PIPELINE.md §L3).

Unlike L2 this provider *is* OpenAI-shaped, so we talk to it that way —
the point of dropping v4's universal-runtime abstraction was never to
forbid the OpenAI shape, it was to stop forcing it on providers that do
not speak it.

Three things here are not defaults and are deliberate:

``WIRE_FORMAT``
    A clip reaches the model as a sampled sequence of ``image_url`` data
    URIs, not as a ``video_url``. Providers advertise ``video_url``, but
    what actually arrives at the model is provider-dependent and can be a
    heavily decimated sample — silently. Sending frames means the count
    the model receives is the count we chose. ``video_url`` remains
    selectable so a probe can re-measure a given deployment.

``User-Agent``
    An explicit UA is set. Gateways in front of OpenAI-compatible
    deployments reject urllib's default UA with a 403 that is
    indistinguishable from an auth failure, which is an expensive hour to
    lose.

``context_length_exceeded_behavior``
    Sent as ``error``. The alternative is silent truncation, and a
    truncated escalation is worse than a failed one: it looks like a
    considered answer about evidence the model never saw.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from ..providers import ProviderError

USER_AGENT = "care-agent/1.0 (+https://github.com/futuremode/care-agent)"

WIRE_FORMAT_FRAMES = "frames"
WIRE_FORMAT_VIDEO_URL = "video_url"


class MiniMaxError(ProviderError):
    """A MiniMax call failed."""


@dataclass
class MiniMaxResponse:
    text: str
    latency_ms: int
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


class MiniMaxClient:
    def __init__(
        self,
        api_key: str,
        model: str = "MiniMaxAI/MiniMax-M3",
        base_url: str = "https://api.gmi-serving.com/v1",
        timeout_sec: float = 90.0,
        wire_format: str = WIRE_FORMAT_FRAMES,
        max_frames: int = 10,
    ) -> None:
        if not api_key:
            raise MiniMaxError("no_api_key", "MINIMAX_API_KEY is not configured")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.wire_format = wire_format
        self.max_frames = max_frames

    # -- transport -------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_sec) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MiniMaxError(_http_code(exc.code), _extract_error(exc.read()), status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise MiniMaxError("network_error", str(exc.reason)) from exc
        except TimeoutError as exc:
            raise MiniMaxError("timeout", f"no response within {timeout or self.timeout_sec}s") from exc

    # -- content parts ---------------------------------------------------

    def video_parts(self, frames: list[bytes], clip_url: str | None = None) -> list[dict[str, Any]]:
        """Encode the clip's visual evidence for the chat payload."""
        if self.wire_format == WIRE_FORMAT_VIDEO_URL:
            if not clip_url:
                raise MiniMaxError("no_clip_url", "video_url wire format needs a reachable clip URL")
            return [{"type": "video_url", "video_url": {"url": clip_url}}]

        sampled = _thin(frames, self.max_frames)
        return [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(f).decode("ascii")},
            }
            for f in sampled
        ]

    @staticmethod
    def text_part(text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    # -- generation ------------------------------------------------------

    def analyse(
        self,
        parts: list[dict[str, Any]],
        *,
        system_instruction: str | None = None,
        json_output: bool = True,
        temperature: float = 0.0,
        max_tokens: int = 900,
        model: str | None = None,
    ) -> MiniMaxResponse:
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": parts})

        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Fail loudly rather than silently dropping evidence.
            "context_length_exceeded_behavior": "error",
        }
        if json_output:
            # json_object, not json_schema: strict schema support is not
            # guaranteed here, so validation stays on our side of the wire.
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        data = self._post("/chat/completions", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        choices = data.get("choices") or []
        if not choices:
            raise MiniMaxError("empty_response", "no choices returned")
        choice = choices[0]
        content = (choice.get("message") or {}).get("content")
        if isinstance(content, list):  # some deployments return parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        usage = data.get("usage") or {}
        return MiniMaxResponse(
            text=content or "",
            latency_ms=latency_ms,
            model=data.get("model", model or self.model),
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw=data,
        )

    def list_models(self) -> list[str]:
        """Auth + model-availability probe (docs/04_SETUP_DEPLOY_VERIFY.md §Capability probes)."""
        req = urllib.request.Request(f"{self.base_url}/models", method="GET")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise MiniMaxError(_http_code(exc.code), _extract_error(exc.read()), status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise MiniMaxError("network_error", str(exc.reason)) from exc
        return [m.get("id", "") for m in data.get("data", [])]


def _thin(frames: list[bytes], limit: int) -> list[bytes]:
    """Even coverage of the clip, keeping the last frame.

    Same reasoning as ``FrameWindow.window``: the tail of a clip is not a
    substitute for the clip. If a fall happened in the first second, a
    tail sample shows only the aftermath.
    """
    if len(frames) <= limit:
        return list(frames)
    stride = len(frames) / float(limit)
    picked = [frames[min(int(i * stride), len(frames) - 1)] for i in range(limit)]
    picked[-1] = frames[-1]
    return picked


def _http_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthenticated",
        402: "payment_required",
        403: "forbidden",
        404: "model_not_found",
        413: "payload_too_large",
        429: "rate_limited",
        500: "provider_error",
        503: "provider_unavailable",
    }.get(status, f"http_{status}")


def _extract_error(payload: bytes) -> str:
    try:
        body = json.loads(payload.decode("utf-8"))
        error = body.get("error", body)
        if isinstance(error, dict):
            return str(error.get("message", error))[:400]
        return str(error)[:400]
    except Exception:  # noqa: BLE001
        return payload.decode("utf-8", "replace")[:400]
