"""Shared probe scaffolding (docs/04_SETUP_DEPLOY_VERIFY.md §Capability probes).

The rule these scripts exist to enforce: "Provider 文件沒保證的能力，不可
直接寫成 runtime 假設，以 probe 結果為準." Every capability the cascade
depends on is checked against the *actual* deployment, and the report says
what was measured rather than what a docs page claims.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    latency_ms: int | None = None
    skipped: bool = False


@dataclass
class Report:
    provider: str
    model: str
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        mark = "SKIP" if check.skipped else ("PASS" if check.passed else "FAIL")
        latency = f"  {check.latency_ms} ms" if check.latency_ms is not None else ""
        print(f"  [{mark}] {check.name}{latency}")
        if check.detail:
            for line in check.detail.splitlines():
                print(f"         {line}")
        return check

    def summarise(self) -> int:
        run = [c for c in self.checks if not c.skipped]
        failed = [c for c in run if not c.passed]
        print(f"\n{self.provider} · {self.model}")
        print(f"  {len(run) - len(failed)}/{len(run)} checks passed"
              f"{f', {len(self.checks) - len(run)} skipped' if len(run) != len(self.checks) else ''}")
        if failed:
            print("\nCapabilities this deployment does NOT have:")
            for check in failed:
                print(f"  · {check.name}")
            print("\nDo not write these into runtime assumptions. Adjust the config,\n"
                  "or the spec, to match what was measured here.")
        return 1 if failed else 0


def timed(fn):
    started = time.perf_counter()
    try:
        result = fn()
        return result, int((time.perf_counter() - started) * 1000), None
    except Exception as exc:  # noqa: BLE001 - a probe reports failures, never raises
        return None, int((time.perf_counter() - started) * 1000), exc


def make_clip(seconds: float = 4.0, fps: int = 4, size: str = "320x240",
              with_audio: bool = False) -> Path:
    """Synthesise a small test clip so a probe needs no fixture assets."""
    out = Path(tempfile.gettempdir()) / f"care-probe-{int(seconds)}s{'-audio' if with_audio else ''}.mp4"
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                 "-c:a", "aac", "-shortest"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.run(args, capture_output=True, timeout=90)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    return out


def clip_frames(path: Path, limit: int = 10) -> list[bytes]:
    """Extract JPEG frames from a clip, the way the L3 adapter does."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-vf", "fps=2", "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        capture_output=True, timeout=60,
    )
    from backend.media.ffmpeg import JPEG_EOI, JPEG_SOI

    frames: list[bytes] = []
    buffer = proc.stdout
    cursor = 0
    while len(frames) < limit:
        start = buffer.find(JPEG_SOI, cursor)
        if start < 0:
            break
        end = buffer.find(JPEG_EOI, start + 2)
        if end < 0:
            break
        frames.append(buffer[start:end + 2])
        cursor = end + 2
    return frames


def read_key(env_name: str, args: argparse.Namespace) -> str:
    import os

    if getattr(args, "key", None):
        return str(args.key)
    if getattr(args, "key_file", None):
        return Path(args.key_file).read_text(encoding="utf-8").strip()
    from backend.config import AppConfig

    stored = AppConfig().secret_store().get(env_name)
    if stored:
        return stored
    value = os.environ.get(env_name)
    if not value:
        print(f"No {env_name} found. Pass --key, --key-file, set the environment\n"
              f"variable, or configure it in Setup first.")
        raise SystemExit(2)
    return value


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--key", help="API key (prefer --key-file or the secret store)")
    parser.add_argument("--key-file", help="file containing the API key")
    parser.add_argument("--model", help="override the configured model id")
    parser.add_argument("--base-url", help="override the configured base URL")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser
