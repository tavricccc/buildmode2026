"""Synchronous local camera + microphone capture runner."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import time
import wave

from .models import CaptureConfig, EvidenceRef, EventCandidate, MultimodalEventBundle


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_ref(event_dir: Path, path: Path) -> str:
    return path.relative_to(event_dir.parent.parent).as_posix()


def _write_wav(path: Path, chunks: list[object], sample_rate: int, channels: int) -> int:
    import numpy as np

    if not chunks:
        return 0
    samples = np.concatenate([np.asarray(chunk, dtype=np.int16) for chunk in chunks], axis=0)
    if samples.ndim == 1 and channels > 1:
        samples = samples.reshape(-1, channels)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(samples.astype(np.int16).tobytes())
    return int(samples.shape[0])


class LocalCapture:
    """Capture a bounded local window and write a replayable event bundle."""

    def __init__(self, config: CaptureConfig):
        self.config = config

    def record(self) -> Path:
        if self.config.duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than zero")
        if not self.config.enable_video and not self.config.enable_audio:
            raise ValueError("at least one of video or audio must be enabled")

        import cv2

        candidate = EventCandidate.start(self.config.subject_id, self.config.source_id)
        event_dir = self.config.output_dir / candidate.event_id
        frames_dir = event_dir / "frames"
        event_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        audio_chunks: list[object] = []
        audio_stream = None
        camera = None
        writer = None
        frame_count = 0
        keyframe_count = 0
        camera_opened = False
        audio_opened = False
        started = time.monotonic()
        next_keyframe = started
        video_path = event_dir / "video.mp4"
        audio_path = event_dir / "audio.wav"

        try:
            if self.config.enable_audio:
                import sounddevice as sd

                def on_audio(indata, _frames, _time, status):
                    if status:
                        return
                    audio_chunks.append(indata.copy())

                audio_stream = sd.InputStream(
                    samplerate=self.config.sample_rate,
                    channels=self.config.channels,
                    dtype="int16",
                    device=self.config.audio_device,
                    callback=on_audio,
                )
                audio_stream.start()
                audio_opened = True

            if self.config.enable_video:
                camera = cv2.VideoCapture(self.config.camera_index)
                camera_opened = bool(camera.isOpened())
                if not camera_opened:
                    raise RuntimeError(f"cannot open camera index {self.config.camera_index}")

            while time.monotonic() - started < self.config.duration_seconds:
                if self.config.enable_video:
                    ok, frame = camera.read()
                    if not ok:
                        raise RuntimeError("camera returned an invalid frame")
                    height, width = frame.shape[:2]
                    if writer is None:
                        writer = cv2.VideoWriter(
                            str(video_path),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            self.config.frame_rate,
                            (width, height),
                        )
                        if not writer.isOpened():
                            writer.release()
                            writer = None
                    if writer is not None:
                        writer.write(frame)
                    frame_count += 1
                    now = time.monotonic()
                    if now >= next_keyframe:
                        frame_path = frames_dir / f"frame-{keyframe_count:05d}.jpg"
                        if cv2.imwrite(str(frame_path), frame):
                            keyframe_count += 1
                        next_keyframe = now + self.config.keyframe_interval_seconds
                    time.sleep(max(0.0, 1.0 / self.config.frame_rate))
                else:
                    time.sleep(0.05)
        except KeyboardInterrupt:
            candidate.finish("cancelled")
        except Exception:
            candidate.finish("partial")
            raise
        finally:
            if writer is not None:
                writer.release()
            if camera is not None:
                camera.release()
            if audio_stream is not None:
                audio_stream.stop()
                audio_stream.close()

        if candidate.status == "capturing":
            candidate.finish("completed")

        audio_samples = _write_wav(audio_path, audio_chunks, self.config.sample_rate, self.config.channels)
        evidence: list[EvidenceRef] = []
        if video_path.exists() and video_path.stat().st_size > 0:
            evidence.append(EvidenceRef("video_clip", _relative_ref(event_dir, video_path), "video/mp4", file_sha256(video_path)))
        for frame_path in sorted(frames_dir.glob("*.jpg")):
            evidence.append(EvidenceRef("video_frame", _relative_ref(event_dir, frame_path), "image/jpeg", file_sha256(frame_path)))
        if audio_path.exists() and audio_path.stat().st_size > 44:
            evidence.append(EvidenceRef("audio_clip", _relative_ref(event_dir, audio_path), "audio/wav", file_sha256(audio_path)))

        bundle = MultimodalEventBundle(
            candidate=candidate,
            evidence=evidence,
            modalities={
                "audio": {"status": "captured" if audio_samples else "unavailable", "next": "ASR / audio event classifier"},
                "video": {"status": "captured" if frame_count else "unavailable", "next": "Video VLM"},
            },
            quality={
                "camera_opened": camera_opened,
                "audio_stream_opened": audio_opened,
                "frame_count": frame_count,
                "keyframe_count": keyframe_count,
                "audio_samples": audio_samples,
                "duration_seconds": self.config.duration_seconds,
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            },
        )
        bundle_path = event_dir / "bundle.json"
        bundle.write_json(bundle_path)
        return bundle_path

