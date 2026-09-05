"""Local OpenAI-compatible stub server.

Exposes ``/v1/models``, ``/v1/chat/completions``,
``/v1/audio/transcriptions`` and ``/v1/audio/speech`` so the rest of
the backend can exercise the full Model Gateway contract without a
real model. The server is a separate FastAPI app that runs in a
background task on the same process.
"""

from .server import build_stub_app, start_stub_server, stop_stub_server
from .fixtures import vision_fixture, analysis_fixture, transcription_fixture

__all__ = [
    "build_stub_app",
    "start_stub_server",
    "stop_stub_server",
    "vision_fixture",
    "analysis_fixture",
    "transcription_fixture",
]
