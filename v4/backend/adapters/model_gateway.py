"""Model Gateway.

The Gateway is the single point through which domain code calls any
model — local or cloud, vision or analysis. It binds each call to a
config version (DoD #9: every event is traceable back to the config
that produced it) and persists a ``model_calls`` row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from ..domain.enums import (
    Capability,
    DeploymentType,
    ModelCallStatus,
)
from ..domain.ids import new_id
from ..domain.time import isoformat, utc_now
from .openai_client import OpenAICompatibleClient, OpenAIClientError
from .openai_schemas import ChatRequest, ChatResponse


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelEndpoint:
    id: str
    display_name: str
    deployment_type: DeploymentType
    base_url: str
    adapter_mode: str = "openai_chat"
    api_key: str | None = None
    enabled: bool = True

    def client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(base_url=self.base_url, api_key=self.api_key)


class ModelEndpointRegistry:
    """In-memory endpoint registry.

    Backed by the ``model_endpoints`` table in production. The
    `repos/model_endpoint_repo.py` populates this on startup.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, ModelEndpoint] = {}

    def upsert(self, endpoint: ModelEndpoint) -> None:
        self._by_id[endpoint.id] = endpoint

    def remove(self, endpoint_id: str) -> None:
        self._by_id.pop(endpoint_id, None)

    def get(self, endpoint_id: str) -> ModelEndpoint | None:
        return self._by_id.get(endpoint_id)

    def all(self) -> list[ModelEndpoint]:
        return list(self._by_id.values())


@dataclass(frozen=True)
class ModelRequest:
    capability: Capability
    inputs: dict[str, Any]
    prompt_version: str
    schema_version: str
    timeout_s: float | None = None
    config_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    raw: dict[str, Any]
    parsed: BaseModel | None
    latency_ms: int
    usage: dict[str, int] | None
    call_id: str
    endpoint_id: str
    deployment_type: DeploymentType
    model_id: str
    config_version: str | None
    status: ModelCallStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "endpoint_id": self.endpoint_id,
            "deployment_type": self.deployment_type.value,
            "model_id": self.model_id,
            "config_version": self.config_version,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "status": self.status.value,
            "parsed": self.parsed.model_dump() if self.parsed else None,
        }


# Type alias for a ModelCalls repository — defined forward to avoid
# importing repos here (which would create a cycle).
ModelCallSink = Callable[[ModelResponse, ModelRequest, str], None]


def _input_hash(request: ModelRequest) -> str:
    blob = json.dumps(
        {
            "capability": request.capability.value,
            "inputs": request.inputs,
            "prompt_version": request.prompt_version,
            "schema_version": request.schema_version,
        },
        sort_keys=True,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


class ModelGateway:
    """Single entry point for every model call in the backend."""

    def __init__(
        self,
        registry: ModelEndpointRegistry,
        sink: ModelCallSink | None = None,
    ) -> None:
        self._registry = registry
        self._sink = sink

    def registry(self) -> ModelEndpointRegistry:
        return self._registry

    async def call(
        self,
        endpoint_id: str,
        model_id: str,
        request: ModelRequest,
    ) -> ModelResponse:
        endpoint = self._registry.get(endpoint_id)
        if endpoint is None:
            raise OpenAIClientError("ENDPOINT_AUTH_FAILED", f"unknown endpoint {endpoint_id}")
        if not endpoint.enabled:
            raise OpenAIClientError("RUNTIME_FAILED", f"endpoint {endpoint_id} disabled")

        call_id = new_id("mcall")
        chat_req = self._to_chat_request(model_id, request)
        t0 = time.monotonic()
        status = ModelCallStatus.success
        parsed: BaseModel | None = None
        raw: dict[str, Any] = {}
        usage: dict[str, int] | None = None
        try:
            async with endpoint.client() as client:
                resp: ChatResponse = await client.chat_completions(chat_req)
                raw = resp.model_dump()
                usage = resp.usage.model_dump() if resp.usage else None
                parsed = self._parse_output(request, resp)
        except OpenAIClientError as exc:
            status = ModelCallStatus.invalid_schema
            if exc.code in {"RATE_LIMITED", "TIMEOUT", "RUNTIME_FAILED", "ENDPOINT_AUTH_FAILED"}:
                status = ModelCallStatus[exc.code.lower()] if exc.code in ModelCallStatus.__members__ else ModelCallStatus.runtime_failed
            raw = {"error": exc.code, "message": exc.message}
            logger.warning("model call failed", extra={"code": exc.code, "endpoint": endpoint_id, "model": model_id})
        latency_ms = int((time.monotonic() - t0) * 1000)

        response = ModelResponse(
            raw=raw,
            parsed=parsed,
            latency_ms=latency_ms,
            usage=usage,
            call_id=call_id,
            endpoint_id=endpoint_id,
            deployment_type=endpoint.deployment_type,
            model_id=model_id,
            config_version=request.config_version,
            status=status,
        )
        if self._sink is not None:
            try:
                self._sink(response, request, _input_hash(request))
            except Exception:  # noqa: BLE001 - audit must not break the call
                logger.exception("model call sink failed")
        return response

    # ------------------------------------------------------------------
    # Request / output shaping
    # ------------------------------------------------------------------

    def _to_chat_request(self, model_id: str, request: ModelRequest) -> ChatRequest:
        messages = request.inputs.get("messages")
        if not messages:
            system = request.inputs.get("system", "You are a structured-output assistant. Reply with JSON only.")
            user = request.inputs.get("user", "")
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        return ChatRequest(
            model=model_id,
            messages=messages,
            temperature=request.inputs.get("temperature", 0.0),
            response_format={"type": "json_object"},
        )

    def _parse_output(self, request: ModelRequest, resp: ChatResponse) -> BaseModel | None:
        if not resp.choices:
            return None
        content = resp.choices[0].message.content
        if isinstance(content, list):
            text = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        else:
            text = content or ""
        try:
            data = json.loads(text) if isinstance(text, str) and text.strip().startswith("{") else {}
        except json.JSONDecodeError:
            return None
        schema = request.inputs.get("output_schema")
        if schema is None:
            return None
        try:
            return schema.model_validate(data)
        except Exception:  # noqa: BLE001 - invalid schema is a valid result
            return None


def make_sink(repo: Any) -> ModelCallSink:
    """Build a sink that writes ``model_calls`` rows.

    ``repo`` is duck-typed to avoid an import cycle: it must implement
    ``record(call_id, endpoint_id, deployment_type, model_id, capability,
    input_hash, prompt_version, schema_version, status, latency_ms,
    tokens_in, tokens_out, error_code, response_json, created_at,
    config_version)``.
    """

    def sink(response: ModelResponse, request: ModelRequest, input_hash: str) -> None:
        repo.record(
            call_id=response.call_id,
            endpoint_id=response.endpoint_id,
            deployment_type=response.deployment_type.value,
            model_id=response.model_id,
            capability=request.capability.value,
            input_hash=input_hash,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            status=response.status.value,
            latency_ms=response.latency_ms,
            tokens_in=(response.usage or {}).get("prompt_tokens"),
            tokens_out=(response.usage or {}).get("completion_tokens"),
            error_code=response.raw.get("error") if "error" in response.raw else None,
            response_json=json.dumps(response.raw, default=str)[:8192],
            created_at=isoformat(utc_now()),
            config_version=response.config_version,
        )

    return sink
