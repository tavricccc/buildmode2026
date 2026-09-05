from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import time
import wave
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from .config import Settings
from .schemas import FocusReview, MainAgentJudgment, RecognitionEventCandidate, SceneDescription, VisualDescription, VisionObservation


@dataclass
class AdapterResult:
    status: str
    payload: dict[str, Any]
    error_code: str | None = None
    latency_ms: int = 0


def _http_json(method: str, url: str, *, headers: dict[str, str] | None = None, body: dict | None = None, timeout: float = 10) -> tuple[int, dict]:
    request = urllib.request.Request(url, method=method, headers={"Accept": "application/json", "User-Agent": "Longcare/1.0", **(headers or {})})
    if body is not None:
        request.data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        return response.status, json.loads(data) if data else {}


def _http_frame_json(url: str, image_bytes: bytes, camera_id: str, content_type: str, timeout: float = 10) -> tuple[int, dict]:
    request = urllib.request.Request(url, method="POST", data=image_bytes,
                                     headers={"Accept": "application/json", "Content-Type": content_type, "X-Camera-ID": camera_id})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        return response.status, json.loads(data) if data else {}


class FrigateAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def test(self) -> AdapterResult:
        base = __import__("os").getenv("FRIGATE_BASE_URL", "").rstrip("/")
        if not base:
            return AdapterResult("unavailable", {"configured": False, "mode": "not_configured"}, "FRIGATE_NOT_CONFIGURED")
        started = time.perf_counter()
        try:
            status, payload = await asyncio.to_thread(_http_json, "GET", f"{base}/api/config", timeout=5)
            return AdapterResult("healthy" if status == 200 else "degraded", {"configured": True, "http_status": status, "camera_count": len(payload.get("cameras", {}))}, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return AdapterResult("unavailable", {"configured": True, "error": type(exc).__name__}, "FRIGATE_UNAVAILABLE", int((time.perf_counter() - started) * 1000))

    async def assess_frame(self, image_bytes: bytes, camera_id: str, content_type: str = "image/jpeg") -> AdapterResult:
        """Call an explicitly configured frame bridge.

        Stock Frigate is normally an RTSP/MQTT service, not an arbitrary image
        classification HTTP API. The bridge is therefore opt-in; without it we
        record an ingress-only result and never claim Frigate made a decision.
        """
        endpoint = self.settings.frigate_frame_endpoint
        if not endpoint:
            return AdapterResult("unavailable", {"detections": [], "decision_source": "ingress_only", "message": "Frigate frame bridge is not configured"}, "FRIGATE_FRAME_BRIDGE_NOT_CONFIGURED")
        started = time.perf_counter()
        try:
            status, payload = await asyncio.to_thread(_http_frame_json, endpoint, image_bytes, camera_id, content_type, 10)
            detections = payload.get("detections", [])
            if not isinstance(detections, list) or not all(isinstance(item, dict) for item in detections):
                return AdapterResult("invalid", {"detections": []}, "FRIGATE_INVALID_RESPONSE", int((time.perf_counter() - started) * 1000))
            return AdapterResult("healthy" if status < 300 else "degraded", {"detections": detections, "noteworthy": payload.get("noteworthy"), "decision_source": "frigate_frame_bridge"}, None if status < 300 else "FRIGATE_HTTP_ERROR", int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            return AdapterResult("unavailable", {"detections": [], "decision_source": "frigate_frame_bridge", "error": type(exc).__name__}, "FRIGATE_FRAME_INFERENCE_FAILED", int((time.perf_counter() - started) * 1000))


class VllmVisionAdapter:
    """OpenAI-compatible image adapter for the local Nemotron Omni server."""

    PROMPT_VERSION = "vision-events.nemotron-omni.v1"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def probe(self) -> AdapterResult:
        started = time.perf_counter()
        try:
            headers = {"Authorization": f"Bearer {self.settings.inference_api_key}"} if self.settings.inference_api_key else None
            status, payload = await asyncio.to_thread(_http_json, "GET", f"{self.settings.inference_base_url}/models", headers=headers, timeout=20)
            models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
            found = self.settings.inference_model in models
            return AdapterResult("healthy" if status == 200 and found else "degraded", {"provider": self.settings.inference_provider, "endpoint": self.settings.inference_base_url, "model": self.settings.inference_model, "models": models[:20], "found": found}, None if found else "INFERENCE_MODEL_NOT_FOUND", int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, KeyError) as exc:
            return AdapterResult("unavailable", {"provider": self.settings.inference_provider, "endpoint": self.settings.inference_base_url, "model": self.settings.inference_model, "error": type(exc).__name__}, "INFERENCE_UNAVAILABLE", int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _extract_json(content: Any) -> dict[str, Any]:
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        if not isinstance(content, str):
            raise ValueError("vLLM response content is not text")
        cleaned = content.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("no JSON object in vLLM response")
            parsed = json.loads(cleaned[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("vLLM JSON output is not an object")
        return parsed

    @staticmethod
    def _string_list(value: Any, limit: int = 12) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:240] for item in value if str(item).strip()][:limit]

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalize_observation(cls, raw: dict[str, Any]) -> dict[str, Any]:
        candidate_items = []
        for item in raw.get("event_candidates", []) if isinstance(raw.get("event_candidates", []), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                candidate_items.append(RecognitionEventCandidate.model_validate(item).model_dump())
            except Exception:
                continue
        posture = raw.get("posture") if raw.get("posture") in {"standing", "sitting", "lying", "unknown"} else "unknown"
        transition = raw.get("vertical_transition") if raw.get("vertical_transition") in {"up", "down", "none", "unknown"} else "unknown"
        warning = raw.get("warning_signal") if raw.get("warning_signal") in {"none", "possible", "high"} else "none"
        return {
            "observed_at_offset_ms": int(raw.get("observed_at_offset_ms", 0) or 0),
            "person_visible": bool(raw.get("person_visible", False)), "posture": posture, "vertical_transition": transition,
            "near_floor": bool(raw.get("near_floor", False)), "drink_container": raw.get("drink_container") if raw.get("drink_container") in {"cup", "bottle", "other", "none", "unknown"} else "unknown",
            "container_near_mouth": bool(raw.get("container_near_mouth", False)), "drinking_motion": bool(raw.get("drinking_motion", False)),
            "confidence": cls._number(raw.get("confidence"), .35), "supporting_frame_indexes": [int(x) for x in raw.get("supporting_frame_indexes", []) if isinstance(x, (int, float))][:32],
            "uncertainty_reasons": cls._string_list(raw.get("uncertainty_reasons")), "audio_present": bool(raw.get("audio_present", False)),
            "audio_events": cls._string_list(raw.get("audio_events"), 20), "speaker_emotion": raw.get("speaker_emotion") if raw.get("speaker_emotion") in {"calm", "happy", "sad", "angry", "fearful", "distressed", "neutral", "unknown"} else "unknown",
            "audio_confidence": cls._number(raw.get("audio_confidence"), 0.0) if raw.get("audio_confidence") is not None else None,
            "audio_uncertainty_reasons": cls._string_list(raw.get("audio_uncertainty_reasons"), 20), "speech_detected": bool(raw.get("speech_detected", False)),
            "speech_transcript": str(raw.get("speech_transcript", ""))[:1000], "transcript_confidence": cls._number(raw.get("transcript_confidence"), 0.0) if raw.get("transcript_confidence") is not None else None,
            "transcript_uncertainty_reasons": cls._string_list(raw.get("transcript_uncertainty_reasons"), 20), "change_detected": bool(raw.get("change_detected", False)),
            "change_confidence": cls._number(raw.get("change_confidence"), 0.0), "change_reasons": cls._string_list(raw.get("change_reasons")),
            "change_summary": str(raw.get("change_summary", ""))[:240], "warning_signal": warning, "event_candidates": candidate_items,
        }

    @classmethod
    def _normalize_scene(cls, raw: dict[str, Any]) -> dict[str, Any]:
        return {"location": str(raw.get("location", "unknown"))[:120] or "unknown", "scene_description": str(raw.get("scene_description", "場景描述不可用。"))[:600] or "場景描述不可用。",
                "objects": cls._string_list(raw.get("objects"), 30), "non_person_features": cls._string_list(raw.get("non_person_features"), 20),
                "uncertainty_reasons": cls._string_list(raw.get("uncertainty_reasons")), "confidence": cls._number(raw.get("confidence"), .35),
                "schema_version": "scene-description.v1"}

    @classmethod
    def _normalize_description(cls, raw: dict[str, Any]) -> dict[str, Any]:
        return {"description": str(raw.get("description", "這段窗口未觀察到人物或物品動作。"))[:1200] or "這段窗口未觀察到人物或物品動作。",
                "observed_facts": cls._string_list(raw.get("observed_facts")), "visible_objects": cls._string_list(raw.get("visible_objects"), 20),
                "person_actions": cls._string_list(raw.get("person_actions")), "changes": cls._string_list(raw.get("changes")),
                "warnings": cls._string_list(raw.get("warnings")), "unknowns": cls._string_list(raw.get("unknowns")),
                "confidence": cls._number(raw.get("confidence"), .35), "warning_level": raw.get("warning_level") if raw.get("warning_level") in {"none", "possible", "high"} else "none",
                "schema_version": "visual-description.v1"}

    @classmethod
    def _normalize_focus(cls, raw: dict[str, Any]) -> dict[str, Any]:
        return {"abnormal": bool(raw.get("abnormal", False)), "warning_level": raw.get("warning_level") if raw.get("warning_level") in {"none", "possible", "high"} else "none",
                "comparison_summary": str(raw.get("comparison_summary", "沒有足夠證據確認異常。"))[:800] or "沒有足夠證據確認異常。",
                "description": str(raw.get("description", "沒有足夠證據確認異常。"))[:1200] or "沒有足夠證據確認異常。",
                "supporting_facts": cls._string_list(raw.get("supporting_facts")), "unknowns": cls._string_list(raw.get("unknowns")),
                "evidence_frame_indexes": [int(x) for x in raw.get("evidence_frame_indexes", []) if isinstance(x, (int, float))][:32],
                "confidence": cls._number(raw.get("confidence"), .35), "next_action": str(raw.get("next_action", "繼續觀察。"))[:300] or "繼續觀察。", "schema_version": "focus-review.v1"}

    @classmethod
    def _normalize_main_agent(cls, raw: dict[str, Any]) -> dict[str, Any]:
        phase = raw.get("situation_phase", "unclear")
        phase = {"silent": "no_change", "stable": "ongoing"}.get(phase, phase)
        if phase not in {"no_change", "emerging", "ongoing", "resolved", "unclear"}:
            phase = "unclear"
        risk = raw.get("risk_level", raw.get("risk", "unknown")); risk = {"normal": "normal", "watch": "watch", "elevated": "elevated", "urgent": "urgent"}.get(risk, "unknown")
        attention = raw.get("attention_level", raw.get("attention", "none")); attention = attention if attention in {"none", "low", "medium", "high", "urgent"} else "none"
        action = raw.get("proposed_action", "silent"); action = {"none": "silent", "alert": "dashboard_alert"}.get(action, action)
        if action not in {"silent", "observe", "ask", "remind", "dashboard_alert"}:
            action = "silent"
        unknowns = cls._string_list(raw.get("unknowns")) or cls._string_list(raw.get("unknowns_uncertainty"))
        assessments = []
        for item in raw.get("event_assessments", []) if isinstance(raw.get("event_assessments", []), list) else []:
            if not isinstance(item, dict):
                continue
            assessment = item.get("assessment", "uncertain") if item.get("assessment") in {"supported", "not_supported", "uncertain"} else "uncertain"
            assessments.append({"event_type": str(item.get("event_type", "unknown"))[:80], "assessment": assessment, "confidence": cls._number(item.get("confidence"), .35), "reason": str(item.get("reason", "證據不足。"))[:300] or "證據不足。", "evidence_frame_indexes": [int(x) for x in item.get("evidence_frame_indexes", []) if isinstance(x, (int, float))][:32]})
        segment = raw.get("segment_record") if isinstance(raw.get("segment_record"), dict) else None
        if segment is not None:
            segment = {"summary": str(segment.get("summary", "觀察窗口摘要不可用。"))[:600] or "觀察窗口摘要不可用。", "observed_actions": cls._string_list(segment.get("observed_actions")), "not_observed_actions": cls._string_list(segment.get("not_observed_actions")), "uncertainty": cls._string_list(segment.get("uncertainty"))}
        return {"situation_summary": str(raw.get("situation_summary", raw.get("summary", "目前沒有足夠證據確認值得注意事件。")))[:1000] or "目前沒有足夠證據確認值得注意事件。", "situation_phase": phase,
                "temporal_assessment": str(raw.get("temporal_assessment", "目前沒有足夠的跨窗口證據。"))[:500] or "目前沒有足夠的跨窗口證據。", "observed_facts": cls._string_list(raw.get("observed_facts")),
                "event_assessments": assessments[:12], "hypotheses": cls._string_list(raw.get("hypotheses"), 8), "unknowns": unknowns,
                "uncertainty_reasons": cls._string_list(raw.get("uncertainty_reasons")) or cls._string_list(raw.get("unknowns_uncertainty")), "risk_level": risk, "attention_level": attention,
                "proposed_action": action, "decision_reasons": cls._string_list(raw.get("decision_reasons")) or cls._string_list(raw.get("notes")), "next_action": str(raw.get("next_action", "保持安靜並持續觀察。"))[:300] or "保持安靜並持續觀察。",
                "ask_question": raw.get("ask_question") if isinstance(raw.get("ask_question"), str) else None, "caregiver_summary": raw.get("caregiver_summary") if isinstance(raw.get("caregiver_summary"), str) else None,
                "evidence_frame_indexes": [int(x) for x in raw.get("evidence_frame_indexes", []) if isinstance(x, (int, float))][:32], "confidence": cls._number(raw.get("confidence"), .35),
                "needs_further_attention": bool(raw.get("needs_further_attention", False)), "attention_reason": str(raw.get("attention_reason", ""))[:300], "segment_record": segment,
                "requires_human_review": bool(raw.get("requires_human_review", False)), "schema_version": "main-agent-judgment.v1"}

    @staticmethod
    def _schema() -> dict[str, Any]:
        candidate_schema = {"type": "object", "properties": {
            "event_type": {"type": "string", "enum": ["fall", "hydration", "person_present", "person_walking", "person_sitting", "person_lying", "person_entered", "person_left", "person_inactive", "person_stood_up", "person_sat_down", "person_lay_down", "person_got_up", "doorbell", "door_knock", "door_open", "door_closed", "fridge_open", "fridge_closed", "water_running", "toilet_flush", "washing_machine", "microwave", "rice_cooker", "range_hood", "dishes", "impact_sound", "cough", "tv_audio", "speech_activity", "alarm_sound", "object_cup", "object_bottle", "object_phone", "object_remote", "object_bag", "object_pet", "object_vehicle", "smoke", "fire", "unknown"]},
            "domain": {"type": "string", "enum": ["sound", "person", "object", "scene"]}, "label": {"type": "string"},
            "state": {"type": "string", "enum": ["present", "started", "ended", "active", "unknown"]}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_frame_indexes": {"type": "array", "items": {"type": "integer"}}, "attributes": {"type": "object"},
            "uncertainty_reasons": {"type": "array", "items": {"type": "string"}},
        }, "required": ["event_type", "domain", "label", "state", "confidence", "evidence_frame_indexes", "attributes", "uncertainty_reasons"], "additionalProperties": False}
        return {"type": "object", "properties": {
            "observed_at_offset_ms": {"type": "integer"}, "person_visible": {"type": "boolean"},
            "posture": {"type": "string", "enum": ["standing", "sitting", "lying", "unknown"]},
            "vertical_transition": {"type": "string", "enum": ["up", "down", "none", "unknown"]},
            "near_floor": {"type": "boolean"}, "drink_container": {"type": "string", "enum": ["cup", "bottle", "other", "none", "unknown"]},
            "container_near_mouth": {"type": "boolean"}, "drinking_motion": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "supporting_frame_indexes": {"type": "array", "items": {"type": "integer"}},
            "uncertainty_reasons": {"type": "array", "items": {"type": "string"}},
            "audio_present": {"type": "boolean"}, "audio_events": {"type": "array", "items": {"type": "string"}},
            "speaker_emotion": {"type": "string", "enum": ["calm", "happy", "sad", "angry", "fearful", "distressed", "neutral", "unknown"]},
            "audio_confidence": {"type": "number", "minimum": 0, "maximum": 1}, "audio_uncertainty_reasons": {"type": "array", "items": {"type": "string"}},
            "speech_detected": {"type": "boolean"}, "speech_transcript": {"type": "string", "maxLength": 1000},
            "transcript_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "transcript_uncertainty_reasons": {"type": "array", "items": {"type": "string"}},
            "change_detected": {"type": "boolean"}, "change_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "change_reasons": {"type": "array", "items": {"type": "string"}}, "change_summary": {"type": "string", "maxLength": 240},
            "warning_signal": {"type": "string", "enum": ["none", "possible", "high"]},
            "event_candidates": {"type": "array", "items": candidate_schema},
        }, "required": ["observed_at_offset_ms", "person_visible", "posture", "vertical_transition", "near_floor", "drink_container", "container_near_mouth", "drinking_motion", "confidence", "supporting_frame_indexes", "uncertainty_reasons", "audio_present", "audio_events", "speaker_emotion", "audio_confidence", "audio_uncertainty_reasons", "speech_detected", "speech_transcript", "transcript_confidence", "transcript_uncertainty_reasons", "change_detected", "change_confidence", "change_reasons", "change_summary", "warning_signal", "event_candidates"], "additionalProperties": False}

    @staticmethod
    def _main_agent_schema() -> dict[str, Any]:
        assessment = {
            "type": "object",
            "properties": {
                "event_type": {"type": "string"},
                "assessment": {"type": "string", "enum": ["supported", "not_supported", "uncertain"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string", "maxLength": 180},
                "evidence_frame_indexes": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["event_type", "assessment", "confidence", "reason", "evidence_frame_indexes"],
            "additionalProperties": False,
        }
        segment_record = {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "maxLength": 600},
                "observed_actions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 160}},
                "not_observed_actions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 160}},
                "uncertainty": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            },
            "required": ["summary", "observed_actions", "not_observed_actions", "uncertainty"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "situation_summary": {"type": "string"},
                "situation_phase": {"type": "string", "enum": ["no_change", "emerging", "ongoing", "resolved", "unclear"]},
                "temporal_assessment": {"type": "string", "maxLength": 320},
                "observed_facts": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 240}},
                "event_assessments": {"type": "array", "maxItems": 6, "items": assessment},
                "hypotheses": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
                "unknowns": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 240}},
                "uncertainty_reasons": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 240}},
                "risk_level": {"type": "string", "enum": ["normal", "watch", "elevated", "urgent", "unknown"]},
                "attention_level": {"type": "string", "enum": ["none", "low", "medium", "high", "urgent"]},
                "proposed_action": {"type": "string", "enum": ["silent", "observe", "ask", "remind", "dashboard_alert"]},
                "decision_reasons": {"type": "array", "maxItems": 6, "items": {"type": "string", "maxLength": 180}},
                "next_action": {"type": "string", "maxLength": 300},
                "ask_question": {"type": ["string", "null"]},
                "caregiver_summary": {"type": ["string", "null"]},
                "evidence_frame_indexes": {"type": "array", "maxItems": 12, "items": {"type": "integer"}},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_further_attention": {"type": "boolean"},
                "attention_reason": {"type": "string", "maxLength": 300},
                "segment_record": {"anyOf": [segment_record, {"type": "null"}]},
                "requires_human_review": {"type": "boolean"},
                "schema_version": {"type": "string"},
            },
            "required": ["situation_summary", "situation_phase", "temporal_assessment", "observed_facts", "event_assessments", "hypotheses", "unknowns", "uncertainty_reasons", "risk_level", "attention_level", "proposed_action", "decision_reasons", "next_action", "ask_question", "caregiver_summary", "evidence_frame_indexes", "confidence", "needs_further_attention", "attention_reason", "segment_record", "requires_human_review", "schema_version"],
            "additionalProperties": False,
        }

    async def analyze_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> AdapterResult:
        return await self.analyze_images((image_bytes,), mime_type=mime_type)

    @staticmethod
    def _pcm_to_wav(audio_pcm: bytes, sample_rate: int = 16000) -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(1); wav_file.setsampwidth(2); wav_file.setframerate(sample_rate); wav_file.writeframes(audio_pcm)
        return output.getvalue()

    def _write_transient_audio(self, audio_pcm: bytes) -> tuple[str, str]:
        if self.settings.inference_provider == "gmi_cloud":
            return "", f"data:audio/wav;base64,{base64.b64encode(self._pcm_to_wav(audio_pcm)).decode('ascii')}"
        root = Path(self.settings.media_root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix="vllm-audio-", suffix=".wav", dir=root)
        with os.fdopen(fd, "wb") as output:
            output.write(self._pcm_to_wav(audio_pcm))
        path = Path(filename).resolve()
        # The Nemotron server is WSL-hosted and was started with
        # --allowed-local-media-path /mnt/d, so expose the transient host file
        # using its WSL path rather than a Windows path.
        if path.drive:
            posix_path = path.as_posix()
            wsl_path = f"/mnt/{path.drive[0].lower()}{posix_path[2:]}"
            return filename, f"file://{wsl_path}"
        return filename, path.as_uri()

    async def _structured_chat(self, content: list[dict[str, Any]], *, name: str, schema: dict[str, Any],
                               max_tokens: int, timeout: float = 35, audio_pcm: bytes | None = None,
                               enable_thinking: bool = False) -> AdapterResult:
        started = time.perf_counter()
        request_content = list(content)
        transient_audio = None
        if audio_pcm:
            transient_audio, audio_uri = self._write_transient_audio(audio_pcm)
            request_content.append({"type": "audio_url", "audio_url": {"url": audio_uri}})
        body = {"model": self.settings.inference_model, "messages": [{"role": "user", "content": request_content}],
                "temperature": 0.0, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": enable_thinking},
                "response_format": {"type": "json_object" if self.settings.inference_provider == "gmi_cloud" else "json_schema", **({} if self.settings.inference_provider == "gmi_cloud" else {"json_schema": {"name": name, "strict": True, "schema": schema}})}}
        headers = {"Authorization": f"Bearer {self.settings.inference_api_key}"} if self.settings.inference_api_key else None
        try:
            status, payload = await asyncio.to_thread(_http_json, "POST", f"{self.settings.inference_base_url}/chat/completions", headers=headers, body=body, timeout=timeout)
            choice = payload.get("choices", [{}])[0]
            content_value = choice.get("message", {}).get("content", "")
            if choice.get("finish_reason") == "length":
                return AdapterResult("invalid", {"error": "output_truncated", "finish_reason": "length", "content_tail": str(content_value)[-240:]}, "VLLM_STRUCTURED_OUTPUT_TRUNCATED", int((time.perf_counter() - started) * 1000))
            raw = self._extract_json(content_value)
            if status >= 300:
                return AdapterResult("degraded", {"raw": raw}, "VLLM_STRUCTURED_HTTP_ERROR", int((time.perf_counter() - started) * 1000))
            return AdapterResult("healthy", {"raw": raw}, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_STRUCTURED_OUTPUT_INVALID", int((time.perf_counter() - started) * 1000))
        finally:
            if transient_audio:
                try:
                    os.unlink(transient_audio)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _change_gate_schema() -> dict[str, Any]:
        return {"type": "object", "properties": {
            "changed": {"type": "boolean"},
            "change_score": {"type": "number", "minimum": 0, "maximum": 1},
            "change_summary": {"type": "string", "maxLength": 240},
            "change_reasons": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 100}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }, "required": ["changed", "change_score", "change_summary", "change_reasons", "confidence"], "additionalProperties": False}

    @staticmethod
    def _scene_schema() -> dict[str, Any]:
        return {"type": "object", "properties": {
            "location": {"type": "string", "maxLength": 120}, "scene_description": {"type": "string", "maxLength": 600},
            "objects": {"type": "array", "maxItems": 30, "items": {"type": "string", "maxLength": 100}},
            "non_person_features": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 120}},
            "uncertainty_reasons": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "schema_version": {"type": "string"},
        }, "required": ["location", "scene_description", "objects", "non_person_features", "uncertainty_reasons", "confidence", "schema_version"], "additionalProperties": False}

    @staticmethod
    def _visual_description_schema() -> dict[str, Any]:
        return {"type": "object", "properties": {
            "description": {"type": "string", "maxLength": 1200},
            "observed_facts": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "visible_objects": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 100}},
            "person_actions": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 160}},
            "changes": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 160}},
            "warnings": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "unknowns": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "warning_level": {"type": "string", "enum": ["none", "possible", "high"]},
            "schema_version": {"type": "string"},
        }, "required": ["description", "observed_facts", "visible_objects", "person_actions", "changes", "warnings", "unknowns", "confidence", "warning_level", "schema_version"], "additionalProperties": False}

    @staticmethod
    def _focus_schema() -> dict[str, Any]:
        return {"type": "object", "properties": {
            "abnormal": {"type": "boolean"}, "warning_level": {"type": "string", "enum": ["none", "possible", "high"]},
            "comparison_summary": {"type": "string", "maxLength": 800}, "description": {"type": "string", "maxLength": 1200},
            "supporting_facts": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "unknowns": {"type": "array", "maxItems": 12, "items": {"type": "string", "maxLength": 180}},
            "evidence_frame_indexes": {"type": "array", "maxItems": 32, "items": {"type": "integer"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "next_action": {"type": "string", "maxLength": 300},
            "schema_version": {"type": "string"},
        }, "required": ["abnormal", "warning_level", "comparison_summary", "description", "supporting_facts", "unknowns", "evidence_frame_indexes", "confidence", "next_action", "schema_version"], "additionalProperties": False}

    async def analyze_change_gate(self, images: tuple[bytes, ...] | list[bytes], window: dict[str, Any]) -> AdapterResult:
        """Optional Omni change gate with reasoning explicitly disabled.

        The live pipeline uses the local pixel gate by default because it is
        faster. This method keeps the model-backed gate available for A/B tests
        and proves that Nemotron can toggle thinking per request.
        """
        if len(images) < 2:
            return AdapterResult("invalid", {"error": "change_gate_requires_two_frames"}, "VLLM_CHANGE_GATE_NEEDS_TWO_FRAMES")
        encoded = [base64.b64encode(item).decode("ascii") for item in (images[0], images[-1])]
        content: list[dict[str, Any]] = [{"type": "text", "text": (
            "你是 Longcare 的快速 change gate。只比較最早與最後一張 frame，判斷畫面是否有可見變化。"
            "不要辨識人物、姿勢、物件、聲音或風險，不要思考，不要輸出解釋段落；只輸出 change-gate.v1 JSON。"
            "changed 只能是 true/false；change_summary 只能用一句繁體中文描述『是否需要送下一層』，不要猜測畫面中看不到的內容。window="
            + json.dumps(window, ensure_ascii=False, separators=(",", ":"))
        )}]
        content.extend({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{item}"}} for item in encoded)
        result = await self._structured_chat(content, name="change_gate", schema=self._change_gate_schema(), max_tokens=180, timeout=20, enable_thinking=False)
        if result.status != "healthy":
            return result
        try:
            raw = result.payload["raw"]
            if raw.get("changed") and not raw.get("change_summary"):
                raw["change_summary"] = "偵測到畫面變化，送下一層觀察。"
            return AdapterResult("healthy", {"gate": raw}, None, result.latency_ms)
        except Exception as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_CHANGE_GATE", result.latency_ms)

    async def analyze_scene(self, images: tuple[bytes, ...] | list[bytes], window: dict[str, Any]) -> AdapterResult:
        if not images:
            return AdapterResult("invalid", {"error": "empty_scene_window"}, "VLLM_EMPTY_SCENE_WINDOW")
        encoded = [base64.b64encode(image).decode("ascii") for image in images]
        content: list[dict[str, Any]] = [{"type": "text", "text": (
            "這是 camera session 啟動後前 5 秒的場景 bootstrap。請只描述地點與非人物環境，忽略所有人、人物姿勢與人物行為。"
            "回答 scene-description.v1：location、scene_description、objects、non_person_features、uncertainty_reasons、confidence。"
            "只列出 frame 中可見的固定或非人物物體，不要猜測房間用途以外的細節；只輸出 JSON。window=" + json.dumps(window, ensure_ascii=False, separators=(",", ":"))
        )}]
        content.extend({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{item}"}} for item in encoded)
        result = await self._structured_chat(content, name="scene_description", schema=self._scene_schema(), max_tokens=500)
        if result.status != "healthy":
            return result
        try:
            scene = SceneDescription.model_validate(self._normalize_scene(result.payload["raw"]))
            return AdapterResult("healthy", {"scene": scene.model_dump()}, None, result.latency_ms)
        except Exception as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_SCENE_DESCRIPTION", result.latency_ms)

    async def analyze_visual_description(self, images: tuple[bytes, ...] | list[bytes], window: dict[str, Any],
                                         scene_context: dict[str, Any] | None = None, audio_pcm: bytes | None = None) -> AdapterResult:
        if not images:
            return AdapterResult("invalid", {"error": "empty_description_window"}, "VLLM_EMPTY_DESCRIPTION_WINDOW")
        encoded = [base64.b64encode(image).decode("ascii") for image in images]
        prompt = (
            f"你是 Longcare 的 5fps action description worker。這是連續 2 秒、{len(images)} 張有序 frame；只描述這段時間人物或物品的動作與狀態變化。"
            "不要重複場景 bootstrap 或 scene footnote；不要描述房間、牆面、地板、燈光、固定擺設、空間用途或未參與動作的物件。"
            "description 必須是簡短的繁體中文動作摘要，例如『人物從坐姿站起並向右移動』或『人物拿起杯子靠近嘴邊』。"
            "observed_facts 只能列動作事實；person_actions 只能列人物動作；visible_objects 只能列參與動作或狀態變化的物品；changes 只能列這段窗口新發生的動作／狀態變化。"
            "若沒有觀察到人物或物品動作，description 填『這段窗口未觀察到人物或物品動作。』，其動作與 changes 陣列填空。"
            "不要做最終風險裁決，不要把推測寫成事實；warnings 只保留與觀察到的動作直接相關的注意事項，unknowns 只保留影響動作判讀的未知。"
            "只輸出 visual-description.v1 JSON。window=" + json.dumps(window, ensure_ascii=False, separators=(",", ":"))
        )
        if scene_context:
            prompt += "場景註腳（背景參考，不可取代目前 frame evidence）：" + json.dumps(scene_context, ensure_ascii=False, separators=(",", ":"))
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{item}"}} for item in encoded)
        result = await self._structured_chat(content, name="visual_description", schema=self._visual_description_schema(), max_tokens=700, audio_pcm=audio_pcm)
        if result.status != "healthy":
            return result
        try:
            description = VisualDescription.model_validate(self._normalize_description(result.payload["raw"]))
            return AdapterResult("healthy", {"description": description.model_dump()}, None, result.latency_ms)
        except Exception as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_VISUAL_DESCRIPTION", result.latency_ms)

    async def analyze_focus(self, images: tuple[bytes, ...] | list[bytes], context: dict[str, Any],
                            scene_context: dict[str, Any] | None = None, audio_pcm: bytes | None = None) -> AdapterResult:
        if not images:
            return AdapterResult("invalid", {"error": "empty_focus_window"}, "VLLM_EMPTY_FOCUS_WINDOW")
        encoded = [base64.b64encode(image).decode("ascii") for image in images]
        prompt = (
            f"你是 Longcare focus review worker。這是因為 Main Agent 注意到變化後啟動的 2fps、10 秒、{len(images)} 張連續 frame。"
            "請嚴格對照提供的 5fps descriptions、第一層 observation、事件與其他紀錄，回答 focus-review.v1。"
            "只描述支持 abnormal/warning 的證據、相對上一階段的差異與未知，不做醫療診斷，不宣稱已執行行動；只輸出 JSON。context="
            + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        )
        if scene_context:
            prompt += "場景註腳：" + json.dumps(scene_context, ensure_ascii=False, separators=(",", ":"))
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{item}"}} for item in encoded)
        result = await self._structured_chat(content, name="focus_review", schema=self._focus_schema(), max_tokens=800, audio_pcm=audio_pcm, timeout=45)
        if result.status != "healthy":
            return result
        try:
            focus = FocusReview.model_validate(self._normalize_focus(result.payload["raw"]))
            return AdapterResult("healthy", {"focus": focus.model_dump()}, None, result.latency_ms)
        except Exception as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_FOCUS_REVIEW", result.latency_ms)

    async def analyze_images(self, images: tuple[bytes, ...] | list[bytes], mime_type: str = "image/jpeg", audio_pcm: bytes | None = None,
                             scene_context: dict[str, Any] | None = None, enable_thinking: bool | None = None) -> AdapterResult:
        started = time.perf_counter()
        if not images:
            return AdapterResult("invalid", {"error": "empty_frame_window"}, "VLLM_EMPTY_FRAME_WINDOW")
        frame_count = len(images)
        encoded_images = [base64.b64encode(image).decode("ascii") for image in images]
        prompt = (
            f"你是照護影像事件觀察器。以下是依時間排序的 {frame_count} 張連續攝影機 frame，"
            "請把它們視為同一個事件窗口，並只輸出一個 JSON object，不要 markdown、不要推理文字。"
            "遵守 vision-observation.v1 欄位：observed_at_offset_ms(0), person_visible(boolean), "
            "posture(standing|sitting|lying|unknown), vertical_transition(up|down|none|unknown), near_floor(boolean), "
            "drink_container(cup|bottle|other|none|unknown), container_near_mouth(boolean), drinking_motion(boolean), "
            "confidence(0..1), supporting_frame_indexes(array), uncertainty_reasons(array)。"
            "audio_present(boolean), audio_events(array of concise environment/sound event labels), speaker_emotion(calm|happy|sad|angry|fearful|distressed|neutral|unknown), audio_confidence(0..1), audio_uncertainty_reasons(array)。"
            "若聽到清楚的人聲或 speech_activity，speech_detected=true 並把可辨識內容放入 speech_transcript；沒有清楚語音時 speech_detected=false、speech_transcript=\"\"、transcript_confidence=0。不要猜測聽不清楚的字，transcript_uncertainty_reasons 說明原因。"
            "event_candidates(array)：優先使用 fall/hydration 既有事件欄位；只有家庭聲音、人物活動、非人物物件等例外才新增候選。可用 event_type 包含 doorbell、door_knock、door_open、door_closed、fridge_open、fridge_closed、water_running、toilet_flush、washing_machine、microwave、rice_cooker、range_hood、dishes、impact_sound、cough、tv_audio、speech_activity、alarm_sound、person_present、person_walking、person_sitting、person_lying、person_entered、person_left、person_inactive、object_cup、object_bottle、object_phone、object_remote、object_bag、object_pet、object_vehicle、smoke、fire。只有有證據且 confidence >= 0.55 才列出，否則留在 uncertainty。"
            "若 request 提供 audio_url，audio_present 必須為 true；即使沒有辨識到聲音事件，audio_events 可以是空陣列並在 audio_uncertainty_reasons 說明。"
            "輸出 change_detected(boolean)、change_confidence(0..1)、change_reasons(array) 與 change_summary(string)：只在相對於前一窗口有姿勢、人物、物件、聲音、光線或場景狀態變化時為 true；change_summary 必須用一句繁體中文簡短說明『觀察到的變化內容』，不要只寫『有變化』，沒有變化時填空字串。"
            "輸出 warning_signal(none|possible|high)：只有有潛在危險或需進一步注意的證據才提高，不要把一般人物出現當警示。"
            "這不是單張判讀：只有跨 frame 的變化才支持 vertical_transition；不要僅因單張 lying 確認跌倒。"
        )
        if scene_context:
            prompt += "此 camera session 的場景註腳（只作背景，不可取代目前 frame evidence）：" + json.dumps(scene_context, ensure_ascii=False, separators=(",", ":"))
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}} for encoded in encoded_images)
        transient_audio = None
        if audio_pcm:
            transient_audio, audio_uri = self._write_transient_audio(audio_pcm)
            content.append({"type": "audio_url", "audio_url": {"url": audio_uri}})
        response_format = {"type": "json_object"} if self.settings.inference_provider == "gmi_cloud" else {"type": "json_schema", "json_schema": {"name": "vision_observation", "strict": True, "schema": self._schema()}}
        body = {"model": self.settings.inference_model, "messages": [{"role": "user", "content": content}], "temperature": 0.0, "max_tokens": 512,
                "chat_template_kwargs": {"enable_thinking": self.settings.vllm_observation_enable_thinking if enable_thinking is None else enable_thinking}, "response_format": response_format}
        headers = {"Authorization": f"Bearer {self.settings.inference_api_key}"} if self.settings.inference_api_key else None
        try:
            status, payload = await asyncio.to_thread(_http_json, "POST", f"{self.settings.inference_base_url}/chat/completions", headers=headers, body=body, timeout=60)
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            raw = self._extract_json(content)
            observation = VisionObservation.model_validate(self._normalize_observation(raw))
            if audio_pcm and not observation.audio_present:
                observation = observation.model_copy(update={"audio_present": True, "audio_uncertainty_reasons": [*observation.audio_uncertainty_reasons, "audio track was supplied but the model returned no audio event"]})
            if status >= 300:
                return AdapterResult("degraded", {"observation": observation.model_dump()}, "VLLM_HTTP_ERROR", int((time.perf_counter() - started) * 1000))
            return AdapterResult("healthy", {"observation": observation.model_dump()}, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_OBSERVATION", int((time.perf_counter() - started) * 1000))
        finally:
            if transient_audio:
                try:
                    os.unlink(transient_audio)
                except FileNotFoundError:
                    pass

    async def analyze_main_agent(self, images: tuple[bytes, ...] | list[bytes] | None, context: dict[str, Any],
                                 audio_pcm: bytes | None = None, mime_type: str = "image/jpeg") -> AdapterResult:
        """Run the main local agent on the same bounded evidence window.

        The prompt asks for auditable evidence summaries, not hidden chain of
        thought. The returned proposed action is advisory; MainAgentPolicy is
        the only component that produces the final bounded action proposal.
        """
        started = time.perf_counter()
        context_json = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        prompt = (
            "你是 Longcare Ambient Care 的主 Agent。請分析同一個有限證據窗口，輸出一個 JSON object。"
            "不要輸出 markdown、不要輸出隱藏 chain-of-thought，也不要虛構看不到的資訊；只輸出可稽核的短摘要、證據索引、未知、假設與決策理由。"
            "通常你只收到第一層 observation、5fps visual descriptions、scene footnote、事件與記憶摘要，不會收到原始影片；不要假裝看過不存在的 frame。"
            "先做四步：1) 只列最多 8 項 observed_facts；2) 依 frame 順序說明 temporal_assessment 與 situation_phase；"
            "3) 先把 fall/hydration 對應既有事件，再處理 sound/person/object/scene 例外；"
            "4) 列出 unknowns/uncertainty，再提出 attention、risk 與 proposed_action。"
            "event_assessments 最多 6 項，只評估 current window 中最相關的事件，不要重複列出 recent_events，也不要為每個 domain 產生固定項目。"
            "candidate 不是 confirmed event；模型只能提出 action，不能宣稱已通知、已詢問或已執行。"
            "memory_notes 只是有 provenance 的注意事項，不是新的 evidence 或 fact；不得用它升格目前窗口的未知欄位。"
            "若證據不足，使用 unknown、unclear、silent 或 observe。不要做醫療診斷、疾病預測或目前位置猜測。"
            "evidence_frame_indexes 必須是本次 frame 的 0-based index；沒有直接證據就填空陣列。"
            "若 proposed_action=ask，ask_question 必須是短而可回答的繁體中文問題；否則為 null。"
            "needs_further_attention 只有需要啟動 2 FPS × 10 秒 focus review 時才為 true；沒有警示時必須為 false。"
            "沒有警告且為一般狀態時，segment_record 必須整理這段時間的 summary、observed_actions、not_observed_actions、uncertainty；若無法整理也要填空陣列，不要虛構行動。"
            "回傳 main-agent-judgment.v1 的所有欄位。輸入 context：" + context_json
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if images:
            encoded_images = [base64.b64encode(image).decode("ascii") for image in images]
            content.extend({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}} for encoded in encoded_images)
        transient_audio = None
        if audio_pcm and images:
            transient_audio, audio_uri = self._write_transient_audio(audio_pcm)
            content.append({"type": "audio_url", "audio_url": {"url": audio_uri}})
        body = {
            "model": self.settings.inference_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
            "max_tokens": 1800,
            "chat_template_kwargs": {"enable_thinking": self.settings.vllm_main_agent_enable_thinking},
            "response_format": {"type": "json_object"} if self.settings.inference_provider == "gmi_cloud" else {"type": "json_schema", "json_schema": {"name": "main_agent_judgment", "strict": True, "schema": self._main_agent_schema()}},
        }
        headers = {"Authorization": f"Bearer {self.settings.inference_api_key}"} if self.settings.inference_api_key else None
        try:
            status, payload = await asyncio.to_thread(_http_json, "POST", f"{self.settings.inference_base_url}/chat/completions", headers=headers, body=body, timeout=60)
            choice = payload.get("choices", [{}])[0]
            content_value = choice.get("message", {}).get("content", "")
            if choice.get("finish_reason") == "length":
                return AdapterResult("invalid", {"error": "output_truncated", "finish_reason": "length", "content_tail": str(content_value)[-240:]}, "VLLM_MAIN_AGENT_OUTPUT_TRUNCATED", int((time.perf_counter() - started) * 1000))
            raw = self._extract_json(content_value)
            judgment = MainAgentJudgment.model_validate(self._normalize_main_agent(raw))
            if status >= 300:
                return AdapterResult("degraded", {"judgment": judgment.model_dump()}, "VLLM_MAIN_AGENT_HTTP_ERROR", int((time.perf_counter() - started) * 1000))
            return AdapterResult("healthy", {"judgment": judgment.model_dump()}, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            return AdapterResult("invalid", {"error": type(exc).__name__}, "VLLM_INVALID_MAIN_AGENT_JUDGMENT", int((time.perf_counter() - started) * 1000))
        finally:
            if transient_audio:
                try:
                    os.unlink(transient_audio)
                except FileNotFoundError:
                    pass


class MiniMaxAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        return self.settings.minimax_configured

    async def probe(self) -> AdapterResult:
        if not self.configured():
            return AdapterResult("unavailable", {"configured": False, "mode": "degraded_local_summary"}, "MINIMAX_NOT_CONFIGURED")
        started = time.perf_counter()
        try:
            status, payload = await asyncio.to_thread(_http_json, "GET", f"{self.settings.minimax_base_url}/v1/models",
                                                      headers={"Authorization": f"Bearer {self.settings.minimax_api_key}"}, timeout=8)
            models = [x.get("id") for x in payload.get("data", []) if isinstance(x, dict)]
            found = self.settings.minimax_model in models or not models
            return AdapterResult("healthy" if status == 200 and found else "degraded", {"configured": True, "model": self.settings.minimax_model, "models": models[:20], "found": found}, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return AdapterResult("unavailable", {"configured": True, "model": self.settings.minimax_model, "error": type(exc).__name__}, "MINIMAX_PROBE_FAILED", int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _local_result(summary: dict[str, Any], window: str) -> dict[str, Any]:
        hydration = summary.get("event_summary", {}).get("hydration", {})
        fall = summary.get("event_summary", {}).get("fall", {})
        health = summary.get("health_snapshot", {})
        reasons: list[str] = []
        recommendations: list[str] = []
        risk = "normal"
        if hydration.get("completion_ratio", 0) < 0.5:
            reasons.append("hydration_below_target"); recommendations.append("提醒補充水分並持續觀察"); risk = "watch"
        if health.get("activity") == "inactive" or (health.get("steps") is not None and health.get("steps", 0) < 500):
            reasons.append("low_activity"); recommendations.append("留意活動量與資料覆蓋"); risk = "elevated" if risk == "watch" else "watch"
        if health.get("heart_rate_bpm", 0) > 110 or health.get("spo2_percent", 100) < 92:
            reasons.append("health_value_out_of_demo_range"); recommendations.append("請照護者依專業流程確認健康狀況"); risk = "elevated"
        if fall.get("unresolved", 0):
            reasons.append("unresolved_fall"); recommendations.append("確認長輩是否已恢復並依照護流程處理"); risk = "urgent"
        if not reasons:
            recommendations.append("維持目前觀察")
        return {"summary_zh_tw": "；".join(recommendations) if reasons else "目前資料未顯示需要升級的風險。",
                "risk_level": risk, "reason_codes": reasons,
                "supporting_facts": [{"key": "estimated_hydration_ml", "value": hydration.get("estimated_ml", 0), "window": window}],
                "uncertainties": ["健康數值為 simulated", "飲水量由每次設定容量估算"], "recommendations": recommendations,
                "proposed_actions": ["dashboard_alert"] if risk in {"elevated", "urgent"} else ["dashboard_reminder"],
                "analysis_window": window, "schema_version": "health-risk.v1", "degraded": True}

    async def analyze(self, summary: dict[str, Any], window: str) -> AdapterResult:
        if not self.configured():
            return AdapterResult("degraded", self._local_result(summary, window), "MINIMAX_NOT_CONFIGURED")
        started = time.perf_counter()
        prompt = (
            "Return exactly one JSON object for the health-risk.v1 contract. Do not repeat or echo the input. "
            "Use only these keys: summary_zh_tw (short Traditional Chinese string), risk_level (normal|watch|elevated|urgent|unknown), "
            "reason_codes (string array), recommendations (string array), supporting_facts (array), uncertainties (string array), "
            "proposed_actions (string array), analysis_window (string), schema_version (exactly health-risk.v1), degraded (false). "
            "This is care support, not diagnosis. Input summary:\n" + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        )
        body = {"model": self.settings.minimax_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.0,
                "max_tokens": 512, "chat_template_kwargs": {"enable_thinking": False}, "response_format": {"type": "json_object"}}
        try:
            status, payload = await asyncio.to_thread(_http_json, "POST", f"{self.settings.minimax_base_url}/v1/chat/completions",
                                                       headers={"Authorization": f"Bearer {self.settings.minimax_api_key}"}, body=body, timeout=30)
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = json.loads(content) if isinstance(content, str) else content
            required = {"summary_zh_tw", "risk_level", "reason_codes", "recommendations", "schema_version"}
            if status >= 300 or not required.issubset(result) or result.get("schema_version") != "health-risk.v1":
                return AdapterResult("invalid", {"error": "schema_invalid", "fallback": self._local_result(summary, window)}, "MINIMAX_SCHEMA_INVALID", int((time.perf_counter() - started) * 1000))
            result["degraded"] = False
            return AdapterResult("healthy", result, None, int((time.perf_counter() - started) * 1000))
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError, KeyError, IndexError) as exc:
            return AdapterResult("degraded", self._local_result(summary, window), "MINIMAX_REQUEST_FAILED", int((time.perf_counter() - started) * 1000))


class TelegramAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def configured(self) -> bool:
        return self.settings.telegram_configured

    async def test(self) -> AdapterResult:
        if not self.configured():
            return AdapterResult("unavailable", {"configured": False}, "TELEGRAM_NOT_CONFIGURED")
        try:
            status, payload = await asyncio.to_thread(_http_json, "GET", f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/getMe", timeout=8)
            return AdapterResult("healthy" if status == 200 and payload.get("ok") else "degraded", {"configured": True, "bot_username": payload.get("result", {}).get("username")}, None)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return AdapterResult("unavailable", {"configured": True, "error": type(exc).__name__}, "TELEGRAM_UNAVAILABLE")

    async def send(self, text: str, delivery_id: str, chat_id: str) -> AdapterResult:
        if not self.configured() or chat_id not in self.settings.telegram_allowed_chat_ids:
            return AdapterResult("failed", {}, "TELEGRAM_RECIPIENT_NOT_ALLOWED")
        token = __import__("hashlib").sha256(f"{delivery_id}:{self.settings.telegram_bot_token}".encode()).hexdigest()[:24]
        body = {"chat_id": chat_id, "text": text, "reply_markup": {"inline_keyboard": [[
            {"text": "已收到", "callback_data": f"ack:{token}"}, {"text": "誤報", "callback_data": f"false:{token}"}
        ]]}}
        try:
            status, payload = await asyncio.to_thread(_http_json, "POST", f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage", body=body, timeout=10)
            if status >= 300 or not payload.get("ok"):
                return AdapterResult("failed", {}, "TELEGRAM_SEND_FAILED")
            return AdapterResult("sent", {"provider_message_id": str(payload.get("result", {}).get("message_id", ""))})
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return AdapterResult("failed", {}, "TELEGRAM_SEND_FAILED")
