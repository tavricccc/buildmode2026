// Mirrors the backend contracts in backend/domain/. Kept hand-written and
// small rather than generated: the surface the Dashboard actually reads is
// a fraction of the schema, and a drifting field shows up as a type error
// at the one place that consumes it.

export type L1Decision = "person_present" | "no_person" | "stale" | "unavailable";
export type L2Outcome = "called" | "skipped_l1" | "heartbeat" | "forced_high_risk" | "failed";
export type L3Outcome = "not_required" | "called" | "degraded_text_only" | "failed";
export type Health = "ok" | "degraded" | "unavailable" | "unknown";

export interface PipelineRun {
  run_id: string;
  window_started_at_ms: number;
  window_ended_at_ms: number;
  config_version: string;
  l1_decision: L1Decision;
  l1_confidence: number;
  l1_detector_id: string;
  l1_health: Health;
  l2_outcome: L2Outcome;
  l2_reason: string;
  l2_model: string | null;
  l2_latency_ms: number | null;
  l2_repaired: boolean;
  l2_escalation_required: boolean;
  l2_escalation_reasons: string[];
  l2_error: string | null;
  l3_outcome: L3Outcome;
  l3_reason: string;
  l3_model: string | null;
  l3_latency_ms: number | null;
  l3_risk_level: string | null;
  l3_error: string | null;
  clip_path: string | null;
  event_ids: string[];
}

export interface RunStats {
  windows: number;
  skipped_by_l1: number;
  l2_calls: number;
  heartbeats: number;
  forced: number;
  l2_failures: number;
  escalations: number;
  l3_calls: number;
  l3_degraded: number;
  l3_failures: number;
  l2_latency_avg: number | null;
  l2_latency_max: number | null;
  l3_latency_avg: number | null;
  skip_ratio: number;
}

export interface CareEvent {
  event_id: string;
  event_type: "fall" | "hydration";
  status: string;
  occurred_at_ms: number;
  updated_at_ms: number;
  ended_at_ms: number | null;
  confidence: number;
  attributes: Record<string, unknown>;
}

export interface ModelCall {
  call_id: string;
  layer: string;
  provider: string;
  model: string;
  purpose: string;
  status: "ok" | "repaired" | "invalid" | "failed";
  latency_ms: number;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  total_tokens: number | null;
  created_at: string;
}

export interface Analysis {
  analysis_id: string;
  trigger: string;
  reason_codes: string;
  degraded: number;
  risk_level: string | null;
  recommendation: string | null;
  supports_l2: number;
  created_at: string;
}

export interface CareAction {
  action_id: string;
  kind: string;
  rule: string;
  reason: string;
  severity: string;
  suppressed: number;
  suppressed_reason: string;
  created_at: string;
}

export interface EventDetail {
  event: CareEvent;
  runs: PipelineRun[];
  model_calls: ModelCall[];
  analyses: Analysis[];
  actions: CareAction[];
}

export interface QueueMetrics {
  running: boolean;
  pending: boolean;
  pending_high_risk: boolean;
  accepted: number;
  dropped: number;
  rejected: number;
  completed: number;
}

export interface Status {
  uptime_ms: number;
  runtime: { mode: "production" | "debug"; debug: boolean };
  subject_id: string;
  config_version: string;
  browser_media: BrowserMediaHealth[];
  source: {
    running?: boolean; kind?: string; frames_emitted?: number; scenario?: string;
    source_id?: string; reconnects?: number; last_frame_age_ms?: number | null;
    error?: string | null; uri_host?: string; lifecycle?: "starting" | "running" | "completed" | "stopped" | "failed";
  };
  cascade: {
    windows_seen: number;
    starved_since_ms: number | null;
    frames: { frames: number; capacity: number; dropped: number };
    l1: {
      detector: { detector_id: string; status: Health; calls?: number; note?: string };
      decision: { decision: L1Decision; confidence: number; reason: string; age_ms: number };
      gate: { state: string; flips: number; skips_permitted: number; fail_opens: number };
      health: Health;
    };
    l2: { queue: QueueMetrics; model: string | null };
    l3: { queue: QueueMetrics; model: string | null; enabled: boolean; today: number };
    events: Record<string, { status: string; event_id: string | null; observations: number }>;
  };
  realtime: { clients: number; sequence: number; sent: number; dropped: number };
  observer: ObserverSchedulerStatus;
  providers: Record<"l2" | "l3", {
    name: string; model: string; base_url: string; api_style: string;
    key_configured: boolean; active: string | null; stub: boolean;
  }>;
  secrets: Record<string, { configured: boolean; source: string; length: number }>;
}

