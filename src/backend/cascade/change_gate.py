"""Cheap temporal gate ported from the original Longcare media pipeline."""

from __future__ import annotations

import math
from array import array
from io import BytesIO
from typing import Any


def audio_level(audio_pcm: bytes | None) -> float | None:
    if not audio_pcm or len(audio_pcm) < 4:
        return None
    samples = array("h")
    samples.frombytes(audio_pcm[: len(audio_pcm) - (len(audio_pcm) % 2)])
    if not samples:
        return None
    step = max(1, len(samples) // 8000)
    selected = list(samples[::step])
    return round(math.sqrt(sum((item / 32768.0) ** 2 for item in selected) / len(selected)), 5)


def detect_frame_change(
    images: tuple[bytes, ...] | list[bytes],
    *,
    threshold: float = 0.06,
    audio_pcm: bytes | None = None,
    previous_audio_level: float | None = None,
    audio_delta_threshold: float = 0.06,
    min_changed_pairs: int = 2,
    strong_score_multiplier: float = 2.5,
) -> dict[str, Any]:
    """Return a fail-open change decision over an ordered media window.

    Pillow is optional.  When it is unavailable the gate deliberately sends
    the window onward rather than claiming that two JPEG byte strings are
    semantically equal.
    """
    current_audio = audio_level(audio_pcm)
    audio_changed = bool(
        current_audio is not None and previous_audio_level is not None
        and current_audio >= 0.02
        and abs(current_audio - previous_audio_level) >= audio_delta_threshold
    )
    if len(images) < 2:
        return _decision(True, 1.0, ["insufficient_frames"], current_audio, audio_changed)
    try:
        from PIL import Image, ImageChops, ImageStat  # type: ignore

        frames = []
        for image in images:
            with Image.open(BytesIO(image)) as decoded:
                frames.append(decoded.convert("L").resize((96, 54)).copy())
        pair_scores = []
        for first, second in zip(frames, frames[1:]):
            difference = ImageChops.difference(first, second)
            pair_scores.append(float(ImageStat.Stat(difference).mean[0]) / 255.0)
        score = max(pair_scores or [0.0])
        changed_pairs = sum(value >= threshold for value in pair_scores)
        strong = threshold * max(1.0, strong_score_multiplier)
        visual_changed = changed_pairs >= max(1, min_changed_pairs) or score >= strong
        changed = visual_changed or audio_changed
        reasons = []
        if visual_changed:
            reasons.append("temporal_pixel_delta_persistent" if changed_pairs >= max(1, min_changed_pairs) else "temporal_pixel_delta_strong_jump")
        if audio_changed:
            reasons.append("audio_energy_changed")
        result = _decision(changed, score, reasons or ["temporal_pixel_delta_below_threshold"], current_audio, audio_changed)
        result.update({"peak_pair_index": pair_scores.index(score) if pair_scores else None,
                       "changed_pair_count": changed_pairs,
                       "min_changed_pairs": min_changed_pairs,
                       "strong_score_threshold": round(strong, 5)})
        return result
    except Exception as exc:  # noqa: BLE001 - gate must fail open
        return _decision(True, None, ["change_gate_error", type(exc).__name__], current_audio, audio_changed)


def _decision(changed: bool, score: float | None, reasons: list[str],
              current_audio: float | None, audio_changed: bool) -> dict[str, Any]:
    return {
        "changed": changed,
        "change_score": round(score, 5) if isinstance(score, (int, float)) else None,
        "change_summary": "偵測到影像或音訊狀態變化，送第二層觀察。" if changed else "目前影像與音訊沒有超過門檻的變化。",
        "change_reasons": reasons,
        "method": "local_pixel_delta_plus_audio",
        "audio_level": current_audio,
        "audio_changed": audio_changed,
    }
