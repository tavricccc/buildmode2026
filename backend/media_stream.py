from __future__ import annotations

import asyncio
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .change_gate import detect_frame_change
from .config import Settings
from .store import Store, make_id, now_iso


FrameWindowCallback = Callable[["StreamSession", tuple[bytes, ...], dict[str, Any], bytes | None], Awaitable[None]]
ChangeGateCallback = Callable[["StreamSession", tuple[bytes, ...], dict[str, Any], bytes | None], Awaitable[None]]
DescriptionWindowCallback = Callable[["StreamSession", tuple[bytes, ...], dict[str, Any], bytes | None], Awaitable[None]]
FocusWindowCallback = Callable[["StreamSession", tuple[bytes, ...], dict[str, Any], bytes | None], Awaitable[None]]


@dataclass
class StreamSession:
    id: str
    camera_id: str
    media_type: str
    started_at: str
    bridge_status: str
    rtsp_target: str | None
    started_mono: float = field(default_factory=time.monotonic)
    process: asyncio.subprocess.Process | None = None
    vlm_process: asyncio.subprocess.Process | None = None
    audio_process: asyncio.subprocess.Process | None = None
    detail_process: asyncio.subprocess.Process | None = None
    vlm_task: asyncio.Task | None = None
    audio_task: asyncio.Task | None = None
    detail_task: asyncio.Task | None = None
    analysis_tasks: set[asyncio.Task] = field(default_factory=set)
    vlm_status: str = "disabled"
    vlm_frames: int = 0
    vlm_windows: int = 0
    vlm_window_frames: int = 0
    gate_windows: int = 0
    gate_changed_windows: int = 0
    observation_windows: int = 0
    vlm_buffer: deque[tuple[int, bytes]] = field(default_factory=deque)
    vlm_last_window_mono: float | None = None
    last_observation_mono: float | None = None
    focus_request: dict[str, Any] | None = None
    focus_windows: int = 0
    detail_buffer: deque[tuple[int, bytes]] = field(default_factory=deque)
    detail_last_window_mono: float | None = None
    detail_active_until_mono: float | None = None
    detail_windows: int = 0
    detail_pending: int = 0
    detail_reason: str | None = None
    scene_context: dict[str, Any] | None = None
    scene_context_id: str | None = None
    focus_pending: int = 0
    raw_media_directory: str | None = None
    raw_media_path: str | None = None
    raw_media_segment_started_mono: float | None = None
    raw_media_segment_index: int = 0
    raw_media_bytes: int = 0
    audio_status: str = "disabled"
    audio_bytes: int = 0
    audio_windows: int = 0
    audio_buffer: bytearray = field(default_factory=bytearray)
    bytes_received: int = 0
    chunks_received: int = 0
    error_code: str | None = None
    last_observation: Any = None
    last_state_tracker: dict[str, Any] | None = None
    gate_event_keys: set[str] = field(default_factory=set)
    last_gate_audio_level: float | None = None
    last_main_agent_mono: float | None = None


