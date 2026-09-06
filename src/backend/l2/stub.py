"""Offline L2 stand-in (docs/04_SETUP_DEPLOY_VERIFY.md gate 1).

Gate 1 is "replay -> L1 stub -> Gemini stub -> event -> SQLite ->
Dashboard", and it has to pass on a machine with no API key and no
network. This backend derives an observation from the replay annotation
that :class:`ScriptedSource` attached to the frames.

It is deliberately not a simulator of Gemini's *quality* — it does not
add noise or hedge. It reproduces Gemini's *contract*, so that everything
downstream (schema validation, the repair path, the state machines, the
escalation decision, the audit row) is exercised for real.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..domain.observation import GeminiObservation
from .gemini_client import GeminiResponse


class StubL2Backend:
    """Satisfies the ``L2Backend`` protocol without leaving the process."""

    def __init__(self, model: str = "stub-l2", latency_ms: int = 5, fail_with: Any = None,
                 malformed: bool = False) -> None:
        self.model = model
        self.latency_ms = latency_ms
        #: set to a GeminiError to exercise the failure paths
        self.fail_with = fail_with
        #: emit prose-wrapped, contract-violating output to exercise repair
        self.malformed = malformed
        self.calls = 0
        self._last_annotation: dict[str, Any] | None = None

    # -- L2Backend protocol ----------------------------------------------

    @staticmethod
    def text_part(text: str) -> dict[str, Any]:
        return {"text": text}

    def media_part(self, path: str | Path, mime_type: str,
                   cleanup: list[Any] | None = None) -> dict[str, Any]:
        # The stub is handed the annotation through the clip, not the file.
        return {"inline_data": {"mime_type": mime_type, "data": ""}}

    def set_annotation(self, annotation: dict[str, Any] | None) -> None:
        self._last_annotation = annotation or {}

    def generate(self, parts: list[dict[str, Any]], *, system_instruction: str | None = None,
                 json_output: bool = True, temperature: float = 0.0,
                 max_output_tokens: int = 1024, model: str | None = None) -> GeminiResponse:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        time.sleep(self.latency_ms / 1000.0)

        is_repair = any("did not satisfy the required JSON contract" in p.get("text", "")
                        for p in parts if "text" in p)
        if self.malformed and not is_repair:
            # A realistic first-attempt failure: fenced prose plus a value
            # outside the declared range.
            return self._response('Sure! Here is what I saw:\n```json\n{"person_visible": true, '
                                  '"confidence": 1.7}\n```')

        return self._response(json.dumps(self._observation()))

    # -- fixture logic ---------------------------------------------------

    def _observation(self) -> dict[str, Any]:
        a = self._last_annotation or {}
        person = bool(a.get("person", False))
        posture = str(a.get("posture", "unknown" if person else "unknown"))
        near_floor = bool(a.get("near_floor", posture == "lying"))
        motionless = bool(a.get("motionless", False))
        drinking = bool(a.get("drinking", False))
        container = str(a.get("container", "cup" if drinking else "none"))
        confidence = float(a.get("confidence", 0.9 if person else 0.8))

        fall_like = person and posture == "lying" and near_floor
        reasons: list[str] = []
        if fall_like:
            reasons.append("possible_fall")
        if fall_like and motionless:
            reasons.append("person_motionless_on_floor")
        if a.get("occluded"):
            reasons.append("occluded_view")

        payload = GeminiObservation.parse(
            {
                "person_visible": person,
                "person_count": 1 if person else 0,
                "scene_summary": str(a.get("summary", "")) or ("person in frame" if person else "empty room"),
                "confidence": confidence,
                "uncertainty_reasons": ["occluded_view"] if a.get("occluded") else [],
                "fall": {
                    "posture": posture if posture in {"standing", "sitting", "lying", "crouching"} else "unknown",
                    "vertical_transition": str(a.get("transition", "unknown")),
                    "near_floor": near_floor,
                    "motionless": motionless,
                    "confidence": confidence,
                },
                "hydration": {
                    "container": container,
                    "container_near_mouth": bool(a.get("container_near_mouth", drinking)),
                    "drinking_motion": drinking,
                    "confidence": confidence,
                },
                "escalation": {
                    "required": bool(a.get("escalate", fall_like)),
                    "reason_codes": reasons,
                    "requested_evidence_window_sec": 10,
                },
            }
        )
        return payload.to_dict()

    def _response(self, text: str) -> GeminiResponse:
        return GeminiResponse(
            text=text,
            latency_ms=self.latency_ms,
            model=self.model,
            finish_reason="STOP",
            prompt_tokens=100,
            candidate_tokens=80,
            total_tokens=180,
        )