export interface CareSummary {
  state: "intervention_required" | "attention" | "recovering" | "stable" | "insufficient_evidence" | "source_unavailable";
  urgency: "immediate" | "today" | "watch" | "none" | "unknown";
  headline: string;
  reasons: string[];
  recommended_next_step: string;
  confidence: number;
  data_completeness: number;
  policy_status: string;
  delivery_status: string;
  generated_at_ms: number;
  source_event_id: string | null;
  limitations: string[];
  source_lifecycle: string;
  runtime_mode: "production" | "debug";
}

export interface PipelineStep {
  step_id: string;
  run_id: string;
  event_id: string | null;
  step: string;
  status: "waiting" | "running" | "succeeded" | "skipped" | "degraded" | "failed";
  summary: string;
  reason_codes: string[];
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  mode: "live" | "debug";
  started_at_ms: number;
  completed_at_ms: number | null;
}

export interface ActivePipeline {
  active: PipelineStep[];
  recent: PipelineStep[];
  source: Status["source"];
}

export interface DebugStatus {
  stream: { running: boolean; profile?: string; seed?: number; interval_sec?: number; events?: number; last_scenario?: string };
  scenarios: { id: string; name: string }[];
}

export interface BrowserMediaHealth {
  source_id: string;
  kind: "browser_webm";
  camera_id: string;
  media_type: string;
  running: boolean;
  bytes_received: number;
  chunks_received: number;
  frames_emitted: number;
  audio_bytes: number;
  error: string | null;
  started_at_ms: number;
}

export interface BrowserUploadHealth {
  source_id: string;
  kind: "browser_upload";
  filename: string;
  state: "uploading" | "uploaded" | "processing" | "completed" | "failed";
  event_start_ms: number;
  bytes_received: number;
  chunks_received: number;
  compressed_path: string | null;
  compressed_bytes: number;
  source: Status["source"] | null;
  error: string | null;
  started_at_ms: number;
}

export interface InteractionMessage { message_id: string; role: "user" | "assistant"; text: string; intent: string; created_at: string; }
export interface MemoryRecord { memory_id: string; memory_type: string; title: string; content: string; confidence: number; status: "pending" | "confirmed" | "invalidated"; requires_confirmation: number; created_at: string; updated_at: string; }
export interface AgentRun { agent_run_id: string; agent_name: string; trigger_type: string; status: string; input_context: Record<string, unknown>; output: Record<string, unknown>; error_code: string | null; latency_ms: number | null; created_at: string; completed_at: string | null; }
export interface SocialWorkRecord { record_id: string; record_type: string; occurred_at_ms: number; author: string; content: string; tags: string[]; created_at: string; privacy_redacted?: boolean; }
export interface PrivacyDimension { key: "sleep" | "diet" | "exercise" | "social"; name: string; status: "未見異常" | "需要進一步確認" | "資料不足"; score: number; }
export interface StatusReport { report_id: string; report_type: string; window_start_ms: number; window_end_ms: number; title: string; body: string; sources: Record<string, unknown> & { privacy_dimensions?: PrivacyDimension[]; medication_status?: string }; created_at: string; }
export interface AuditPayload { database: { path: string; tables: Record<string, number> }; logs: Array<{ log_id: string; level: string; source: string; message: string; context_json: string; created_at: string }>; pipeline_runs: PipelineRun[]; observations: Array<{ observation_id: string; observed_at_ms: number; summary: string; confidence: number; payload: Record<string, unknown> }>; model_calls: Array<Record<string, unknown>>; agent_runs: AgentRun[]; memories: MemoryRecord[]; social_work_records: SocialWorkRecord[]; note: string; }

export type ObserverState = "stable" | "attention" | "insufficient_evidence" | "anomaly" | "failed";