class VirtualCameraBridge:
    """Receive continuous browser media and fan it to the observation layers."""

    def __init__(self, settings: Settings, store: Store, on_window: FrameWindowCallback | None = None,
                 on_change_gate: ChangeGateCallback | None = None,
                 on_description_window: DescriptionWindowCallback | None = None,
                 on_focus_window: FocusWindowCallback | None = None):
        self.settings = settings
        self.store = store
        self.on_window = on_window
        self.on_change_gate = on_change_gate
        self.on_description_window = on_description_window
        self.on_focus_window = on_focus_window
        self.sessions: dict[str, StreamSession] = {}
        self.audio_window_bytes = int(16000 * 2 * self.settings.vllm_window_seconds)
        self.detail_audio_window_bytes = int(16000 * 2 * self.settings.detail_window_seconds)
        self.focus_audio_window_bytes = int(16000 * 2 * self.settings.focus_window_seconds)

    async def open(self, camera_id: str, media_type: str) -> StreamSession:
        session = StreamSession(make_id("stream"), camera_id, media_type, now_iso(), "ingress_only", self.settings.frigate_rtsp_publish_url or None)
        session.vlm_buffer = deque(maxlen=max(self.settings.vllm_window_frames, self.settings.focus_window_frames))
        session.detail_buffer = deque(maxlen=self.settings.detail_window_frames * 3)
        raw_dir = Path(self.settings.media_root).resolve() / "rolling" / session.id
        raw_dir.mkdir(parents=True, exist_ok=True)
        session.raw_media_directory = str(raw_dir)
        session.raw_media_segment_started_mono = session.started_mono
        session.raw_media_path = str(raw_dir / "segment-000.webm")
        ffmpeg = shutil.which("ffmpeg")
        if not self.settings.virtual_camera_enabled:
            session.bridge_status = "disabled"
        elif session.rtsp_target and not ffmpeg:
            session.bridge_status = "unavailable"
            session.error_code = "FFMPEG_NOT_FOUND"
        elif session.rtsp_target:
            session.process = await self._start_ffmpeg(ffmpeg, [
                "-hide_banner", "-loglevel", "warning", "-fflags", "+genpts", "-i", "pipe:0",
                "-analyzeduration", "1000000", "-probesize", "1000000", "-c:v", "libx264",
                "-preset", "veryfast", "-tune", "zerolatency", "-c:a", "aac", "-f", "rtsp",
                "-rtsp_transport", "tcp", session.rtsp_target,
            ])
            session.bridge_status = "publishing" if session.process else "unavailable"
            if not session.process:
                session.error_code = "FFMPEG_START_FAILED"

        if self.on_window and self.settings.local_vlm_mode in {"vllm", "real"}:
            if not ffmpeg:
                session.vlm_status = "unavailable"
                session.audio_status = "unavailable"
                session.error_code = session.error_code or "FFMPEG_NOT_FOUND"
            else:
                session.vlm_process = await self._start_ffmpeg(ffmpeg, [
                    "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-i", "pipe:0",
                    "-vf", f"fps={self.settings.vllm_sample_fps},scale={self.settings.vllm_max_frame_width}:-2",
                    "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "6", "pipe:1",
                ], output_pipe=True)
                session.vlm_status = "sampling" if session.vlm_process else "unavailable"
                session.audio_process = await self._start_ffmpeg(ffmpeg, [
                    "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-i", "pipe:0",
                    "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
                ], output_pipe=True)
                if self.on_description_window:
                    session.detail_process = await self._start_ffmpeg(ffmpeg, [
                        "-hide_banner", "-loglevel", "error", "-fflags", "+genpts", "-i", "pipe:0",
                        "-vf", f"fps={self.settings.detail_sample_fps},scale={self.settings.vllm_max_frame_width}:-2",
                        "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "6", "pipe:1",
                    ], output_pipe=True)
                session.audio_status = "sampling" if session.audio_process else "unavailable"
                if session.vlm_process:
                    session.vlm_task = asyncio.create_task(self._read_vlm_frames(session), name=f"vlm-sampler-{session.id}")
                if session.audio_process:
                    session.audio_task = asyncio.create_task(self._read_audio(session), name=f"audio-sampler-{session.id}")
                if session.detail_process:
                    session.detail_task = asyncio.create_task(self._read_detail_frames(session), name=f"detail-sampler-{session.id}")
                if not session.vlm_process or not session.audio_process or (self.on_description_window and not session.detail_process):
                    session.error_code = session.error_code or "FFMPEG_MULTIMODAL_SAMPLER_START_FAILED"

        self.sessions[session.id] = session
        with self.store.db.transaction() as conn:
            conn.execute("INSERT INTO virtual_camera_streams(id,camera_id,media_type,started_at,bridge_status,rtsp_target,media_path,media_retention_seconds,vlm_status,vlm_frames,vlm_windows,vlm_window_frames,audio_status,audio_bytes,audio_windows) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (session.id, session.camera_id, session.media_type, session.started_at, session.bridge_status, session.rtsp_target,
                          session.raw_media_path, self.settings.video_retention_seconds, session.vlm_status, 0, 0,
                          self.settings.vllm_window_frames, session.audio_status, 0, 0))
        self.store.log("info", "virtual_camera", "Continuous browser media stream started", context={"stream_id": session.id, "camera_id": camera_id, "bridge_status": session.bridge_status, "vlm_status": session.vlm_status, "audio_status": session.audio_status, "window_frames": self.settings.vllm_window_frames, "window_seconds": self.settings.vllm_window_seconds, "sample_fps": self.settings.vllm_sample_fps})
        return session

    async def _start_ffmpeg(self, executable: str | None, args: list[str], output_pipe: bool = False) -> asyncio.subprocess.Process | None:
        if not executable:
            return None
        try:
            return await asyncio.create_subprocess_exec(executable, *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE if output_pipe else asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        except (OSError, ValueError):
            return None

    async def receive(self, session: StreamSession, chunk: bytes) -> StreamSession:
        if not chunk:
            return session
        session.bytes_received += len(chunk)
        session.chunks_received += 1
        self._persist_raw_chunk(session, chunk)
        for process, name in ((session.process, "rtsp"), (session.vlm_process, "vlm"), (session.audio_process, "audio"), (session.detail_process, "detail")):
            if process and process.stdin:
                try:
                    process.stdin.write(chunk)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionError):
                    if name == "rtsp":
                        session.bridge_status = "error"; session.error_code = "FFMPEG_PIPE_BROKEN"
                    elif name == "vlm":
                        session.vlm_status = "error"; session.error_code = session.error_code or "FFMPEG_VLM_PIPE_BROKEN"
                    elif name == "detail":
                        session.error_code = session.error_code or "FFMPEG_DETAIL_PIPE_BROKEN"
                    else:
                        session.audio_status = "error"; session.error_code = session.error_code or "FFMPEG_AUDIO_PIPE_BROKEN"
        if session.chunks_received % 4 == 0:
            self._persist_progress(session)
        return session

    def _persist_progress(self, session: StreamSession) -> None:
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE virtual_camera_streams SET bytes_received=?,chunks_received=?,bridge_status=?,media_path=?,media_retention_seconds=?,error_code=?,vlm_status=?,vlm_frames=?,vlm_windows=?,vlm_window_frames=?,audio_status=?,audio_bytes=?,audio_windows=? WHERE id=?",
                         (session.bytes_received, session.chunks_received, session.bridge_status, session.raw_media_path, self.settings.video_retention_seconds, session.error_code, session.vlm_status, session.vlm_frames, session.vlm_windows, session.vlm_window_frames, session.audio_status, session.audio_bytes, session.audio_windows, session.id))

    def _persist_raw_chunk(self, session: StreamSession, chunk: bytes) -> None:
        """Keep a rolling set of raw WebM bytes, bounded to one minute."""
        if not session.raw_media_path or session.raw_media_segment_started_mono is None:
            return
        now = time.monotonic()
        if now - session.raw_media_segment_started_mono >= self.settings.video_retention_seconds:
            session.raw_media_segment_index += 1
            session.raw_media_segment_started_mono = now
            session.raw_media_path = str(Path(session.raw_media_directory or ".") / f"segment-{session.raw_media_segment_index:03d}.webm")
            root = Path(session.raw_media_directory or ".")
            for old in root.glob("segment-*.webm"):
                if str(old) != session.raw_media_path:
                    try:
                        old.unlink()
                    except FileNotFoundError:
                        pass
        path = Path(session.raw_media_path)
        with path.open("ab") as output:
            output.write(chunk)
        session.raw_media_bytes += len(chunk)

    async def _read_audio(self, session: StreamSession) -> None:
        if not session.audio_process or not session.audio_process.stdout:
            return
        try:
            while True:
                chunk = await session.audio_process.stdout.read(16384)
                if not chunk:
                    break
                session.audio_bytes += len(chunk)
                session.audio_buffer.extend(chunk)
                max_buffer = self.audio_window_bytes * 2
                if len(session.audio_buffer) > max_buffer:
                    del session.audio_buffer[:-max_buffer]
                if session.audio_status == "sampling" and len(session.audio_buffer) >= self.audio_window_bytes:
                    session.audio_status = "ready"
                if session.audio_bytes % (16384 * 4) < len(chunk):
                    self._persist_progress(session)
        except (asyncio.CancelledError, BrokenPipeError, ConnectionError):
            raise
        except Exception:
            session.audio_status = "error"
            session.error_code = session.error_code or "AUDIO_FRAME_PIPE_FAILED"

    async def _read_vlm_frames(self, session: StreamSession) -> None:
        if not session.vlm_process or not session.vlm_process.stdout or not (self.on_window or self.on_change_gate):
            return
        buffer = bytearray()
        try:
            while True:
                chunk = await session.vlm_process.stdout.read(32768)
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
                    session.vlm_frames += 1
                    offset_ms = int((time.monotonic() - session.started_mono) * 1000)
                    session.vlm_buffer.append((offset_ms, jpeg))
                    self._schedule_focus_if_ready(session)
                    if len(session.vlm_buffer) < self.settings.vllm_window_frames:
                        continue
                    now = time.monotonic()
                    if session.vlm_last_window_mono is not None and now - session.vlm_last_window_mono < self.settings.vllm_window_stride_seconds:
                        continue
                    session.vlm_last_window_mono = now
                    window_items = tuple(list(session.vlm_buffer)[-self.settings.vllm_window_frames:])
                    session.vlm_window_frames = len(window_items)
                    audio_pcm = bytes(session.audio_buffer[-self.audio_window_bytes:]) if len(session.audio_buffer) >= self.audio_window_bytes else None
                    session.gate_windows += 1
                    window = {"window_id": f"{session.id}:g{session.gate_windows}", "start_offset_ms": window_items[0][0], "end_offset_ms": window_items[-1][0], "frame_count": len(window_items), "sample_fps": self.settings.vllm_sample_fps, "window_seconds": self.settings.vllm_window_seconds, "stride_seconds": self.settings.vllm_window_stride_seconds, "audio_present": audio_pcm is not None, "audio_sample_rate": 16000, "audio_duration_ms": int(len(audio_pcm) / 32) if audio_pcm else 0, "stage": "change_gate", "gate_frame_indexes": [0, len(window_items) - 1]}
                    self._persist_progress(session)
                    if len(session.analysis_tasks) >= self.settings.vllm_max_pending_windows:
                        self.store.log("warning", "virtual_camera", "VLM window skipped because pending limit was reached", context={"stream_id": session.id, "window_id": window["window_id"], "pending": len(session.analysis_tasks), "max_pending": self.settings.vllm_max_pending_windows})
                        continue
                    callback = self.on_change_gate or self.on_window
                    if callback is None:
                        continue
                    task = asyncio.create_task(callback(session, tuple(item[1] for item in window_items), window, audio_pcm), name=f"change-gate-window-{window['window_id']}")
                    session.analysis_tasks.add(task)
                    task.add_done_callback(lambda completed, current=session: (current.analysis_tasks.discard(completed), completed.exception() if not completed.cancelled() else None))
        except (asyncio.CancelledError, BrokenPipeError, ConnectionError):
            raise
        except Exception:
            session.vlm_status = "error"
            session.error_code = session.error_code or "VLM_FRAME_PIPE_FAILED"

    async def _read_detail_frames(self, session: StreamSession) -> None:
        if not session.detail_process or not session.detail_process.stdout or not self.on_description_window:
            return
        buffer = bytearray()
        try:
            while True:
                chunk = await session.detail_process.stdout.read(32768)
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
                    offset_ms = int((time.monotonic() - session.started_mono) * 1000)
                    session.detail_buffer.append((offset_ms, jpeg))
                    now = time.monotonic()
                    if not session.detail_active_until_mono or now > session.detail_active_until_mono:
                        continue
                    if len(session.detail_buffer) < self.settings.detail_window_frames:
                        continue
                    if session.detail_last_window_mono is not None and now - session.detail_last_window_mono < self.settings.detail_window_stride_seconds:
                        continue
                    if session.detail_pending >= self.settings.detail_max_pending:
                        continue
                    session.detail_last_window_mono = now
                    session.detail_windows += 1
                    items = tuple(list(session.detail_buffer)[-self.settings.detail_window_frames:])
                    audio_pcm = bytes(session.audio_buffer[-self.detail_audio_window_bytes:]) if len(session.audio_buffer) >= self.detail_audio_window_bytes else None
                    window = {"window_id": f"{session.id}:d{session.detail_windows}", "trigger_window_id": session.detail_reason,
                              "start_offset_ms": items[0][0], "end_offset_ms": items[-1][0], "frame_count": len(items),
                              "sample_fps": self.settings.detail_sample_fps, "window_seconds": self.settings.detail_window_seconds,
                              "stride_seconds": self.settings.detail_window_stride_seconds, "audio_present": audio_pcm is not None,
                              "audio_sample_rate": 16000, "audio_duration_ms": int(len(audio_pcm) / 32) if audio_pcm else 0,
                              "description_reason": session.detail_reason}
                    session.detail_pending += 1
                    self._schedule_callback(session, self.on_description_window, tuple(item[1] for item in items), window, audio_pcm,
                                             f"description-window-{window['window_id']}", "detail")
        except (asyncio.CancelledError, BrokenPipeError, ConnectionError):
            raise
        except Exception:
            session.error_code = session.error_code or "DETAIL_FRAME_PIPE_FAILED"

    def trigger_detail(self, session: StreamSession, *, reason: str, source_window_id: str) -> dict[str, Any]:
        now = time.monotonic()
        session.detail_active_until_mono = max(session.detail_active_until_mono or 0, now + self.settings.detail_active_seconds)
        session.detail_reason = f"{source_window_id}:{reason}"
        session.detail_last_window_mono = None
        self._persist_progress(session)
        return self.snapshot(session)

    def request_focus(self, session: StreamSession, *, reason: str, source_window_id: str,
                      context: dict[str, Any]) -> dict[str, Any]:
        if session.focus_request is None:
            session.focus_request = {"reason": reason, "source_window_id": source_window_id, "context": context}
        return self.snapshot(session)

    def _schedule_focus_if_ready(self, session: StreamSession) -> None:
        if not self.on_focus_window or not session.focus_request or len(session.vlm_buffer) < self.settings.focus_window_frames:
            return
        if session.focus_pending >= 1 or len(session.analysis_tasks) >= self.settings.vllm_max_pending_windows:
            return
        request = session.focus_request
        session.focus_request = None
        session.focus_windows += 1
        items = tuple(list(session.vlm_buffer)[-self.settings.focus_window_frames:])
        audio_pcm = bytes(session.audio_buffer[-self.focus_audio_window_bytes:]) if len(session.audio_buffer) >= self.focus_audio_window_bytes else None
        window = {"window_id": f"{session.id}:f{session.focus_windows}", "trigger_window_id": request["source_window_id"],
                  "start_offset_ms": items[0][0], "end_offset_ms": items[-1][0], "frame_count": len(items),
                  "sample_fps": self.settings.vllm_sample_fps, "window_seconds": self.settings.focus_window_seconds,
                  "audio_present": audio_pcm is not None, "audio_sample_rate": 16000,
                  "audio_duration_ms": int(len(audio_pcm) / 32) if audio_pcm else 0,
                  "focus_reason": request["reason"], "focus_context": request["context"]}
        session.focus_pending += 1
        self._schedule_callback(session, self.on_focus_window, tuple(item[1] for item in items), window, audio_pcm,
                                 f"focus-window-{window['window_id']}", "focus")

    def _schedule_callback(self, session: StreamSession, callback: Callable[..., Awaitable[None]],
                           images: tuple[bytes, ...], window: dict[str, Any], audio_pcm: bytes | None,
                           name: str, kind: str) -> None:
        async def run() -> None:
            try:
                await callback(session, images, window, audio_pcm)
            finally:
                if kind == "detail":
                    session.detail_pending = max(0, session.detail_pending - 1)
                elif kind == "focus":
                    session.focus_pending = max(0, session.focus_pending - 1)

        task = asyncio.create_task(run(), name=name)
        session.analysis_tasks.add(task)
        task.add_done_callback(lambda completed, current=session: (current.analysis_tasks.discard(completed), completed.exception() if not completed.cancelled() else None))

    async def _close_process(self, process: asyncio.subprocess.Process | None) -> None:
        if not process:
            return
        if process.stdin:
            try:
                process.stdin.close()
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionError):
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def close(self, session: StreamSession) -> dict[str, Any]:
        for task in (session.vlm_task, session.audio_task, session.detail_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        session.vlm_task = None; session.audio_task = None; session.detail_task = None
        for task in list(session.analysis_tasks):
            task.cancel()
        if session.analysis_tasks:
            await asyncio.gather(*session.analysis_tasks, return_exceptions=True)
        session.analysis_tasks.clear()
        await self._close_process(session.vlm_process)
        await self._close_process(session.audio_process)
        await self._close_process(session.detail_process)
        await self._close_process(session.process)
        ended_at = now_iso()
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE virtual_camera_streams SET ended_at=?,bytes_received=?,chunks_received=?,bridge_status=?,media_path=?,media_retention_seconds=?,error_code=?,vlm_status=?,vlm_frames=?,vlm_windows=?,vlm_window_frames=?,audio_status=?,audio_bytes=?,audio_windows=? WHERE id=?",
                         (ended_at, session.bytes_received, session.chunks_received, session.bridge_status, session.raw_media_path, self.settings.video_retention_seconds, session.error_code, session.vlm_status, session.vlm_frames, session.vlm_windows, session.vlm_window_frames, session.audio_status, session.audio_bytes, session.audio_windows, session.id))
        self.sessions.pop(session.id, None)
        self.store.log("info", "virtual_camera", "Continuous browser media stream stopped", context={"stream_id": session.id, "camera_id": session.camera_id, "bytes_received": session.bytes_received, "chunks_received": session.chunks_received, "raw_media_path": session.raw_media_path, "raw_media_bytes": session.raw_media_bytes, "raw_media_retention_seconds": self.settings.video_retention_seconds, "vlm_frames": session.vlm_frames, "vlm_windows": session.vlm_windows, "vlm_window_frames": session.vlm_window_frames, "detail_windows": session.detail_windows, "audio_bytes": session.audio_bytes, "audio_windows": session.audio_windows, "bridge_status": session.bridge_status, "vlm_status": session.vlm_status, "audio_status": session.audio_status})
        return self.snapshot(session)

    def snapshot(self, session: StreamSession) -> dict[str, Any]:
        return {"stream_id": session.id, "camera_id": session.camera_id, "media_type": session.media_type, "started_at": session.started_at,
                "bytes_received": session.bytes_received, "chunks_received": session.chunks_received, "bridge_status": session.bridge_status,
                "vlm_status": session.vlm_status, "vlm_frames": session.vlm_frames, "vlm_windows": session.vlm_windows, "vlm_window_frames": session.vlm_window_frames,
                "gate_windows": session.gate_windows, "gate_changed_windows": session.gate_changed_windows, "observation_windows": session.observation_windows,
                "vlm_sample_fps": self.settings.vllm_sample_fps, "vlm_window_seconds": self.settings.vllm_window_seconds, "vlm_window_stride_seconds": self.settings.vllm_window_stride_seconds,
                "audio_status": session.audio_status, "audio_bytes": session.audio_bytes, "audio_windows": session.audio_windows, "audio_sample_rate": 16000,
                "detail_sample_fps": self.settings.detail_sample_fps, "detail_window_seconds": self.settings.detail_window_seconds,
                "detail_windows": session.detail_windows, "detail_pending": session.detail_pending, "detail_active": bool(session.detail_active_until_mono and session.detail_active_until_mono > time.monotonic()),
                "focus_windows": session.focus_windows, "focus_pending": session.focus_pending, "focus_requested": bool(session.focus_request), "scene_context": session.scene_context,
                "raw_media_path": session.raw_media_path, "raw_media_bytes": session.raw_media_bytes, "raw_media_retention_seconds": self.settings.video_retention_seconds,
                "analysis_pending": len(session.analysis_tasks), "analysis_parallel_limit": self.settings.vllm_max_concurrency,
                "analysis_pending_limit": self.settings.vllm_max_pending_windows,
                "rtsp_target_configured": bool(session.rtsp_target), "error_code": session.error_code,
                "last_observation": session.last_observation.model_dump() if hasattr(session.last_observation, "model_dump") else session.last_observation,
                "state_tracker": session.last_state_tracker}

    def active_snapshot(self) -> list[dict[str, Any]]:
        return [self.snapshot(session) for session in self.sessions.values()]

    def reset_analysis_state(self) -> None:
        """Re-baseline active streams after history reset without stopping media."""
        for session in self.sessions.values():
            session.last_observation = None
            session.last_state_tracker = None
            session.gate_event_keys.clear()
            session.last_gate_audio_level = None
            session.last_main_agent_mono = None
            session.scene_context = None
            session.scene_context_id = None
            session.gate_windows = 0
            session.gate_changed_windows = 0
            session.observation_windows = 0
            session.vlm_windows = 0
            session.audio_windows = 0
            session.detail_windows = 0
            session.focus_windows = 0
