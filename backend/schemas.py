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
    risk_event_type: str = Field(default="", max_length=80)
    risk_confirmed: bool = False
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


class MainAgentPeriodSummary(BaseModel):
    """Compact, durable digest used to carry important events across a day."""

    model_config = ConfigDict(extra="forbid")

    summary_text: str = Field(min_length=1, max_length=2000)
    key_events: list[str] = Field(default_factory=list, max_length=20)
    action_timeline: list[str] = Field(default_factory=list, max_length=30)
    stable_states: list[str] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=20)
    risk_level: RiskLevel
    confidence: float = Field(ge=0, le=1)
    requires_follow_up: bool = False
    follow_up_reason: str = Field(default="", max_length=500)
    schema_version: str = "main-agent-period-summary.v1"


class ResidentMemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: Literal["preference", "routine", "avoidance", "accessibility", "interest", "communication", "important_event"]
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = True


class ResidentInteractionReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply_text: str = Field(min_length=1, max_length=1200)
    intent: Literal["conversation", "question", "reminder", "confirmation", "clarification", "repeat", "stop", "forget", "memory_query", "help", "event_report", "preference_statement", "schedule_reminder", "proactive_settings", "emergency_response", "unknown"] = "unknown"
    tone: Literal["warm", "calm", "cheerful", "serious", "empathetic", "neutral"] = "warm"
    used_main_agent_context: bool = False
    memory_candidates: list[ResidentMemoryCandidate] = Field(default_factory=list, max_length=8)
    needs_follow_up: bool = False
    follow_up_question: str | None = Field(default=None, max_length=300)
    should_speak: bool = True
    confidence: float = Field(ge=0, le=1)
    safety_notes: list[str] = Field(default_factory=list, max_length=8)
    reported_event_type: str | None = Field(default=None, max_length=80)
    reported_event_summary: str | None = Field(default=None, max_length=500)
    reminder_time: str | None = Field(default=None, max_length=120)
    reminder_text: str | None = Field(default=None, max_length=600)
    proactive_enabled: bool | None = None
    proactive_interval_minutes: int | None = Field(default=None, ge=30, le=1440)
    proactive_align_to_hour: bool | None = None
    schema_version: str = "resident-interaction-reply.v1"


class ResidentUnderstandingInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_pattern: str = Field(min_length=1, max_length=1000)
    user_perspective: str = Field(min_length=1, max_length=1000)
    preference_hypotheses: list[str] = Field(default_factory=list, max_length=12)
    state_hypotheses: list[str] = Field(default_factory=list, max_length=12)
    memory_candidates: list[ResidentMemoryCandidate] = Field(default_factory=list, max_length=8)
    should_initiate: bool = False
    suggested_message: str = Field(default="", max_length=500)
    initiation_reasons: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(ge=0, le=1)
    requires_review: bool = True
    schema_version: str = "resident-understanding-insight.v1"


class ResidentAsrResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speech_detected: bool
    transcript: str = Field(default="", max_length=2000)
    language: str = Field(default="unknown", max_length=40)
    confidence: float = Field(ge=0, le=1)
    uncertainty_reasons: list[str] = Field(default_factory=list, max_length=10)
    schema_version: str = "resident-asr.v1"


class ResidentMessageRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=100)
    speak: bool = True
    audio_base64: str | None = Field(default=None, max_length=2_000_000)
    asr_only: bool = False
    emergency_response: bool = False


class ResidentMemoryUpdateRequest(BaseModel):
    action: Literal["confirm", "invalidate"]


class HighRiskResolveRequest(BaseModel):
    reason: str = Field(default="operator_resolved", max_length=300)


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

    hydration_target_ml: int | None = Field(default=None, ge=100, le=10000)
    estimated_ml_per_session: int | None = Field(default=None, ge=20, le=2000)
    fall_confirm_window_sec: int | None = Field(default=None, ge=1, le=120)
    fall_no_recovery_alert_sec: int | None = Field(default=None, ge=5, le=86400)
    demo_no_recovery_alert_sec: int | None = Field(default=None, ge=5, le=600)
    minimax_base_url: str | None = None
    minimax_model: str | None = None
    minimax_api_key: str | None = None
    local_tts_enabled: bool | None = None
    local_tts_language: str | None = Field(default=None, max_length=20)
    local_tts_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    agent_summary_interval_seconds: float | None = Field(default=None, ge=60, le=86400)
    agent_hourly_summary_interval_seconds: float | None = Field(default=None, ge=600, le=172800)
    observation_quiet_seconds: float | None = Field(default=None, ge=10, le=3600)
    observation_quiet_sample_interval_seconds: float | None = Field(default=None, ge=1, le=30)
    observation_quiet_frames: int | None = Field(default=None, ge=2, le=60)
    resident_proactive_speech_enabled: bool | None = None
    resident_proactive_interval_seconds: float | None = Field(default=None, ge=60, le=86400)
    resident_proactive_align_to_hour: bool | None = None
    resident_display_name: str | None = Field(default=None, max_length=80)
    high_risk_repeat_question_seconds: float | None = Field(default=None, ge=5, le=300)
    high_risk_no_response_seconds: float | None = Field(default=None, ge=30, le=3600)
    telegram_bot_token: str | None = None
    telegram_allowed_chat_ids: list[str] | None = None

    @field_validator("minimax_base_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is not None and value and not value.startswith(("http://", "https://")):
            raise ValueError("minimax_base_url must be an http(s) URL")
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
