"""OpenAI-compatible HTTP schemas (vendor-neutral).

The fields here are a strict subset of the OpenAI Chat Completions
schema — the same payload shape that llama.cpp, vLLM, Ollama, MiniMax
and most cloud providers accept. We deliberately do not import the
``openai`` SDK so that domain code stays vendor-neutral.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


Role = Literal["system", "user", "assistant", "tool"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Role
    content: str | list[dict[str, Any]]  # text or list of multimodal parts


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stream: bool = False
    response_format: dict[str, Any] | None = None


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int
    message: ChatMessage
    finish_reason: str | None = None


class ChatUsage(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: ChatUsage | None = None


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    object: str = "model"
    owned_by: str = "unknown"
    created: int | None = None
    capabilities: list[str] = Field(default_factory=list)


class AudioTranscriptionRequest(BaseModel):
    """POST /v1/audio/transcriptions multipart body."""

    model_config = ConfigDict(extra="allow")

    model: str
    language: str | None = None
    prompt: str | None = None
    response_format: Literal["json", "text", "srt", "verbose_json"] = "json"
    temperature: float | None = None


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    language: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None


class SpeechResult(BaseModel):
    """Result of /v1/audio/speech. Bytes-only; the model returns audio."""

    model_config = ConfigDict(extra="allow")

    audio_bytes: bytes
    content_type: str = "audio/mpeg"
