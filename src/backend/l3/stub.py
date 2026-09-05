"""Offline L3 stand-in (docs/04_SETUP_DEPLOY_VERIFY.md gate 1).

Mirrors :mod:`backend.l2.stub`: it reproduces the MiniMax *contract* so
the escalation path, the degraded text-only path, the audit row and the
Policy Gateway are all exercised without a key or a network.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..domain.l3_contract import EvidenceBundle
from .minimax_client import MiniMaxResponse


class StubL3Backend:
    def __init__(self, model: str = "stub-l3", latency_ms: int = 5, fail_with: Any = None) -> None:
        self.model = model
        self.latency_ms = latency_ms
        self.fail_with = fail_with
        self.calls = 0
        self.last_frame_count = 0
        self._bundle: EvidenceBundle | None = None

    @staticmethod
    def text_part(text: str) -> dict[str, Any]:
        return {"type": "text", "text": text}

    def video_parts(self, frames: list[bytes], clip_url: str | None = None) -> list[dict[str, Any]]:
        self.last_frame_count = len(frames)
        return [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"}} for _ in frames]

    def set_bundle(self, bundle: EvidenceBundle) -> None:
        self._bundle = bundle

    def analyse(self, parts: list[dict[str, Any]], *, system_instruction: str | None = None,
                json_output: bool = True, temperature: float = 0.0, max_tokens: int = 900,
                model: str | None = None) -> MiniMaxResponse:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        time.sleep(self.latency_ms / 1000.0)

        bundle = self._bundle
        reasons = bundle.reason_codes if bundle else []
        saw_video = bool(bundle and not bundle.degraded_text_only)
        motionless = bool(
            bundle and (bundle.l2_observation.get("fall") or {}).get("motionless")
        )

        if "person_motionless_on_floor" in reasons:
            risk, rec = ("critical" if saw_video else "high"), "suggest_caregiver_notification"
            text = "Person is on the floor and not moving across the whole clip."
        elif "possible_fall" in reasons:
            risk, rec = "high" if motionless else "medium", "raise_dashboard_alert"
            text = "Posture is consistent with a fall; no clear attempt to get up yet."
        else:
            risk, rec = "low", "keep_observing"
            text = "Nothing in the clip changes what a caregiver should do."

        payload = {
            "interpretation": text + ("" if saw_video else " (no footage was attached)"),
            "risk_level": risk,
            "confidence": 0.82 if saw_video else 0.4,
            "supports_l2": True,
            "contradicts_l2_reason": "",
            "uncertainty": [] if saw_video else ["no footage attached"],
            "recommendation": rec,
            "recommended_followup_sec": 30 if risk in {"high", "critical"} else 0,
        }
        return MiniMaxResponse(
            text=json.dumps(payload),
            latency_ms=self.latency_ms,
            model=self.model,
            finish_reason="stop",
            prompt_tokens=400,
            output_tokens=120,
            total_tokens=520,
        )
