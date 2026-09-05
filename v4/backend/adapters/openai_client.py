"""OpenAI-compatible HTTP client.

Wraps ``httpx.AsyncClient`` so the rest of the backend never imports a
vendor SDK. Errors are normalised to ``OpenAIClientError`` with a stable
``code`` that the API layer maps onto the v4 error envelope.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .openai_schemas import (
    ChatRequest,
    ChatResponse,
    ModelInfo,
    TranscriptionResult,
)


logger = logging.getLogger(__name__)


class OpenAIClientError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s,
            headers=self._headers(),
        )

    @property
    def headers(self) -> dict[str, str]:
        return self._client.headers if not self._owns_client else self._headers()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "User-Agent": "care-agent-v4/0.1"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "OpenAICompatibleClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    async def list_models(self) -> list[ModelInfo]:
        url = f"{self.base_url}/v1/models"
        try:
            resp = await self._client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise OpenAIClientError("TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OpenAIClientError("RUNTIME_FAILED", str(exc)) from exc
        self._raise_for_status(resp)
        data = resp.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        return [ModelInfo(**item) for item in items]

    async def chat_completions(self, req: ChatRequest) -> ChatResponse:
        url = f"{self.base_url}/v1/chat/completions"
        payload = req.model_dump(exclude_none=True)
        return await self._post_json(url, payload, ChatResponse)

    async def audio_transcriptions(
        self,
        audio: bytes,
        filename: str,
        req: "AudioTranscriptionRequest",  # type: ignore[name-defined]
    ) -> TranscriptionResult:
        url = f"{self.base_url}/v1/audio/transcriptions"
        files = {"file": (filename, audio, "application/octet-stream")}
        data = req.model_dump(exclude_none=True)
        headers = {k: v for k, v in self._headers().items() if k.lower() != "content-type"}
        try:
            resp = await self._client.post(url, files=files, data=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise OpenAIClientError("TIMEOUT", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OpenAIClientError("RUNTIME_FAILED", str(exc)) from exc
        self._raise_for_status(resp)
        body = resp.json()
        return TranscriptionResult(**body)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _post_json(self, url: str, payload: dict[str, Any], model_cls: type[ChatResponse]) -> ChatResponse:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                t0 = time.monotonic()
                resp = await self._client.post(url, json=payload, headers=self._headers())
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._raise_for_status(resp)
                return model_cls(**resp.json())
            except OpenAIClientError as exc:
                last_exc = exc
                if exc.code in {"RATE_LIMITED", "TIMEOUT"} and attempt < self.max_retries:
                    await asyncio.sleep(0.25 * (2 ** attempt))
                    continue
                raise
        raise OpenAIClientError("RUNTIME_FAILED", str(last_exc))

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code == 200:
            return
        if resp.status_code == 401 or resp.status_code == 403:
            raise OpenAIClientError("ENDPOINT_AUTH_FAILED", resp.text, resp.status_code)
        if resp.status_code == 429:
            raise OpenAIClientError("RATE_LIMITED", resp.text, resp.status_code)
        if resp.status_code == 408 or resp.status_code == 504:
            raise OpenAIClientError("TIMEOUT", resp.text, resp.status_code)
        if 400 <= resp.status_code < 500:
            raise OpenAIClientError("MODEL_SCHEMA_INVALID", resp.text, resp.status_code)
        raise OpenAIClientError("RUNTIME_FAILED", resp.text, resp.status_code)
