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
        if bundle and "comprehensive_care_review" in bundle.reason_codes:
            snapshot = bundle.l2_observation
            totals = snapshot.get("period_totals", {})
            falls = int(totals.get("fall_events", 0) or 0)
            hydration = float(totals.get("hydration_ml", 0) or 0)
            days = int(bundle.event_state.get("days", 1) or 1)
            risk = "medium" if falls else "low"
            payload = {
                "summary": (
                    f"已檢視最近 {days} 天的照護資料。"
                    f"期間記錄 {falls} 次跌倒相關事件，飲水共 {hydration:.0f} ml。"
                ),
                "risk_level": risk,
                "confidence": 0.72 if snapshot.get("daily_summaries") else 0.42,
                "recommendations": (["請照護人員複核跌倒事件並確認後續狀況"] if falls else
                                    ["維持目前觀察頻率，並持續記錄飲水與活動"]),
                "positive_signals": ["資料期間內未記錄跌倒事件"] if not falls else [],
                "attention_items": [f"期間內有 {falls} 次跌倒相關事件"] if falls else [],
                "data_limitations": (["每日彙總資料不足，判讀信心有限"]
                                     if not snapshot.get("daily_summaries") else []),
            }
            return MiniMaxResponse(
                text=json.dumps(payload, ensure_ascii=False), latency_ms=self.latency_ms,
                model=self.model, finish_reason="stop", prompt_tokens=520,
                output_tokens=180, total_tokens=700,
            )
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
