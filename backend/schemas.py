from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EventType = Literal["fall", "hydration"]
EventStatus = Literal["candidate", "confirmed", "recovering", "resolved", "dismissed", "invalid"]
RiskLevel = Literal["normal", "watch", "elevated", "urgent", "unknown"]
AttentionLevel = Literal["none", "low", "medium", "high", "urgent"]
AgentAction = Literal["silent", "observe", "ask", "remind", "dashboard_alert"]
AgentDecision = Literal["silent", "observe", "ask", "alert", "insufficient_data"]
WarningLevel = Literal["none", "possible", "high"]
RecognitionDomain = Literal["sound", "person", "object", "scene"]
RecognitionEventType = Literal[
    "fall", "hydration", "person_present", "person_walking", "person_sitting", "person_lying", "person_entered", "person_left", "person_inactive", "person_stood_up", "person_sat_down", "person_lay_down", "person_got_up",
    "doorbell", "door_knock", "door_open", "door_closed", "fridge_open", "fridge_closed", "water_running", "toilet_flush", "washing_machine",
    "microwave", "rice_cooker", "range_hood", "dishes", "impact_sound", "cough", "tv_audio", "speech_activity", "alarm_sound",
    "object_cup", "object_bottle", "object_phone", "object_remote", "object_bag", "object_pet", "object_vehicle", "smoke", "fire", "unknown"
]


class RecognitionEventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: RecognitionEventType
    domain: RecognitionDomain
    label: str = Field(min_length=1, max_length=100)
    state: Literal["present", "started", "ended", "active", "unknown"] = "unknown"
    confidence: float = Field(ge=0, le=1)
    evidence_frame_indexes: list[int] = Field(default_factory=list, max_length=32)
    attributes: dict[str, Any] = Field(default_factory=dict)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=10)


class VisionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at_offset_ms: int = Field(ge=0)
    person_visible: bool
    posture: Literal["standing", "sitting", "lying", "unknown"] = "unknown"
    vertical_transition: Literal["up", "down", "none", "unknown"] = "unknown"
    near_floor: bool = False
    drink_container: Literal["cup", "bottle", "other", "none", "unknown"] = "unknown"
    container_near_mouth: bool = False
    drinking_motion: bool = False
    confidence: float = Field(ge=0, le=1)
    supporting_frame_indexes: list[int] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    audio_present: bool = False
    audio_events: list[str] = Field(default_factory=list, max_length=20)
    speaker_emotion: Literal["calm", "happy", "sad", "angry", "fearful", "distressed", "neutral", "unknown"] = "unknown"
    audio_confidence: float | None = Field(default=None, ge=0, le=1)
    audio_uncertainty_reasons: list[str] = Field(default_factory=list, max_length=20)
    speech_detected: bool = False
    speech_transcript: str = Field(default="", max_length=1000)
    transcript_confidence: float | None = Field(default=None, ge=0, le=1)
    transcript_uncertainty_reasons: list[str] = Field(default_factory=list, max_length=20)
    change_detected: bool = False
    change_confidence: float = Field(default=0.0, ge=0, le=1)
    change_reasons: list[str] = Field(default_factory=list, max_length=12)
    change_summary: str = Field(default="", max_length=240)
    warning_signal: WarningLevel = "none"
    event_candidates: list[RecognitionEventCandidate] = Field(default_factory=list, max_length=12)


class SceneDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = Field(default="unknown", max_length=120)
    scene_description: str = Field(min_length=1, max_length=600)
    objects: list[str] = Field(default_factory=list, max_length=30)
    non_person_features: list[str] = Field(default_factory=list, max_length=20)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0, le=1)
    schema_version: str = "scene-description.v1"


class VisualDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1200)
    observed_facts: list[str] = Field(default_factory=list, max_length=12)
    visible_objects: list[str] = Field(default_factory=list, max_length=20)
    person_actions: list[str] = Field(default_factory=list, max_length=12)
    changes: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0, le=1)
    warning_level: WarningLevel = "none"
    schema_version: str = "visual-description.v1"


class FocusReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abnormal: bool
    warning_level: WarningLevel
    comparison_summary: str = Field(min_length=1, max_length=800)
    description: str = Field(min_length=1, max_length=1200)
    supporting_facts: list[str] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    evidence_frame_indexes: list[int] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0, le=1)
    next_action: str = Field(min_length=1, max_length=300)
    schema_version: str = "focus-review.v1"


class MainAgentSegmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    observed_actions: list[str] = Field(default_factory=list, max_length=12)
    not_observed_actions: list[str] = Field(default_factory=list, max_length=12)
    uncertainty: list[str] = Field(default_factory=list, max_length=12)


class MainAgentEventAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=80)
    assessment: Literal["supported", "not_supported", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)
    evidence_frame_indexes: list[int] = Field(default_factory=list, max_length=32)


