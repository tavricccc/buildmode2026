"""Replay sources (v5 00: same downstream contract as RTSP).

Two flavours:

``ReplaySource``   decodes a real video file through FFmpeg. This is what
                   you point at a recorded fall to check the pipeline
                   against footage.
``ScriptedSource`` plays a JSON manifest of annotated segments. No camera,
                   no video file, no model download — v5 04 gate 1 has to
                   run on a fresh Windows+WSL clone, and this is what makes
                   the replay tests deterministic rather than timing-
                   dependent.
"""

from __future__ import annotations

import base64
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..domain.timeutil import now_ms
from . import ffmpeg
from .frames import FramePacket
from .source import FrameSink

#: A 64x64 grey JPEG. ScriptedSource frames must be *valid* JPEG bytes so
#: that clip encoding and the wire format are exercised for real, but their
#: pixels carry no information — the ground truth rides in ``annotation``.
_TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAgAAAQABAAD//gAQTGF2YzYyLjI4LjEwMAD/2wBDAAgQEBMQExYWFhYWFhoY"
    "GhsbGxoaGhobGxsdHR0iIiIdHR0bGx0dICAiIiUmJSMjIiMmJigoKDAwLi44ODpFRVP/xABKAAEA"
    "AAAAAAAAAAAAAAAAAAAAAQEAAAAAAAAAAAAAAAAAAAAAEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAA"
    "AAAAAAAAAAAAAAAA/8AAEQgAQABAAwEiAAIRAAMRAP/aAAwDAQACEQMRAD8AAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAA/9k="
)

_TINY_W = _TINY_H = 64


class ScriptedSource:
    """Emit annotated frames from a manifest, in real time or as fast as possible."""

    source_kind = "replay"

    def __init__(
        self,
        manifest: dict[str, Any],
        source_id: str = "replay-scripted",
        fps: float = 4.0,
        realtime: bool = True,
    ) -> None:
        self.manifest = manifest
        self.source_id = source_id
        self.fps = fps
        self.realtime = realtime
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emitted = 0
        self._started_at_ms = 0

    @classmethod
    def from_file(cls, path: str | Path, **kwargs: Any) -> "ScriptedSource":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data, **kwargs)

    def frames(self, base_ms: int | None = None) -> list[FramePacket]:
        """Materialise the whole scenario. Used directly by replay tests."""
        base = now_ms() if base_ms is None else base_ms
        step_ms = int(1000 / self.fps)
        out: list[FramePacket] = []
        seq = 0
        cursor = base
        for segment in self.manifest.get("segments", []):
            count = max(1, int(round(float(segment.get("duration_sec", 1.0)) * self.fps)))
            annotation = {k: v for k, v in segment.items() if k != "duration_sec"}
            for _ in range(count):
                seq += 1
                out.append(
                    FramePacket(
                        sequence=seq,
                        captured_at_ms=cursor,
                        jpeg=_TINY_JPEG,
                        width=_TINY_W,
                        height=_TINY_H,
                        source_id=self.source_id,
                        source_kind=self.source_kind,
                        annotation=annotation,
                    )
                )
                cursor += step_ms
        return out

    def start(self, sink: FrameSink) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._started_at_ms = now_ms()

        def run() -> None:
            step = 1.0 / self.fps
            loop = bool(self.manifest.get("loop", False))
            while not self._stop.is_set():
                for packet in self.frames(base_ms=now_ms()):
                    if self._stop.is_set():
                        return
                    # Re-stamp so a looped fixture keeps advancing wall clock.
                    sink(
                        FramePacket(
                            sequence=packet.sequence,
                            captured_at_ms=now_ms(),
                            jpeg=packet.jpeg,
                            width=packet.width,
                            height=packet.height,
                            source_id=packet.source_id,
                            source_kind=packet.source_kind,
                            annotation=packet.annotation,
                        )
                    )
                    self._emitted += 1
                    if self.realtime:
                        self._stop.wait(step)
                if not loop:
                    return

        self._thread = threading.Thread(target=run, name="replay-scripted", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def health(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "kind": self.source_kind,
            "running": self._thread is not None and self._thread.is_alive(),
            "frames_emitted": self._emitted,
            "scenario": self.manifest.get("name", "unnamed"),
        }


class ReplaySource:
    """Decode a recorded video file through FFmpeg at a fixed sampling rate."""

    source_kind = "replay"

    def __init__(
        self,
        path: str | Path,
        source_id: str = "replay-file",
        fps: float = 4.0,
        width: int = 640,
        loop: bool = False,
        realtime: bool = False,
    ) -> None:
        self.path = str(path)
        self.source_id = source_id
        self.fps = fps
        self.width = width
        self.loop = loop
        self.realtime = realtime
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._emitted = 0
        self._error: str | None = None

    def start(self, sink: FrameSink) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def run() -> None:
            while not self._stop.is_set():
                try:
                    self._pump(sink)
                except Exception as exc:  # noqa: BLE001
                    self._error = str(exc)
                    return
                if not self.loop:
                    return

        self._thread = threading.Thread(target=run, name="replay-file", daemon=True)
        self._thread.start()

    def _pump(self, sink: FrameSink) -> None:
        args = ffmpeg.decode_command(self.path, self.fps, self.width)
        self._proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert self._proc.stdout is not None
        seq = 0
        started = time.monotonic()
        for jpeg in ffmpeg.iter_mjpeg(self._proc.stdout):
            if self._stop.is_set():
                break
            seq += 1
            # A demo upload is treated as a camera: each sampled frame enters
            # the downstream queue at its video-time offset, rather than all
            # decoded frames being injected as fast as FFmpeg can read them.
            if self.realtime:
                due = started + (seq - 1) / max(self.fps, 0.1)
                self._stop.wait(max(0.0, due - time.monotonic()))
                if self._stop.is_set():
                    break
            self._emitted += 1
            sink(
                FramePacket(
                    sequence=seq,
                    captured_at_ms=now_ms(),
                    jpeg=jpeg,
                    width=self.width,
                    height=0,
                    source_id=self.source_id,
                    source_kind=self.source_kind,
                )
            )
        self._proc.wait(timeout=5)

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def health(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "kind": self.source_kind,
            "running": (self._thread is not None and self._thread.is_alive()) or
                       (self._proc is not None and self._proc.poll() is None),
            "frames_emitted": self._emitted,
            "error": self._error,
            "path": self.path,
            "realtime": self.realtime,
        }
