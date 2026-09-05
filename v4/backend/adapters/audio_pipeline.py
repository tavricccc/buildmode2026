"""Audio pipeline stub (v4 09 §4).

The production pipeline uses a real mic + Silero VAD + Whisper. In
this round we expose a protocol that the test suite can satisfy; the
real implementation lands in a later commit.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .source_protocol import AudioPacket


@runtime_checkable
class VadProtocol(Protocol):
    async def is_speech(self, pcm: AudioPacket) -> bool: ...


class AudioPipeline:
    def __init__(self, vad: VadProtocol | None = None) -> None:
        self._vad = vad

    async def is_speech(self, pcm: AudioPacket) -> bool:
        if self._vad is None:
            return False
        return await self._vad.is_speech(pcm)
