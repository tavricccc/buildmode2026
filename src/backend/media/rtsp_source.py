"""Live RTSP source with bounded reconnect (docs/04_SETUP_DEPLOY_VERIFY.md gate 5).

Structurally the same as :class:`ReplaySource` — same ``FrameSource``
contract, same MJPEG pipe — with the one thing a live camera needs and a
file does not: it comes back after the network drops, with exponential
backoff so a camera that is genuinely gone does not spin the CPU.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Any

from ..domain.timeutil import now_ms
from . import ffmpeg
from .frames import FramePacket
from .source import FrameSink


class RtspSource:
    source_kind = "rtsp"

    def __init__(
        self,
        uri: str,
        source_id: str = "rtsp-main",
        fps: float = 4.0,
        width: int = 640,
        transport: str = "tcp",
        max_backoff_sec: float = 30.0,
    ) -> None:
        self.uri = uri
        self.source_id = source_id
        self.fps = fps
        self.width = width
        self.transport = transport
        self.max_backoff_sec = max_backoff_sec
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emitted = 0
        self._reconnects = 0
        self._last_frame_ms = 0
        self._error: str | None = None

    def start(self, sink: FrameSink) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def run() -> None:
            backoff = 1.0
            while not self._stop.is_set():
                try:
                    produced = self._pump(sink)
                    self._error = None
                    # A session that produced frames earns a fresh backoff.
                    backoff = 1.0 if produced else min(backoff * 2, self.max_backoff_sec)
                except Exception as exc:  # noqa: BLE001
                    self._error = str(exc)
                    backoff = min(backoff * 2, self.max_backoff_sec)
                if self._stop.is_set():
                    return
                self._reconnects += 1
                self._stop.wait(backoff)

        self._thread = threading.Thread(target=run, name="rtsp-source", daemon=True)
        self._thread.start()

    def _pump(self, sink: FrameSink) -> int:
        args = ffmpeg.decode_command(self.uri, self.fps, self.width, self.transport)
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert self._proc.stdout is not None
        produced = 0
        for jpeg in ffmpeg.iter_mjpeg(self._proc.stdout):
            if self._stop.is_set():
                break
            produced += 1
            self._emitted += 1
            self._last_frame_ms = now_ms()
            sink(
                FramePacket(
                    sequence=self._emitted,
                    captured_at_ms=self._last_frame_ms,
                    jpeg=jpeg,
                    width=self.width,
                    height=0,
                    source_id=self.source_id,
                    source_kind=self.source_kind,
                )
            )
        return produced

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def health(self) -> dict[str, Any]:
        age = now_ms() - self._last_frame_ms if self._last_frame_ms else None
        return {
            "source_id": self.source_id,
            "kind": self.source_kind,
            "running": self._proc is not None and self._proc.poll() is None,
            "frames_emitted": self._emitted,
            "reconnects": self._reconnects,
            "last_frame_age_ms": age,
            "error": self._error,
            # The URI can carry a password — never expose it (docs/04_SETUP_DEPLOY_VERIFY.md §Secrets).
            "uri_host": self.uri.split("@")[-1].split("/")[0] if self.uri else "",
        }