export interface ObserverSchedulerStatus {
  running: boolean;
  interval_sec: number;
  last_started_at_ms: number | null;
  last_completed_at_ms: number | null;
  next_run_at_ms: number | null;
  last_error: string | null;
}

export interface ObserverRecord {
  observer_run_id: string;
  subject_id: string;
  window_started_at_ms: number;
  window_ended_at_ms: number;
  status: ObserverState;
  headline: string;
  detail: string;
  confidence: number;
  data_completeness: number;
  mode: "deterministic" | "l3_narrative";
  call_id: string | null;
  metrics: {
    hydration_ml?: number; hydration_sessions?: number; fall_events?: number;
    windows?: number; coverage_ratio?: number; skip_ratio?: number;
    activity_ratio?: number; motionless_ratio?: number; observation_count?: number;
    current_posture?: string; current_motionless?: boolean;
    current_scene_summary?: string; current_confidence?: number;
    posture_counts?: Record<string, number>;
  };
  anomaly_codes: string[];
  created_at: string;
}

export interface DailySummary {
  day_key: string;
  hydration_ml: number;
  hydration_sessions: number;
  fall_events: number;
  l2_calls: number;
  l2_skipped: number;
  l3_calls: number;
  coverage_ratio: number;
  payload: ObserverRecord["metrics"] & { l2_failures?: number };
}

export interface HealthSample {
  sample_id?: string;
  metric: string;
  value: number;
  unit: string;
  source: string;
  observed_at_ms: number;
}

export interface StatisticsPayload {
  days: number;
  summaries: DailySummary[];
  observer_status_counts: Partial<Record<ObserverState, number>>;
  recent_observations: ObserverRecord[];
  health_samples: HealthSample[];
}

export interface CareReview {
  summary: string;
  risk_level: "none" | "low" | "medium" | "high" | "critical";
  confidence: number;
  recommendations: string[];
  positive_signals: string[];
  attention_items: string[];
  data_limitations: string[];
}

export interface CareReviewPayload {
  ok: true;
  days: number;
  generated_at_ms: number;
  call_id: string;
  finding_id: string;
  model: string;
  analysis: CareReview;
  data_counts: {
    daily_summaries: number;
    health_measurements: number;
    care_events: number;
    observer_records: number;
  };
}

export interface SetupStep {
  id: string;
  label: string;
  done: boolean;
  detail: string;
}

export interface SetupState {
  steps: SetupStep[];
  complete: boolean;
  detectors: Record<string, string>;
  scenarios: string[];
}

export interface CascadeTestResult {
  scenario: string;
  run_id: string;
  l1: { decision: string; detector: string };
  l2: { outcome: string; model: string | null; latency_ms: number | null; repaired: boolean; error: string | null; escalation: string[] };
  l3: { outcome: string; model: string | null; latency_ms: number | null; risk: string | null; error: string | null };
  trace: { layer: string; outcome: string; detail: string; latency_ms: string }[];
}

export interface PolicyPayload {
  version: string;
  l1: Record<string, number | string | boolean>;
  cadence: Record<string, number>;
  fall: Record<string, number>;
  hydration: Record<string, number>;
  escalation: Record<string, number | boolean | string[]>;
  notification: Record<string, number | boolean>;
}

/** One entry in a slot's provider menu, as the backend advertises it. */
export interface ProviderOption {
  name: string;
  label: string;
  secret_key: string;
  default_model: string;
}

export interface SettingsPayload {
  policy: PolicyPayload;
  providers: Record<"l2" | "l3", { name: string; model: string; base_url: string; timeout_sec: number; key_configured: boolean }>;
  /** What each slot may be switched to. Sourced from the backend so the UI
   *  cannot offer a provider this build has no adapter for. */
  provider_options: Record<"l2" | "l3", ProviderOption[]>;
  secrets: Record<string, { configured: boolean; source: string; length: number }>;
  detectors: Record<string, string>;
  versions: { version: string; note: string; is_active: number; created_at: string }[];
  host_managed: Record<string, string>;
}

export interface WsMessage {
  seq: number;
  topic: string;
  payload: Record<string, unknown>;
}
