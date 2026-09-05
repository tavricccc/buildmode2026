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
  subject_id: string;
  config_version: string;
  source: { running?: boolean; kind?: string; frames_emitted?: number; scenario?: string };
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
  providers: Record<"l2" | "l3", {
    name: string; model: string; base_url: string; api_style: string;
    key_configured: boolean; active: string | null; stub: boolean;
  }>;
  secrets: Record<string, { configured: boolean; source: string; length: number }>;
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

export interface SettingsPayload {
  policy: PolicyPayload;
  providers: Record<"l2" | "l3", { name: string; model: string; base_url: string; timeout_sec: number; key_configured: boolean }>;
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