class MainAgentJudgment(BaseModel):
    """Auditable, bounded analysis emitted by the main local agent.

    This is deliberately a summary of observable evidence and decision factors,
    not hidden chain-of-thought. The deterministic policy layer still owns the
    final action.
    """

    model_config = ConfigDict(extra="forbid")

    situation_summary: str = Field(min_length=1, max_length=1000)
    situation_phase: Literal["no_change", "emerging", "ongoing", "resolved", "unclear"]
    temporal_assessment: str = Field(min_length=1, max_length=500)
    observed_facts: list[str] = Field(default_factory=list, max_length=12)
    event_assessments: list[MainAgentEventAssessment] = Field(default_factory=list, max_length=12)
    hypotheses: list[str] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=12)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=12)
    risk_level: RiskLevel
    attention_level: AttentionLevel
    proposed_action: AgentAction
    decision_reasons: list[str] = Field(default_factory=list, max_length=12)
    next_action: str = Field(min_length=1, max_length=300)
    ask_question: str | None = Field(default=None, max_length=300)
    caregiver_summary: str | None = Field(default=None, max_length=500)
    evidence_frame_indexes: list[int] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0, le=1)
    needs_further_attention: bool = False
    attention_reason: str = Field(default="", max_length=300)
    segment_record: MainAgentSegmentRecord | None = None
    requires_human_review: bool = False
    schema_version: str = "main-agent-judgment.v1"


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str
    subject_id: str
    event_type: EventType
    status: EventStatus
    occurred_at: datetime
    source_offset_ms: int | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    model_id: str
    model_version: str
    prompt_version: str
    schema_version: str = "event.v1"
    dedup_key: str


class HealthScenarioRequest(BaseModel):
    scenario: Literal["normal", "elevated_hr", "low_spo2", "inactive"]


class WindowRequest(BaseModel):
    window: Literal["1h", "6h", "24h", "7d", "30d"] = "24h"
    force: bool = False


class SourceActivateRequest(BaseModel):
    source: Literal["live", "replay", "simulated"]


class ReplayLoadRequest(BaseModel):
    video_id: str


class SetupSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    flow_model_provider: str | None = Field(default=None, min_length=1, max_length=80)
    flow_model_base_url: str | None = None
    flow_model_id: str | None = Field(default=None, max_length=240)
    flow_model_api_key: str | None = None
    flow_model_response_format: Literal["auto", "json_object", "json_schema"] | None = None
    flow_model_audio_mode: Literal["auto", "enabled", "disabled"] | None = None
    flow_model_context_length_behavior: Literal["error", "truncate"] | None = None
    hydration_target_ml: int | None = Field(default=None, ge=100, le=10000)
    estimated_ml_per_session: int | None = Field(default=None, ge=20, le=2000)
    fall_confirm_window_sec: int | None = Field(default=None, ge=1, le=120)
    fall_no_recovery_alert_sec: int | None = Field(default=None, ge=5, le=86400)
    demo_no_recovery_alert_sec: int | None = Field(default=None, ge=5, le=600)
    minimax_base_url: str | None = None
    minimax_model: str | None = None
    minimax_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: list[str] | None = None

    @field_validator("minimax_base_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is not None and value and not value.startswith(("http://", "https://")):
            raise ValueError("minimax_base_url must be an http(s) URL")
        return value

    @field_validator("flow_model_base_url")
    @classmethod
    def validate_flow_model_url(cls, value: str | None) -> str | None:
        if value is not None and value and not value.startswith(("http://", "https://")):
            raise ValueError("flow_model_base_url must be an http(s) URL")
        return value


class ModelDownloadRequest(BaseModel):
    model_id: str
    quantization: Literal["4bit"] = "4bit"


class AudioTranscriptRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    started_at: datetime | None = None
    duration_sec: float = Field(default=2.0, ge=0.1, le=60)
    confidence: float = Field(default=0.9, ge=0, le=1)


class FrigateEventRequest(BaseModel):
    frigate_event_id: str = Field(min_length=1, max_length=200)
    camera: str = Field(min_length=1, max_length=100)
    label: str = Field(default="person", max_length=80)
    score: float | None = Field(default=None, ge=0, le=1)
    update_type: Literal["start", "update", "end"] = "start"
    zones: list[str] = Field(default_factory=list, max_length=20)
    started_at: datetime
    ended_at: datetime | None = None
    snapshot_uri: str | None = None
    clip_uri: str | None = None
    noteworthy: bool | None = None


class VadActivityRequest(BaseModel):
    segment_id: str = Field(min_length=1, max_length=100)
    active: bool
    probability: float = Field(ge=0, le=1)
    occurred_at: datetime | None = None


class CaptureStatusRequest(BaseModel):
    camera_active: bool = False
    microphone_active: bool = False
    device_label: str | None = Field(default=None, max_length=200)


def row_json(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    import json

    result = dict(row)
    for field in fields:
        if field in result and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except json.JSONDecodeError:
                pass
    return result
