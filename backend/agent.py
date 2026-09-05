from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings
from .schemas import MainAgentJudgment, VisionObservation


MEMORABLE_EVENT_TYPES = frozenset({
    "fall", "hydration", "person_entered", "person_left", "person_inactive", "person_stood_up", "person_sat_down", "person_lay_down", "person_got_up",
    "doorbell", "door_knock", "door_open", "fridge_open", "water_running", "toilet_flush",
    "impact_sound", "cough", "alarm_sound", "speech_activity", "object_bag", "object_pet",
    "object_vehicle", "smoke", "fire",
})


def evaluate_change_gate(previous: VisionObservation | None, current: VisionObservation,
                         persisted: dict[str, Any], previous_event_keys: set[str] | None = None) -> dict[str, Any]:
    """Combine model change output with deterministic, memorable-event edges."""
    previous_event_keys = previous_event_keys or set()
    reasons: list[str] = []
    noteworthy_events: list[str] = []
    current_event_keys: set[str] = set()

    if current.change_detected and not (previous and previous.change_detected):
        reasons.extend(current.change_reasons or ["model_change_detected"])
    if current.warning_signal != "none" and (not previous or previous.warning_signal != current.warning_signal):
        reasons.append(f"warning_signal:{current.warning_signal}")

    if current.person_visible and (previous is None or not previous.person_visible):
        reasons.append("person_appeared")
        noteworthy_events.append("person_appeared")
    elif previous and previous.person_visible and not current.person_visible:
        reasons.append("person_left_camera_view")
        noteworthy_events.append("person_left_camera_view")

    previous_audio = set(previous.audio_events if previous else [])
    for audio_event in set(current.audio_events) - previous_audio:
        normalized = audio_event.strip().lower().replace(" ", "_")
        if normalized in MEMORABLE_EVENT_TYPES:
            current_event_keys.add(f"audio:{normalized}")
            if f"audio:{normalized}" not in previous_event_keys:
                reasons.append(f"new_audio_event:{normalized}")
                noteworthy_events.append(normalized)

    previous_candidates = {
        f"{item.event_type}:{item.label.strip().lower()}:{item.state}" for item in (previous.event_candidates if previous else [])
        if item.event_type in MEMORABLE_EVENT_TYPES and item.confidence >= 0.55
    }
    current_candidates = {
        f"candidate:{item.event_type}:{item.label.strip().lower()}:{item.state}" for item in current.event_candidates
        if item.event_type in MEMORABLE_EVENT_TYPES and item.confidence >= 0.55
    }
    current_event_keys.update(current_candidates)
    for event_key in current_candidates:
        if event_key not in previous_event_keys and event_key not in previous_candidates:
            event_type = event_key.split(":", 2)[1]
            reasons.append(f"new_memorable_event:{event_type}")
            noteworthy_events.append(event_type)

    for event in [*persisted.get("events", []), *persisted.get("recognition_events", [])]:
        event_type = str(event.get("event_type", ""))
        if event_type not in MEMORABLE_EVENT_TYPES:
            continue
        event_key = f"persisted:{event_type}:{event.get('id')}:{event.get('status', 'observed')}"
        current_event_keys.add(event_key)
        if event_key not in previous_event_keys:
            reasons.append(f"new_persisted_event:{event_type}")
            noteworthy_events.append(event_type)

    unique_reasons = list(dict.fromkeys(reasons))[:12]
    return {
        "trigger": bool(unique_reasons),
        "reasons": unique_reasons,
        "noteworthy_events": list(dict.fromkeys(noteworthy_events))[:12],
        "event_keys": current_event_keys,
        "change_confidence": max(float(current.change_confidence), 0.80 if unique_reasons else 0.0),
    }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class MainAgentPolicy:
    """Convert a model judgment into a bounded, explainable action proposal.

    The local model may describe a situation and propose an action, but it does
    not own the final decision. This policy is intentionally deterministic so a
    reviewer can reproduce why a window became silent, observable, ask-worthy,
    or alert-worthy.
    """

    VERSION = "main-agent-policy.v1"

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(self, judgment: MainAgentJudgment, observation: VisionObservation,
                 persisted: dict[str, Any], window: dict[str, Any],
                 now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        events = list(persisted.get("events") or [])
        recognition_events = list(persisted.get("recognition_events") or [])
        evidence_indexes = set(observation.supporting_frame_indexes)
        evidence_indexes.update(judgment.evidence_frame_indexes)
        for candidate in observation.event_candidates:
            evidence_indexes.update(candidate.evidence_frame_indexes)

        model_confidence = float(judgment.confidence)
        visual_confidence = float(observation.confidence)
        event_confidence = max(
            [float(item.get("confidence", 0)) for item in [*events, *recognition_events] if item.get("confidence") is not None]
            or [0.0]
        )
        event_weights = {
            "fall": 0.95, "fire": 1.0, "smoke": 0.95, "alarm_sound": 0.90, "impact_sound": 0.80,
            "person_inactive": 0.55, "cough": 0.45, "doorbell": 0.40, "door_knock": 0.40,
            "person_left": 0.35, "person_entered": 0.30, "fridge_open": 0.20, "fridge_closed": 0.15,
            "hydration": 0.15, "person_present": 0.15, "person_walking": 0.15, "person_sitting": 0.10,
        }
        event_signal = max(
            [float(item.get("confidence", 0)) * event_weights.get(str(item.get("event_type")), 0.20)
             for item in [*events, *recognition_events] if item.get("confidence") is not None]
            or [0.0]
        )
        uncertainty_penalty = min(30, len(judgment.unknowns) * 4 + len(judgment.uncertainty_reasons) * 3)
        # Confidence says how reliable a signal is; it must not make a normal
        # observation noteworthy by itself. Attention is therefore driven by
        # event signal first, with confidence acting as a reliability weight.
        base_score = round((model_confidence * 15) + (visual_confidence * 10) + (event_signal * 75))
        attention_score = max(0, min(100, base_score - uncertainty_penalty))

        confidence_gate = model_confidence >= self.settings.main_agent_min_confidence
        evidence_gate = bool(evidence_indexes or observation.audio_present or window.get("frame_count"))
        critical_fall_due = False
        confirmed_fall = False
        for event in events:
            if event.get("event_type") != "fall":
                continue
            if event.get("status") in {"confirmed", "recovering"}:
                confirmed_fall = True
            attrs = event.get("attributes") or event.get("attributes_json") or {}
            if isinstance(attrs, str):
                try:
                    import json
                    attrs = json.loads(attrs)
                except json.JSONDecodeError:
                    attrs = {}
            due = _parse_time(attrs.get("alert_due_at")) if isinstance(attrs, dict) else None
            if event.get("status") in {"confirmed", "recovering"} and due and due <= now:
                critical_fall_due = True

        critical_recognition = [
            item for item in recognition_events
            if item.get("event_type") in {"fire", "smoke", "alarm_sound"}
            and float(item.get("confidence", 0)) >= 0.75
        ]
        distressed_audio = observation.audio_present and observation.speaker_emotion == "distressed" and float(observation.audio_confidence or 0) >= 0.70

        reasons: list[str] = []
        if confidence_gate:
            reasons.append(f"model confidence {model_confidence:.2f} meets minimum {self.settings.main_agent_min_confidence:.2f}")
        else:
            reasons.append(f"model confidence {model_confidence:.2f} is below minimum {self.settings.main_agent_min_confidence:.2f}")
        if evidence_gate:
            reasons.append(f"evidence gate passed: {len(evidence_indexes)} frame refs, audio_present={observation.audio_present}")
        else:
            reasons.append("no usable visual or audio evidence")
        if judgment.unknowns:
            reasons.append(f"uncertainty penalty applied for {len(judgment.unknowns)} unknowns")
        if confirmed_fall:
            reasons.append("existing fall state machine has a confirmed or recovering event")
        if critical_fall_due:
            reasons.append("fall recovery deadline has elapsed")
        if critical_recognition:
            reasons.append("fire/smoke/alarm recognition crossed the critical confidence gate")
        if distressed_audio:
            reasons.append("distressed audio emotion crossed the ask-resident confidence gate")

        gates = {
            "observation_valid": True,
            "confidence": confidence_gate,
            "evidence": evidence_gate,
            "existing_first": True,
            "raw_model_action_is_not_authority": True,
            "critical_override": critical_fall_due or bool(critical_recognition),
        }
        if not confidence_gate or not evidence_gate:
            final_action = "silent"
            decision = "insufficient_data"
            attention_level = "none"
            risk_level = "unknown"
        elif critical_fall_due or critical_recognition:
            final_action = "dashboard_alert"
            decision = "alert"
            attention_level = "urgent"
            risk_level = "urgent"
            attention_score = max(attention_score, 95)
        elif distressed_audio and judgment.ask_question:
            final_action = "ask"
            decision = "ask"
            attention_level = "high"
            risk_level = "elevated" if judgment.risk_level == "unknown" else judgment.risk_level
            attention_score = max(attention_score, 75)
        elif judgment.proposed_action == "ask" and model_confidence >= 0.70 and judgment.ask_question and (judgment.needs_further_attention or observation.warning_signal != "none"):
            final_action = "ask"
            decision = "ask"
            attention_level = "medium"
            risk_level = judgment.risk_level
        elif judgment.proposed_action == "remind" and model_confidence >= 0.70:
            final_action = "remind"
            decision = "observe"
            attention_level = "medium"
            risk_level = judgment.risk_level
        elif confirmed_fall:
            final_action = "observe"
            decision = "observe"
            attention_level = "high"
            risk_level = "elevated" if judgment.risk_level == "unknown" else judgment.risk_level
            attention_score = max(attention_score, 70)
        elif attention_score >= 55 or judgment.attention_level in {"medium", "high", "urgent"}:
            final_action = "observe"
            decision = "observe"
            attention_level = "medium" if attention_score < 75 else "high"
            risk_level = judgment.risk_level
        else:
            final_action = "silent"
            decision = "silent"
            attention_level = "none" if attention_score < 30 else "low"
            risk_level = judgment.risk_level

        return {
            "policy_version": self.VERSION,
            "final_action": final_action,
            "decision": decision,
            "attention_level": attention_level,
            "risk_level": risk_level,
            "attention_score": attention_score,
            "score_components": {
                "model_confidence": round(model_confidence, 4),
                "visual_confidence": round(visual_confidence, 4),
                "event_confidence": round(event_confidence, 4),
                "event_signal": round(event_signal, 4),
                "uncertainty_penalty": uncertainty_penalty,
                "critical_bonus": 100 - base_score if critical_fall_due or critical_recognition else 0,
            },
            "gates": gates,
            "reasons": reasons[:12],
            "evidence_frame_indexes": sorted(evidence_indexes),
            "action_allowed": final_action != "silent",
            "action_executed": False,
            "window_id": window.get("window_id"),
        }


def build_main_agent_context(observation: VisionObservation, persisted: dict[str, Any],
                             window: dict[str, Any], recent_events: list[dict[str, Any]],
                             memory_notes: list[dict[str, Any]] | None = None,
                             visual_descriptions: list[dict[str, Any]] | None = None,
                             scene_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a bounded context package; never include raw media or unrestricted SQL."""
    def compact_event(item: dict[str, Any]) -> dict[str, Any]:
        attrs = item.get("attributes") or item.get("attributes_json") or {}
        if isinstance(attrs, str):
            attrs = {}
        compact_attrs = {key: attrs[key] for key in ("alert_due_at", "session_status", "container", "run_id") if key in attrs}
        result = {key: item[key] for key in ("id", "event_type", "domain", "label", "status", "occurred_at", "confidence", "source", "window_id", "source_offset_ms") if key in item}
        if compact_attrs:
            result["attributes"] = compact_attrs
        return result

    def compact_description(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in ("id", "description_type", "window_id", "start_offset_ms", "end_offset_ms", "description_text", "facts_json", "objects_json", "actions_json", "changes_json", "warnings_json", "unknowns_json", "confidence", "warning_level") if key in item}

    return {
        "window": window,
        "observation": observation.model_dump(),
        "canonical_events": [compact_event(item) for item in persisted.get("events", [])[:4]],
        "recognition_events": [compact_event(item) for item in persisted.get("recognition_events", [])[:6]],
        "recent_events": [compact_event(item) for item in recent_events[:8]],
        "visual_descriptions": [compact_description(item) for item in (visual_descriptions or [])[:8]],
        "scene_context": scene_context or {"location": "unknown", "scene_description": "not initialized"},
        "memory_notes": [note for note in (memory_notes or []) if note.get("layer") in {"decision", "abstraction"}][:20],
        "contract": {
            "existing_first": ["fall", "hydration"],
            "exception_domains": ["sound", "person", "object", "scene"],
            "candidate_is_not_confirmed": True,
            "unknown_is_valid": True,
            "raw_media_policy": "local_window_only",
        },
    }


def build_main_agent_notes(judgment: MainAgentJudgment, policy: dict[str, Any],
                           window: dict[str, Any], agent_run_id: str) -> list[dict[str, Any]]:
    """Build bounded short/abstract notes without storing raw media.

    Ordinary clear windows stay only in agent_runs. Notes are created when the
    round contains an event, uncertainty, hypothesis, or non-silent proposal.
    """
    material_event = any(item.assessment == "supported" for item in judgment.event_assessments)
    if policy.get("final_action") == "silent" and not judgment.unknowns and not judgment.hypotheses and not material_event:
        return []
    now = datetime.now(timezone.utc)
    source_window_id = window.get("window_id")
    notes = [{
        "layer": "decision",
        "note_type": "attention_decision",
        "title": f"Main Agent decision · {policy.get('final_action', 'silent')}",
        "content": {
            "situation_summary": judgment.situation_summary,
            "attention_level": policy.get("attention_level"),
            "risk_level": policy.get("risk_level"),
            "attention_score": policy.get("attention_score", 0),
            "final_action": policy.get("final_action", "silent"),
            "reasons": policy.get("reasons", [])[:8],
            "next_action": judgment.next_action,
            "unknowns": judgment.unknowns[:8],
            "window_id": source_window_id,
        },
        "source_agent": "main_agent", "source_run_id": agent_run_id, "source_window_id": source_window_id,
        "status": "active", "confidence": judgment.confidence, "importance": policy.get("attention_score", 0) / 100,
        "privacy_level": "local", "requires_review": policy.get("final_action") in {"ask", "dashboard_alert"},
        "expires_at": (now + timedelta(hours=24)).isoformat(),
        "target_layers": ["decision"], "dedup_key": f"{agent_run_id}:decision",
    }]
    notes.append({
        "layer": "abstraction",
        "note_type": "situation_summary",
        "title": "Main Agent abstract context",
        "content": {
            "situation_summary": judgment.situation_summary,
            "situation_phase": judgment.situation_phase,
            "temporal_assessment": judgment.temporal_assessment,
            "observed_facts": judgment.observed_facts[:8],
            "event_assessments": [item.model_dump() for item in judgment.event_assessments[:8]],
            "hypotheses": judgment.hypotheses[:6],
            "unknowns": judgment.unknowns[:8],
            "uncertainty_reasons": judgment.uncertainty_reasons[:8],
            "window_id": source_window_id,
        },
        "source_agent": "main_agent", "source_run_id": agent_run_id, "source_window_id": source_window_id,
        "status": "active", "confidence": judgment.confidence, "importance": max(0.35, policy.get("attention_score", 0) / 100),
        "privacy_level": "local", "requires_review": bool(judgment.hypotheses),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "target_layers": ["decision", "research"], "dedup_key": f"{agent_run_id}:abstraction",
    })
    return notes
