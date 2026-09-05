"""Deterministic fixture responses for the stub server."""

from __future__ import annotations

import time
from typing import Any


def _now() -> int:
    return int(time.time())


def vision_fixture(model_id: str, *, person_visible: bool = True) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-stub-{_now()}",
        "object": "chat.completion",
        "created": _now(),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "{"
                        "\"observed_at_offset_ms\":0,"
                        "\"person_visible\":true,"
                        "\"posture\":\"standing\","
                        "\"vertical_transition\":\"none\","
                        "\"near_floor\":false,"
                        "\"drink_container\":\"none\","
                        "\"container_near_mouth\":false,"
                        "\"drinking_motion\":false,"
                        "\"confidence\":0.62,"
                        "\"supporting_frame_indexes\":[0],"
                        "\"uncertainty_reasons\":[\"synthetic_stub\"]"
                        "}"
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 16, "completion_tokens": 32, "total_tokens": 48},
    }


def analysis_fixture(model_id: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-stub-analysis-{_now()}",
        "object": "chat.completion",
        "created": _now(),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "{"
                        "\"schema_version\":\"health-risk.v1\","
                        "\"summary_zh\":\"合成資料：無顯著變化。\","
                        "\"risk_level\":\"low\","
                        "\"reason_codes\":[\"synthetic_stub\"],"
                        "\"supporting_facts\":[],"
                        "\"uncertainties\":[\"synthetic_stub\"],"
                        "\"recommendations\":[],"
                        "\"proposed_actions\":[],"
                        "\"analysis_window\":{\"start\":\"now\",\"end\":\"now\"},"
                        "\"confidence\":0.5"
                        "}"
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 16, "completion_tokens": 16, "total_tokens": 32},
    }


def speech_fixture(model_id: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-stub-speech-{_now()}",
        "object": "chat.completion",
        "created": _now(),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "probe"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 4, "total_tokens": 8},
    }


def transcription_fixture() -> dict[str, Any]:
    return {"text": "probe", "language": "en"}
