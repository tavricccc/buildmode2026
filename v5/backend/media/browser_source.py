"""Browser MediaRecorder bridge for the original Longcare input path."""

from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable

from ..domain.timeutil import now_ms
from .frames import FramePacket


class BrowserMediaSession:
    """Decode one continuous WebM upload into JPEG frames and PCM audio."""

    def __init__(self, camera_id: str, media_type: str,
                 sink: Callable[[FramePacket], None], *, fps: float = 2.0,
                 width: int = 1280, audio_seconds: float = 5.0) -> None:
        self.camera_id = camera_id
        self.media_type = media_type
        self.source_id = f"browser-{camera_id}"
        self.sink = sink
        self.fps = fps
        self.width = width
        self.audio_limit = max(16000 * 2, int(16000 * 2 * audio_seconds))
        self.started_at_ms = now_ms()
        self.bytes_received = 0
        self.chunks_received = 0
        self.frames_emitted = 0
        self.audio_bytes = 0
        self.error: str | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self._audio_lock = threading.Lock()
        self._audio = bytearray()
        self._frame_times: deque[int] = deque(maxlen=32)
        self._video = self._spawn_video()
        self._audio_process = self._spawn_audio()
        self._threads = [
            threading.Thread(target=self._read_video, name=f"browser-video-{camera_id}", daemon=True),
            threading.Thread(target=self._read_audio, name=f"browser-audio-{camera_id}", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _spawn_video(self) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
             "-i", "pipe:0", "-vf", f"fps={self.fps:g},scale={self.width}:-2",
             "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "6", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def _spawn_audio(self) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
             "-i", "pipe:0", "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )

    def receive(self, chunk: bytes) -> None:
        if not chunk or self._stop.is_set():
            return
        with self._write_lock:
            for process in (self._video, self._audio_process):
                if process.stdin is None or process.poll() is not None:
                    continue
                try:
                    process.stdin.write(chunk)
                    process.stdin.flush()
                except (BrokenPipeError, OSError) as exc:
                    self.error = f"ffmpeg_pipe: {type(exc).__name__}"
        self.bytes_received += len(chunk)
        self.chunks_received += 1

    def _read_video(self) -> None:
        stdout = self._video.stdout
        if stdout is None:
            return
        buffer = bytearray()
        try:
            while not self._stop.is_set():
                chunk = stdout.read(32768)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if start < 0 or end < 0:
                        if len(buffer) > 4 * 1024 * 1024:
                            del buffer[:-2]
                        break
                    jpeg = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    self.frames_emitted += 1
                    captured = now_ms()
                    self._frame_times.append(captured)
                    with self._audio_lock:
                        audio = bytes(self._audio[-self.audio_limit:]) if self._audio else None
                    self.sink(FramePacket(
                        sequence=self.frames_emitted,
                        captured_at_ms=captured,
                        jpeg=jpeg,
                        width=self.width,
                        height=0,
                        source_id=self.source_id,
                        source_kind="browser_webm",
                        audio_pcm=audio,
                    ))
        except (OSError, ValueError) as exc:
            self.error = f"video_decode: {type(exc).__name__}"

    def _read_audio(self) -> None:
        stdout = self._audio_process.stdout
        if stdout is None:
            return
        try:
            while not self._stop.is_set():
                chunk = stdout.read(16384)
                if not chunk:
                    break
                self.audio_bytes += len(chunk)
                with self._audio_lock:
                    self._audio.extend(chunk)
                    if len(self._audio) > self.audio_limit:
                        del self._audio[:-self.audio_limit]
        except (OSError, ValueError) as exc:
            self.error = f"audio_decode: {type(exc).__name__}"

    def health(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": "browser_webm",
            "camera_id": self.camera_id,
            "media_type": self.media_type,
            "running": not self._stop.is_set(),
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "frames_emitted": self.frames_emitted,
            "audio_bytes": self.audio_bytes,
            "error": self.error,
            "started_at_ms": self.started_at_ms,
        }

    def close(self) -> dict[str, Any]:
        if self._stop.is_set():
            return self.health()
        # Close stdin first and let FFmpeg reach EOF. The reader threads must
        # drain stdout before the stop event is set, otherwise the final
        # decoded frames of an uploaded file can be discarded during flush.
        with self._write_lock:
            for process in (self._video, self._audio_process):
                if process.stdin:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
        for process in (self._video, self._audio_process):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2)
        return self.health()
