"""FFmpeg helpers: probing, MJPEG decode, clip encode (docs/01_PIPELINE.md, 04).

Everything that knows about a codec lives here. The cascade above only
ever sees ``FramePacket`` and ``VideoClip``, which is what keeps the
domain code free of platform- and codec-specific assumptions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..domain.l3_contract import VideoClip

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


def ffmpeg_path() -> str | None:
    return shutil.which(os.environ.get("FFMPEG_BINARY", "ffmpeg"))


def ffprobe_path() -> str | None:
    return shutil.which(os.environ.get("FFPROBE_BINARY", "ffprobe"))


def available() -> bool:
    return ffmpeg_path() is not None


def version() -> str:
    binary = ffmpeg_path()
    if binary is None:
        return "unavailable"
    try:
        out = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.splitlines()[0] if out.stdout else "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def iter_mjpeg(stream) -> "object":
    """Yield complete JPEG frames from a raw MJPEG byte stream.

    FFmpeg's ``image2pipe`` output is a bare concatenation of JPEGs with
    no container framing, so we resynchronise on the SOI/EOI markers.
    Reading in chunks (rather than byte-by-byte) keeps a 4 fps decode
    well under one core.
    """
    buffer = bytearray()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            start = buffer.find(JPEG_SOI)
            if start < 0:
                buffer.clear()
                break
            end = buffer.find(JPEG_EOI, start + 2)
            if end < 0:
                if start > 0:
                    del buffer[:start]
                break
            frame = bytes(buffer[start : end + 2])
            del buffer[: end + 2]
            yield frame


def decode_command(uri: str, fps: float, width: int, transport: str = "tcp",
                   target_height: int | None = None) -> list[str]:
    """FFmpeg args that turn any source URI into an MJPEG pipe."""
    binary = ffmpeg_path() or "ffmpeg"
    args = [binary, "-hide_banner", "-loglevel", "error"]
    if uri.startswith("rtsp://"):
        # TCP avoids the UDP packet loss that shreds JPEG frames on Wi-Fi.
        args += ["-rtsp_transport", transport, "-stimeout", "5000000"]
    scale = f"scale=-2:{target_height}" if target_height else f"scale={width}:-2"
    args += [
        "-i", uri,
        "-an",
        "-vf", f"fps={fps},{scale}",
        "-q:v", "6",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-",
    ]
    return args


def transcode_to_480p(input_path: str | Path, output_path: str | Path,
                      *, start_sec: float = 0.0, height: int = 480,
                      timeout_sec: float = 3600.0) -> dict[str, float | int | str]:
    """Persist an uploaded video as a bounded 480p analysis source.

    Seeking happens after the input is opened so ``start_sec`` is precise.
    Audio is retained when present and normalised to mono 16 kHz, matching
    the browser-media path's PCM contract. The source is intentionally
    written to disk before replay so upload and analysis have separate
    lifecycles and can be audited.
    """
    binary = ffmpeg_path()
    if binary is None:
        raise RuntimeError("ffmpeg_unavailable")
    source = Path(input_path)
    output = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if start_sec < 0:
        raise ValueError("start_sec must be non-negative")
    if height < 2:
        raise ValueError("height must be at least 2")
    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        binary, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-ss", f"{start_sec:.3f}",
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", f"scale=-2:{height}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ac", "1", "-ar", "16000",
        "-movflags", "+faststart", str(output),
    ]
    proc = subprocess.run(args, capture_output=True, timeout=timeout_sec, check=False)
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        detail = proc.stderr.decode("utf-8", "replace")[:600]
        raise RuntimeError(f"ffmpeg_transcode_failed: {detail}")
    return {"path": str(output), "height": height,
            "start_sec": start_sec, "size_bytes": output.stat().st_size}


def encode_clip(
    frames: list[bytes],
    out_path: Path,
    fps: float,
    started_at_ms: int,
) -> VideoClip:
    """Mux JPEG frames into an H.264 MP4 for the multimodal models.

    docs/01_PIPELINE.md hands L2 and L3 a *short video*, not a frame array: a clip is
    one inline part instead of N, it carries real timing, and it is what
    both providers document support for.
    """
    binary = ffmpeg_path()
    if binary is None:
        raise RuntimeError("ffmpeg_unavailable")
    if not frames:
        raise ValueError("no frames to encode")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        binary, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        # yuv420p needs even dimensions; pad up rather than crop down so an
        # odd-sized source never silently loses its last row or column.
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(args, input=b"".join(frames), capture_output=True, timeout=60)
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg_encode_failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")

    return VideoClip(
        path=str(out_path),
        mime_type="video/mp4",
        duration_sec=len(frames) / fps if fps else 0.0,
        size_bytes=out_path.stat().st_size,
        started_at_ms=started_at_ms,
        frame_count=len(frames),
    )


def decode_gray(jpeg: bytes, width: int, height: int, timeout: float = 5.0) -> bytes | None:
    """Decode one JPEG to a raw 8-bit grayscale buffer of ``width*height``.

    FFmpeg is already a hard dependency for ingest and clip encoding, so
    reusing it as the decoder keeps the L1 detectors free of Pillow /
    OpenCV — which matters because docs/04_SETUP_DEPLOY_VERIFY.md forbids a heavy install before
    the user has chosen a detector in Setup.
    """
    binary = ffmpeg_path()
    if binary is None:
        return None
    args = [
        binary, "-hide_banner", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-i", "-",
        "-vf", f"scale={width}:{height}",
        "-pix_fmt", "gray", "-f", "rawvideo", "-",
    ]
    try:
        proc = subprocess.run(args, input=jpeg, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    expected = width * height
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return None
    return proc.stdout[:expected]


def decode_rgb(jpeg: bytes, width: int, height: int, timeout: float = 5.0) -> bytes | None:
    """Decode one JPEG to a raw packed RGB buffer of ``width*height*3``."""
    binary = ffmpeg_path()
    if binary is None:
        return None
    args = [
        binary, "-hide_banner", "-loglevel", "error",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-i", "-",
        # letterbox rather than distort: a stretched aspect ratio measurably
        # hurts a detector trained on square-ish letterboxed input.
        "-vf", (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        ),
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]
    try:
        proc = subprocess.run(args, input=jpeg, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    expected = width * height * 3
    if proc.returncode != 0 or len(proc.stdout) < expected:
        return None
    return proc.stdout[:expected]
