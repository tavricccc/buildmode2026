"""OpenAI-compatible local vLLM transport shared by every agent.

The original Longcare runtime uses one local multimodal model for observation
and the Main Agent.  The design keeps its provider boundary, but this transport lets
L2, L3 and the legacy-flow agents use that same model without requiring a
cloud key or pretending the provider is Gemini.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
import wave
from io import BytesIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .providers import ProviderError


USER_AGENT = "care-agent/local-vllm"


class LocalVllmError(ProviderError):
    """A local vLLM call failed."""


@dataclass
class LocalVllmResponse:
    text: str
    latency_ms: int
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def candidate_tokens(self) -> int | None:
        """Gemini-compatible alias used by the shared L2 service."""
        return self.output_tokens

    @property
    def truncated(self) -> bool:
        return self.finish_reason in {"length", "MAX_TOKENS"}


class LocalVllmClient:
    """Small stdlib client for vLLM's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        model: str = "nemotron_omni",
        base_url: str = "http://127.0.0.1:8100/v1",
        api_key: str = "",
        timeout_sec: float = 90.0,
        enable_thinking: bool = False,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.enable_thinking = enable_thinking

    @staticmethod
    def text_part(text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    @staticmethod
    def _image_part(image: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
        encoded = base64.b64encode(image).decode("ascii")
        return {"type": "image_url", "image_url": {
            "url": f"data:{mime_type};base64,{encoded}"
        }}

    def frame_parts(self, frames: list[bytes] | tuple[bytes, ...], mime_type: str = "image/jpeg",
                    audio_pcm: bytes | None = None) -> list[dict[str, Any]]:
        parts = [self._image_part(frame, mime_type) for frame in frames]
        if audio_pcm:
            parts.append(self.audio_part(audio_pcm))
        return parts

    @staticmethod
    def audio_part(pcm: bytes, sample_rate: int = 16000) -> dict[str, Any]:
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        encoded = base64.b64encode(output.getvalue()).decode("ascii")
        return {"type": "audio_url", "audio_url": {
            "url": f"data:audio/wav;base64,{encoded}"
        }}

    def video_parts(self, frames: list[bytes], clip_url: str | None = None) -> list[dict[str, Any]]:
        # The verified MiniMax path deliberately sends sampled image
        # frames.  This is also the reliable local-Nemotron wire format.
        if frames:
            return self.frame_parts(frames)
        if clip_url:
            return [{"type": "video_url", "video_url": {"url": clip_url}}]
        return []

    def media_part(self, path: str | Path, mime_type: str,
                   cleanup: list[Any] | None = None) -> dict[str, Any]:
        data = Path(path).read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        if mime_type.startswith("video/"):
            return {"type": "video_url", "video_url": {
                "url": f"data:{mime_type};base64,{encoded}"
            }}
        return {"type": "image_url", "image_url": {
            "url": f"data:{mime_type};base64,{encoded}"
        }}

    def _request(self, payload: dict[str, Any], timeout: float | None = None) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_sec) as response:
                raw = response.read()
                return response.status, json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            raise LocalVllmError(_http_code(exc.code), _error_text(raw), exc.code) from exc
        except urllib.error.URLError as exc:
            raise LocalVllmError("network_error", str(exc.reason)) from exc
        except TimeoutError as exc:
            raise LocalVllmError("timeout", f"no response within {timeout or self.timeout_sec}s") from exc
        except json.JSONDecodeError as exc:
            raise LocalVllmError("invalid_response", str(exc)) from exc

    def generate(
        self,
        parts: list[dict[str, Any]],
        *,
        system_instruction: str | None = None,
        json_output: bool = True,
        temperature: float = 0.0,
        max_output_tokens: int = 1024,
        model: str | None = None,
    ) -> LocalVllmResponse:
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": parts})
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        status, data = self._request(payload)
        elapsed = int((time.perf_counter() - started) * 1000)
        choices = data.get("choices") or []
        if not choices:
            raise LocalVllmError("empty_response", "no choices returned", status)
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        usage = data.get("usage") or {}
        return LocalVllmResponse(
            text=str(content),
            latency_ms=elapsed,
            model=model or self.model,
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            raw=data,
        )

    def analyse(self, parts: list[dict[str, Any]], *, system_instruction: str | None = None,
                **kwargs: Any) -> LocalVllmResponse:
        return self.generate(parts, system_instruction=system_instruction,
                             max_output_tokens=kwargs.pop("max_output_tokens", 1200), **kwargs)


def _http_code(status: int) -> str:
    return {
        400: "bad_request", 401: "unauthenticated", 403: "permission_denied",
        404: "model_not_found", 408: "timeout", 413: "payload_too_large",
        429: "rate_limited", 500: "provider_error", 502: "provider_error",
        503: "provider_unavailable",
    }.get(status, f"http_{status}")


def _error_text(raw: bytes) -> str:
    try:
        body = json.loads(raw.decode("utf-8"))
        return str(body.get("error", {}).get("message", body))[:400]
    except Exception:  # noqa: BLE001
        return raw.decode("utf-8", "replace")[:400]
