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
    return round(math.sqrt(sum((samples[index] / 32768.0) ** 2 for index in range(0, len(samples), step)) / len(range(0, len(samples), step))), 5)


def detect_frame_change(images: tuple[bytes, ...] | list[bytes], *, threshold: float = 0.045,
                        audio_pcm: bytes | None = None, previous_audio_level: float | None = None,
                        audio_delta_threshold: float = 0.06, min_changed_pairs: int = 2,
                        strong_score_multiplier: float = 2.5) -> dict[str, Any]:
    """Fast, local change gate over the full temporal window.

    This is intentionally not semantic recognition. It only decides whether
    the expensive multimodal observation layer should receive the window.
    Invalid or underspecified input fails open so a potentially meaningful
    window is not silently discarded.
    """
    current_audio_level = audio_level(audio_pcm)
    audio_changed = bool(current_audio_level is not None and previous_audio_level is not None
                         and current_audio_level >= 0.02
                         and abs(current_audio_level - previous_audio_level) >= audio_delta_threshold)
    if len(images) < 2:
        return {"changed": True, "change_score": 1.0, "threshold": threshold,
                "change_summary": "影像窗口不足，送第二層確認。",
                "change_reasons": ["insufficient_frames"], "method": "local_pixel_delta_plus_audio",
                "audio_level": current_audio_level, "audio_changed": audio_changed}
    try:
        from PIL import Image, ImageChops, ImageStat

        frames = []
        for image in images:
            with Image.open(BytesIO(image)) as decoded:
                frames.append(decoded.convert("L").resize((96, 54)).copy())
        pair_scores = []
        for first, last in zip(frames, frames[1:]):
            difference = ImageChops.difference(first, last)
            pair_scores.append(float(ImageStat.Stat(difference).mean[0]) / 255.0)
        # Adjacent-frame peak catches transient movement even when the first
        # and last frame happen to show the same background.
        score = max(pair_scores or [0.0])
        changed_pair_count = sum(pair_score >= threshold for pair_score in pair_scores)
        strong_score_threshold = threshold * max(1.0, strong_score_multiplier)
        # Require temporal persistence for ordinary movement. A single very
        # large jump still passes so a sudden person entry/impact is not lost.
        visual_changed = changed_pair_count >= max(1, min_changed_pairs) or score >= strong_score_threshold
        changed = visual_changed or audio_changed
        reasons = []
        if visual_changed:
            reasons.append("temporal_pixel_delta_persistent" if changed_pair_count >= max(1, min_changed_pairs) else "temporal_pixel_delta_strong_jump")
        if audio_changed:
            reasons.append("audio_energy_changed")
        return {
            "changed": changed,
            "change_score": round(score, 5),
            "threshold": threshold,
            "change_summary": "偵測到影像或音訊狀態變化，送第二層觀察。" if changed else "目前影像與音訊沒有超過門檻的變化。",
            "change_reasons": reasons or ["temporal_pixel_delta_below_threshold"],
            "peak_pair_index": pair_scores.index(score) if pair_scores else None,
            "changed_pair_count": changed_pair_count, "min_changed_pairs": min_changed_pairs,
            "strong_score_threshold": round(strong_score_threshold, 5),
            "method": "local_pixel_delta_plus_audio",
            "audio_level": current_audio_level, "audio_changed": audio_changed,
        }
    except Exception as exc:
        return {
            "changed": True,
            "change_score": None,
            "threshold": threshold,
            "change_summary": "快速變化檢查失敗，送第二層確認。",
            "change_reasons": ["change_gate_error", type(exc).__name__],
            "method": "local_pixel_delta_plus_audio_fallback",
            "audio_level": current_audio_level, "audio_changed": audio_changed,
        }
