from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _secret_from_file(path: str) -> str:
    if not path:
        return ""
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    if "=" in value:
        name, candidate = value.split("=", 1)
        if name.strip().lower() in {"api_key", "gmi_api_key", "minimax_api_key", "flow_model_api_key"}:
            return candidate.strip().strip("\"'")
    return value


@dataclass
class Settings:
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    demo_mode: str = field(default_factory=lambda: os.getenv("DEMO_MODE", "replay"))
    active_source: str = field(default_factory=lambda: os.getenv("ACTIVE_SOURCE", "replay"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/care_agent.db"))
    media_root: str = field(default_factory=lambda: os.getenv("MEDIA_ROOT", "data/media"))
    backend_host: str = field(default_factory=lambda: os.getenv("BACKEND_HOST", "127.0.0.1"))
    backend_port: int = field(default_factory=lambda: int(os.getenv("BACKEND_PORT", "8000")))
    frontend_origin: str = field(default_factory=lambda: os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"))
    local_vlm_mode: str = field(default_factory=lambda: os.getenv("LOCAL_VLM_MODE", "stub"))
    local_vlm_model: str = field(default_factory=lambda: os.getenv("LOCAL_VLM_MODEL", "nemotron_omni"))
    local_vlm_quantization: str = field(default_factory=lambda: os.getenv("LOCAL_VLM_QUANTIZATION", "4bit"))
    vllm_base_url: str = field(default_factory=lambda: os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"))
    vllm_model: str = field(default_factory=lambda: os.getenv("VLLM_MODEL", "nemotron_omni"))
    vllm_api_key: str = field(default_factory=lambda: os.getenv("VLLM_API_KEY", ""))
    vllm_sample_fps: float = field(default_factory=lambda: float(os.getenv("VLLM_SAMPLE_FPS", "2.0")))
    vllm_window_seconds: float = field(default_factory=lambda: float(os.getenv("VLLM_WINDOW_SECONDS", "5.0")))
    vllm_window_stride_seconds: float = field(default_factory=lambda: float(os.getenv("VLLM_WINDOW_STRIDE_SECONDS", "5.0")))
    vllm_window_frames: int = field(default_factory=lambda: int(os.getenv("VLLM_WINDOW_FRAMES", "10")))
    vllm_max_frame_width: int = field(default_factory=lambda: int(os.getenv("VLLM_MAX_FRAME_WIDTH", "1280")))
    vllm_max_concurrency: int = field(default_factory=lambda: max(1, int(os.getenv("VLLM_MAX_CONCURRENCY", "2"))))
    vllm_max_pending_windows: int = field(default_factory=lambda: max(1, int(os.getenv("VLLM_MAX_PENDING_WINDOWS", "8"))))
    observation_heartbeat_seconds: float = field(default_factory=lambda: max(0.0, float(os.getenv("OBSERVATION_HEARTBEAT_SECONDS", "15"))))
    change_gate_threshold: float = field(default_factory=lambda: max(0.005, min(0.5, float(os.getenv("CHANGE_GATE_THRESHOLD", "0.06")))))
    change_gate_audio_delta_threshold: float = field(default_factory=lambda: max(0.005, min(0.5, float(os.getenv("CHANGE_GATE_AUDIO_DELTA_THRESHOLD", "0.06")))))
    change_gate_min_changed_pairs: int = field(default_factory=lambda: max(1, int(os.getenv("CHANGE_GATE_MIN_CHANGED_PAIRS", "2"))))
    change_gate_strong_score_multiplier: float = field(default_factory=lambda: max(1.0, float(os.getenv("CHANGE_GATE_STRONG_SCORE_MULTIPLIER", "2.5"))))
    vision_wire_format: str = field(default_factory=lambda: os.getenv("VISION_WIRE_FORMAT", "frames").strip().lower())
    vision_video_crf: int = field(default_factory=lambda: max(0, min(51, int(os.getenv("VISION_VIDEO_CRF", "28")))))
    vision_video_max_width: int = field(default_factory=lambda: max(64, int(os.getenv("VISION_VIDEO_MAX_WIDTH", "768"))))
    vision_video_encode_timeout: float = field(default_factory=lambda: max(1.0, float(os.getenv("VISION_VIDEO_ENCODE_TIMEOUT", "20"))))
    vllm_observation_enable_thinking: bool = field(default_factory=lambda: _bool("VLLM_OBSERVATION_ENABLE_THINKING", False))
    vllm_main_agent_enable_thinking: bool = field(default_factory=lambda: _bool("VLLM_MAIN_AGENT_ENABLE_THINKING", False))
    flow_model_provider: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_PROVIDER", "local_vlm").strip().lower())
    flow_model_base_url: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_BASE_URL", "").rstrip("/"))
    flow_model_id: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_ID", ""))
    flow_model_api_key_file: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_API_KEY_FILE", ""))
    flow_model_api_key: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_API_KEY", "") or _secret_from_file(os.getenv("FLOW_MODEL_API_KEY_FILE", "")))
    flow_model_response_format: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_RESPONSE_FORMAT", "auto").strip().lower())
    flow_model_audio_mode: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_AUDIO_MODE", "auto").strip().lower())
    flow_model_context_length_behavior: str = field(default_factory=lambda: os.getenv("FLOW_MODEL_CONTEXT_LENGTH_BEHAVIOR", "error").strip().lower())
    video_retention_seconds: int = field(default_factory=lambda: max(10, int(os.getenv("VIDEO_RETENTION_SECONDS", "60"))))
    detail_sample_fps: float = field(default_factory=lambda: float(os.getenv("DETAIL_SAMPLE_FPS", "5.0")))
    detail_window_seconds: float = field(default_factory=lambda: float(os.getenv("DETAIL_WINDOW_SECONDS", "2.0")))
    detail_window_frames: int = field(default_factory=lambda: max(2, int(os.getenv("DETAIL_WINDOW_FRAMES", "10"))))
    detail_window_stride_seconds: float = field(default_factory=lambda: float(os.getenv("DETAIL_WINDOW_STRIDE_SECONDS", "1.0")))
    detail_active_seconds: float = field(default_factory=lambda: float(os.getenv("DETAIL_ACTIVE_SECONDS", "10.0")))
    detail_max_pending: int = field(default_factory=lambda: max(1, int(os.getenv("DETAIL_MAX_PENDING", "2"))))
    focus_window_seconds: float = field(default_factory=lambda: float(os.getenv("FOCUS_WINDOW_SECONDS", "10.0")))
    focus_window_frames: int = field(default_factory=lambda: max(2, int(os.getenv("FOCUS_WINDOW_FRAMES", "20"))))
    main_agent_enabled: bool = field(default_factory=lambda: _bool("MAIN_AGENT_ENABLED", True))
    main_agent_max_pending: int = field(default_factory=lambda: max(1, int(os.getenv("MAIN_AGENT_MAX_PENDING", "6"))))
    main_agent_interval_seconds: float = field(default_factory=lambda: max(5.0, float(os.getenv("MAIN_AGENT_INTERVAL_SECONDS", "20"))))
    main_agent_min_confidence: float = field(default_factory=lambda: float(os.getenv("MAIN_AGENT_MIN_CONFIDENCE", "0.55")))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    minimax_base_url: str = field(default_factory=lambda: os.getenv("MINIMAX_BASE_URL", "").rstrip("/"))
    minimax_api_key_file: str = field(default_factory=lambda: os.getenv("MINIMAX_API_KEY_FILE", ""))
    minimax_api_key: str = field(default_factory=lambda: os.getenv("MINIMAX_API_KEY", "") or _secret_from_file(os.getenv("MINIMAX_API_KEY_FILE", "")))
    minimax_model: str = field(default_factory=lambda: os.getenv("MINIMAX_MODEL", "MiniMaxAI/MiniMax-M3"))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_allowed_chat_ids: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip() for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()))
    telegram_poll_timeout_sec: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_POLL_TIMEOUT_SEC", "20")))
    frigate_frame_endpoint: str = field(default_factory=lambda: os.getenv("FRIGATE_FRAME_ENDPOINT", "").rstrip("/"))
    frigate_noteworthy_labels: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip().lower() for x in os.getenv("FRIGATE_NOTEWORTHY_LABELS", "fall,fire,smoke").split(",") if x.strip()))
    frigate_noteworthy_zones: tuple[str, ...] = field(default_factory=lambda: tuple(x.strip().lower() for x in os.getenv("FRIGATE_NOTEWORTHY_ZONES", "").split(",") if x.strip()))
    frigate_rtsp_publish_url: str = field(default_factory=lambda: os.getenv("FRIGATE_RTSP_PUBLISH_URL", "").strip())
    virtual_camera_enabled: bool = field(default_factory=lambda: os.getenv("VIRTUAL_CAMERA_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"})
    subject_id: str = field(default_factory=lambda: os.getenv("SUBJECT_ID", "resident_demo"))
    hydration_target_ml: int = field(default_factory=lambda: int(os.getenv("HYDRATION_TARGET_ML", "1600")))
    estimated_ml_per_session: int = field(default_factory=lambda: int(os.getenv("ESTIMATED_ML_PER_SESSION", "200")))
    fall_confirm_window_sec: int = field(default_factory=lambda: int(os.getenv("FALL_CONFIRM_WINDOW_SEC", "8")))
    fall_min_confidence: float = field(default_factory=lambda: float(os.getenv("FALL_MIN_CONFIDENCE", "0.70")))
    fall_no_recovery_alert_sec: int = field(default_factory=lambda: int(os.getenv("FALL_NO_RECOVERY_ALERT_SEC", "120")))
    demo_no_recovery_alert_sec: int = field(default_factory=lambda: int(os.getenv("DEMO_NO_RECOVERY_ALERT_SEC", "10")))
    hydration_session_close_sec: int = field(default_factory=lambda: int(os.getenv("HYDRATION_SESSION_CLOSE_SEC", "4")))
    transcript_retention_minutes: int = field(default_factory=lambda: int(os.getenv("TRANSCRIPT_RETENTION_MINUTES", "30")))
    config_version: str = field(default_factory=lambda: os.getenv("CONFIG_VERSION", "config.v1"))

    @property
    def database_file(self) -> Path:
        return Path(self.database_path)

    @property
    def media_directory(self) -> Path:
        return Path(self.media_root)

    @property
    def minimax_configured(self) -> bool:
        return bool(self.minimax_base_url and self.minimax_api_key)

    @property
    def inference_provider(self) -> str:
        provider = self.flow_model_provider.strip().lower()
        if provider in {"gmi", "gmi_cloud", "minimax_cloud"}:
            return "gmi_cloud"
        if provider in {"", "local", "local_vlm", "vllm"}:
            return "local_vlm"
        # Keep explicitly configured cloud providers visible to the gateway.
        # The adapter uses capabilities/format settings instead of treating
        # every non-GMI provider as a local vLLM endpoint.
        return provider

    @property
    def inference_base_url(self) -> str:
        if self.inference_provider == "local_vlm":
            return self.vllm_base_url
        if self.inference_provider == "gmi_cloud":
            return (self.flow_model_base_url or "https://api.gmi-serving.com/v1").rstrip("/")
        return self.flow_model_base_url.rstrip("/")

    @property
    def inference_model(self) -> str:
        if self.inference_provider == "local_vlm":
            return self.vllm_model
        if self.inference_provider == "gmi_cloud":
            return self.flow_model_id or self.minimax_model or "MiniMaxAI/MiniMax-M3"
        return self.flow_model_id

    @property
    def inference_api_key(self) -> str:
        if self.inference_provider == "local_vlm":
            return self.vllm_api_key
        if self.inference_provider == "gmi_cloud":
            return self.flow_model_api_key or self.minimax_api_key
        return self.flow_model_api_key

    @property
    def inference_response_format(self) -> str:
        """Return the structured-output wire format for the active endpoint.

        Cloud providers default to the portable json_object contract. Local
        runtimes keep the existing json_schema path unless explicitly
        overridden, while a provider-specific override supports probing a
        compatible endpoint that has different guarantees.
        """
        configured = self.flow_model_response_format
        if configured in {"json_object", "json_schema"}:
            return configured
        return "json_schema" if self.inference_provider == "local_vlm" else "json_object"

    @property
    def inference_audio_enabled(self) -> bool:
        """Whether audio is sent to the active model and trusted in output.

        ``auto`` is intentionally conservative for cloud endpoints: audio is
        enabled only after an endpoint/model-specific probe opts in. The
        existing local Omni path remains enabled by default.
        """
        mode = self.flow_model_audio_mode
        if mode in {"on", "true", "enabled", "yes"}:
            return True
        if mode in {"off", "false", "disabled", "no"}:
            return False
        return self.inference_provider == "local_vlm"

    @property
    def inference_context_length_behavior(self) -> str:
        return self.flow_model_context_length_behavior if self.flow_model_context_length_behavior in {"error", "truncate"} else "error"

    @property
    def vision_video_mode(self) -> bool:
        """True when the vision window should be sent as one video_url part.

        Defaults to False: the provider does not document a video_url wire
        format for the hosted model, so `frames` stays the verified default
        until a capability probe passes.
        """
        return self.vision_wire_format in {"video", "video_url"}

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_allowed_chat_ids)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    global _settings
    _settings = None
