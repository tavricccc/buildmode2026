export type Capability = "vision" | "transcription" | "analysis" | "speech" | "embedding";
export type DeploymentType = "local" | "cloud";
export type EventStatus =
  | "candidate"
  | "confirmed"
  | "recovering"
  | "resolved"
  | "dismissed"
  | "invalid";

export interface ModelEndpoint {
  id: string;
  display_name: string;
  deployment_type: DeploymentType;
  base_url: string;
  adapter_mode: string;
  enabled: boolean;
}

export interface InstalledModel {
  id: string;
  endpoint_id: string;
  remote_model_id: string;
  display_name: string;
  capability: Capability;
  source_type: "local_catalog" | "cloud_provider";
  probe_status: string;
}

export interface SettingsBundle {
  fall: { min_confidence: number; no_recovery_alert_sec: number; confirm_window_sec: number; cooldown_sec: number; demo_no_recovery_alert_sec: number };
  hydration: { target_ml_per_day: number; reminder_window_hours: number; min_confirmed_sessions: number; container_volume_ml: number };
  analysis: { default_window: "1h" | "6h" | "24h" | "7d" | "30d"; allowed_windows: string[]; timeout_sec: number; max_retries: number; cache_ttl_sec: number; manual_refresh_cooldown_sec: number };
  observer: { schedule_time: string; timezone: string; short_window_days: number; baseline_window_days: number; min_coverage: number; change_threshold: number; auto_run: boolean };
  notification: { bot_token: string; allowed_chat_ids: string[]; poll_timeout_sec: number; retry_max: number; ack_timeout_sec: number; attach_evidence: boolean; template_fields: string[] };
  vision_loop: { interval_ms: number; window_seconds: number; max_frames: number; jpeg_quality: number; jpeg_edge: number; fps: number; timeout_ms: number; max_retries: number; rate_budget_per_hour: number };
  audio: { sample_rate: number; channels: number; vad: "silero_local" | "energy_local" | "model_slot"; segment_min_ms: number; segment_max_ms: number; silence_ms: number; language: string; retention_sec: number };
  locale: string;
  timezone: string;
}

export interface StatusSnapshot {
  backend: { status: string; version: string; bind: string };
  stub_openai: { status: string; bind: string };
  db: { status: string; path: string };
  capabilities: Record<Capability, string>;
}
