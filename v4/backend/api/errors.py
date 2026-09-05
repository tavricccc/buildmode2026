"""API error envelope + handlers (v4 05 §"錯誤格式")."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..adapters.openai_client import OpenAIClientError
from ..services.settings_service import SettingsError


logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    correlation_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def _envelope(code: str, message: str, retryable: bool, correlation_id: str | None = None) -> dict[str, Any]:
    return ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            correlation_id=correlation_id,
        )
    ).model_dump()


def _status_for_code(code: str) -> int:
    return {
        "CONFIGURATION_REQUIRED": 412,
        "ENDPOINT_AUTH_FAILED": 401,
        "MODEL_CAPABILITY_MISMATCH": 422,
        "MODEL_SCHEMA_INVALID": 422,
        "RATE_LIMITED": 429,
        "LOCAL_RUNTIME_FAILED": 502,
        "CONFIG_VERSION_CONFLICT": 409,
        "RESTART_REQUIRED": 409,
    }.get(code, 500)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(OpenAIClientError)
    async def _openai(_: Request, exc: OpenAIClientError):
        return JSONResponse(
            status_code=_status_for_code(exc.code) or 502,
            content=_envelope(exc.code, exc.message, exc.code in {"RATE_LIMITED", "TIMEOUT"}),
        )

    @app.exception_handler(SettingsError)
    async def _settings(_: Request, exc: SettingsError):
        return JSONResponse(
            status_code=_status_for_code(exc.code),
            content=_envelope(exc.code, exc.message, False),
        )

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        code = {
            400: "BAD_REQUEST",
            401: "ENDPOINT_AUTH_FAILED",
            403: "ENDPOINT_AUTH_FAILED",
            404: "NOT_FOUND",
            409: "CONFIG_VERSION_CONFLICT",
            422: "MODEL_SCHEMA_INVALID",
        }.get(exc.status_code, "INTERNAL")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, str(exc.detail), False),
        )
