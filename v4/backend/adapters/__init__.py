"""Adapter layer.

Vendor SDKs and platform-specific code live here. Domain code in
``backend/domain/`` and ``backend/repos/`` never imports from this package.
"""

from .openai_schemas import (
    ChatRequest,
    ChatResponse,
    ChatMessage,
    ModelInfo,
    TranscriptionResult,
    SpeechResult,
    AudioTranscriptionRequest,
)
from .openai_client import OpenAICompatibleClient, OpenAIClientError
from .capability_probe import ProbeSpec, run_probe, ProbeResult
from .model_gateway import (
    ModelGateway,
    ModelRequest,
    ModelResponse,
    ModelEndpointRegistry,
    ModelEndpoint,
)
from .source_protocol import (
    SourceProtocol,
    SourceStatus,
    FramePacket,
    AudioPacket,
)
from .replay_source import ReplaySource
from .frame_buffer import BoundedRingBuffer
from .vision_loop import ContinuousVisionLoop
from .audio_pipeline import AudioPipeline, VadProtocol
from .telegram_bot import TelegramBot, TelegramUpdate

__all__ = [
    "ChatRequest", "ChatResponse", "ChatMessage", "ModelInfo",
    "TranscriptionResult", "SpeechResult", "AudioTranscriptionRequest",
    "OpenAICompatibleClient", "OpenAIClientError",
    "ProbeSpec", "run_probe", "ProbeResult",
    "ModelGateway", "ModelRequest", "ModelResponse",
    "ModelEndpointRegistry", "ModelEndpoint",
    "SourceProtocol", "SourceStatus", "FramePacket", "AudioPacket",
    "ReplaySource", "BoundedRingBuffer", "ContinuousVisionLoop",
    "AudioPipeline", "VadProtocol",
    "TelegramBot", "TelegramUpdate",
]
