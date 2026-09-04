"""Command line entry point for local capture."""

from __future__ import annotations

import argparse
from pathlib import Path

from .models import CaptureConfig
from .runner import LocalCapture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a local microphone/camera event bundle")
    parser.add_argument("--duration", type=float, default=10.0, help="capture duration in seconds")
    parser.add_argument("--camera", type=int, default=0, help="camera device index")
    parser.add_argument("--audio-device", default=None, help="sounddevice input device name or index")
    parser.add_argument("--subject-id", default="resident_001")
    parser.add_argument("--source-id", default="local-mac")
    parser.add_argument("--output", type=Path, default=Path("data/captures"))
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--no-video", action="store_true", help="disable camera capture")
    parser.add_argument("--no-audio", action="store_true", help="disable microphone capture")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audio_device: int | str | None = args.audio_device
    if isinstance(audio_device, str) and audio_device.isdigit():
        audio_device = int(audio_device)
    config = CaptureConfig(
        subject_id=args.subject_id,
        source_id=args.source_id,
        camera_index=args.camera,
        audio_device=audio_device,
        sample_rate=args.sample_rate,
        channels=args.channels,
        frame_rate=args.fps,
        duration_seconds=args.duration,
        output_dir=args.output,
        enable_video=not args.no_video,
        enable_audio=not args.no_audio,
    )
    try:
        bundle_path = LocalCapture(config).record()
    except KeyboardInterrupt:
        print("capture cancelled")
        return 130
    except Exception as exc:
        print(f"capture failed: {exc}")
        return 1
    print(f"bundle written: {bundle_path}")
    return 0

