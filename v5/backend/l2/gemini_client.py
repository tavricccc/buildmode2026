"""Google Gemini native REST client (v5 01 §L2, v5 README).

v5 explicitly stops pretending Gemini is OpenAI-compatible. It is called
in its own shape:

    POST {base}/models/{model}:generateContent?key=...

Media takes one of two paths, chosen by size and nothing else:

* ``<= inline_limit`` — a ``inline_data`` part carrying base64 bytes.
* larger — the resumable Files API, then poll until the file reports
  ``ACTIVE``, then reference it as ``file_data.file_uri``. Sending a
  ``PROCESSING`` file straight to generateContent fails, so the poll is
  not optional.

Standard library only (``urllib``), for the reason given in
``domain/schema.py``: a reviewer must be able to run this on a fresh
clone.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from ..providers import ProviderError

USER_AGENT = "care-agent-v5/1.0 (+https://github.com/futuremode/care-agent)"


class GeminiError(ProviderError):
    """A Gemini call failed."""


@dataclass
class GeminiResponse:
    text: str
    latency_ms: int
    model: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    candidate_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """A MAX_TOKENS finish silently yields unparseable JSON otherwise."""
        return self.finish_reason == "MAX_TOKENS"


@dataclass
class UploadedFile:
    name: str
    uri: str
    mime_type: str
    state: str


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_sec: float = 45.0,
        inline_limit_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        if not api_key:
            raise GeminiError("no_api_key", "GEMINI_API_KEY is not configured")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.inline_limit_bytes = inline_limit_bytes

    # -- transport -------------------------------------------------------

    def _request(
        self,
        url: str,
        *,
        method: str = "POST",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("User-Agent", USER_AGENT)
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_sec) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            raise GeminiError(
                _http_code(exc.code), _extract_error(payload), status=exc.code
            ) from exc
        except urllib.error.URLError as exc:
            raise GeminiError("network_error", str(exc.reason)) from exc
        except TimeoutError as exc:
            raise GeminiError("timeout", f"no response within {timeout or self.timeout_sec}s") from exc

    def _json_post(self, url: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        _, _, raw = self._request(
            url,
            body=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        return json.loads(raw.decode("utf-8"))

    # -- Files API -------------------------------------------------------

    def upload_file(self, path: str | Path, mime_type: str, display_name: str = "clip") -> UploadedFile:
        """Resumable upload for media above the inline limit (v5 01)."""
        data = Path(path).read_bytes()
        upload_base = self.base_url.replace("/v1beta", "/upload/v1beta")

        status, headers, _ = self._request(
            f"{upload_base}/files?key={self.api_key}",
            body=json.dumps({"file": {"display_name": display_name}}).encode("utf-8"),
            headers={
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                "X-Goog-Upload-Header-Content-Type": mime_type,
                "Content-Type": "application/json",
            },
        )
        upload_url = headers.get("X-Goog-Upload-URL") or headers.get("x-goog-upload-url")
        if not upload_url:
            raise GeminiError("upload_start_failed", f"no upload URL in response (HTTP {status})")

        _, _, raw = self._request(
            upload_url,
            body=data,
            headers={
                "Content-Length": str(len(data)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            timeout=max(self.timeout_sec, 120.0),
        )
        info = json.loads(raw.decode("utf-8")).get("file", {})
        return UploadedFile(
            name=info.get("name", ""),
            uri=info.get("uri", ""),
            mime_type=info.get("mimeType", mime_type),
            state=info.get("state", "PROCESSING"),
        )

    def wait_active(self, file: UploadedFile, poll_sec: float = 1.0, max_wait_sec: float = 60.0) -> UploadedFile:
        """Poll until ``ACTIVE``. A ``PROCESSING`` file cannot be referenced."""
        deadline = time.monotonic() + max_wait_sec
        current = file
        while current.state == "PROCESSING":
            if time.monotonic() > deadline:
                raise GeminiError("file_not_active", f"{current.name} still PROCESSING after {max_wait_sec}s")
            time.sleep(poll_sec)
            _, _, raw = self._request(
                f"{self.base_url}/{current.name}?key={self.api_key}", method="GET"
            )
            info = json.loads(raw.decode("utf-8"))
            current = UploadedFile(
                name=info.get("name", current.name),
                uri=info.get("uri", current.uri),
                mime_type=info.get("mimeType", current.mime_type),
                state=info.get("state", "PROCESSING"),
            )
        if current.state != "ACTIVE":
            raise GeminiError("file_failed", f"{current.name} is {current.state}")
        return current

    def delete_file(self, file: UploadedFile) -> None:
        """Best-effort cleanup; a leaked upload expires on its own in 48h."""
        try:
            self._request(f"{self.base_url}/{file.name}?key={self.api_key}", method="DELETE")
        except GeminiError:
            pass

    # -- parts -----------------------------------------------------------

    def media_part(self, path: str | Path, mime_type: str, cleanup: list[UploadedFile] | None = None) -> dict[str, Any]:
        """Build the right part for this file's size (v5 01 §L2)."""
        path = Path(path)
        size = path.stat().st_size
        if size <= self.inline_limit_bytes:
            return {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            }
        uploaded = self.wait_active(self.upload_file(path, mime_type, display_name=path.name))
        if cleanup is not None:
            cleanup.append(uploaded)
        return {"file_data": {"mime_type": uploaded.mime_type, "file_uri": uploaded.uri}}

    @staticmethod
    def text_part(text: str) -> dict[str, Any]:
        return {"text": text}

    # -- generation ------------------------------------------------------

    def generate(
        self,
        parts: list[dict[str, Any]],
        *,
        system_instruction: str | None = None,
        json_output: bool = True,
        temperature: float = 0.0,
        max_output_tokens: int = 1024,
        model: str | None = None,
    ) -> GeminiResponse:
        model_id = model or self.model
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "candidateCount": 1,
            },
        }
        if json_output:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        started = time.perf_counter()
        data = self._json_post(
            f"{self.base_url}/models/{model_id}:generateContent?key={self.api_key}", payload
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise GeminiError("blocked", f"prompt blocked: {blocked}")

        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError("empty_response", "no candidates returned")

        candidate = candidates[0]
        segments = [
            part["text"]
            for part in (candidate.get("content", {}).get("parts") or [])
            if isinstance(part.get("text"), str)
        ]
        usage = data.get("usageMetadata") or {}
        return GeminiResponse(
            text="".join(segments),
            latency_ms=latency_ms,
            model=model_id,
            finish_reason=candidate.get("finishReason"),
            prompt_tokens=usage.get("promptTokenCount"),
            candidate_tokens=usage.get("candidatesTokenCount"),
            total_tokens=usage.get("totalTokenCount"),
            raw=data,
        )

    def list_models(self) -> list[str]:
        """Auth + model-availability probe (v5 04 §Capability probes)."""
        _, _, raw = self._request(f"{self.base_url}/models?key={self.api_key}", method="GET")
        data = json.loads(raw.decode("utf-8"))
        return [m.get("name", "").removeprefix("models/") for m in data.get("models", [])]


def _http_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthenticated",
        403: "permission_denied",
        404: "model_not_found",
        413: "payload_too_large",
        429: "rate_limited",
        500: "provider_error",
        503: "provider_unavailable",
    }.get(status, f"http_{status}")


def _extract_error(payload: bytes) -> str:
    try:
        body = json.loads(payload.decode("utf-8"))
        return str(body.get("error", {}).get("message", body))[:400]
    except Exception:  # noqa: BLE001
        return payload.decode("utf-8", "replace")[:400]
