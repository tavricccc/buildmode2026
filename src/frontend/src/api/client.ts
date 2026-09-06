import type {
  ActivePipeline, CareAction, CareEvent, CareReviewPayload, CareSummary, CascadeTestResult,
  DebugStatus, EventDetail, PipelineRun,
  AgentRun, AuditPayload, BrowserMediaHealth, InteractionMessage, MemoryRecord,
  ObserverRecord, ObserverSchedulerStatus, RunStats, SettingsPayload, SetupState,
  SocialWorkRecord, StatusReport,
  StatisticsPayload, Status,
} from "../types/api";

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const error = payload?.error ?? {};
    throw new ApiError(response.status, error.code ?? "unknown", error.message ?? response.statusText);
  }
  return payload as T;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  status: () => call<Status>("/api/status"),
  careSummary: () => call<CareSummary>("/api/care/summary"),
  activePipeline: () => call<ActivePipeline>("/api/pipeline/active?limit=160"),
  setupState: () => call<SetupState>("/api/setup/state"),

  runs: (limit = 60) => call<{ runs: PipelineRun[]; stats: RunStats }>(`/api/pipeline/runs?limit=${limit}`),
  events: (limit = 30) => call<{ events: CareEvent[] }>(`/api/events?limit=${limit}`),
  event: (id: string) => call<EventDetail>(`/api/events/${encodeURIComponent(id)}`),
  actions: (limit = 30) => call<{ actions: CareAction[] }>(`/api/actions?limit=${limit}`),
  hydration: () => call<{ day: string; sessions: number; total_ml: number; target_ml: number; progress: number }>("/api/hydration/summary"),
  health: () => call<{ samples: { metric: string; value: number; unit: string; source: string; observed_at_ms: number }[] }>("/api/health/current"),
  logs: (limit = 60) => call<{ logs: { log_id: string; level: string; source: string; message: string; created_at: string }[] }>(`/api/logs?limit=${limit}`),
  observerFindings: () => call<{ findings: { finding_id: string; kind: string; headline: string; detail: string; severity: string; day_key: string }[]; summaries: unknown[] }>("/api/observer/findings"),
  observerStatus: () => call<{ scheduler: ObserverSchedulerStatus; latest: ObserverRecord | null }>("/api/observer/status"),
  observerRecords: (limit = 50) => call<{ records: ObserverRecord[] }>(`/api/observer/records?limit=${limit}`),
  statistics: (days = 30) => call<StatisticsPayload>(`/api/statistics?days=${days}`),
  agentRuns: (limit = 50) => call<{ runs: AgentRun[] }>(`/api/agent/runs?limit=${limit}`),
  memories: (limit = 50) => call<{ memories: MemoryRecord[] }>(`/api/memory?limit=${limit}`),
  setMemoryStatus: (id: string, status: "confirmed" | "invalidated") => post<{ memory_id: string; status: string }>(`/api/memory/${encodeURIComponent(id)}/status`, { status }),
  interactionMessages: () => call<{ messages: InteractionMessage[] }>("/api/interaction/messages"),
  interactionTurn: (text: string) => post<Record<string, unknown>>("/api/interaction/turn", { text }),
  interactionUnderstanding: () => post<Record<string, unknown>>("/api/interaction/understanding"),
  socialWorkRecords: (limit = 100) => call<{ records: SocialWorkRecord[] }>(`/api/social-work/records?limit=${limit}`),
  addSocialWorkRecord: (body: { record_type: string; occurred_at_ms: number; author: string; content: string; tags: string[] }) => post<{ record_id: string }>("/api/social-work/records", body),
  autoGenerateSocialWorkRecord: (hours = 24, record_type = "case_note", author = "AI 社工助理 (事件自動彙整)") =>
    post<{
      record_id: string;
      report_id: string;
      title: string;
      body: string;
      window_hours: number;
      window_start_ms: number;
      window_end_ms: number;
      sources: Record<string, unknown>;
      stats: {
        warning_count: number;
        follow_up_count: number;
        privacy_safe: boolean;
      };
    }>("/api/social-work/auto-generate", { hours, record_type, author }),
  statusReports: () => call<{ reports: StatusReport[] }>("/api/reports/status"),
  generateStatusReport: (report_type: string, days: number) => post<StatusReport>(`/api/reports/status?days=${days}`, { report_type, days }),
  audit: (limit = 100) => call<AuditPayload>(`/api/audit?limit=${limit}`),
  auditLogFiles: () => call<{ files: Array<{ name: string; size_bytes: number; modified_at_ms: number }> }>("/api/audit/log-files"),
  auditLogFile: (name: string) => call<{ name: string; tail: string; truncated: boolean }>(`/api/audit/log-files/${encodeURIComponent(name)}`),

  settings: () => call<SettingsPayload>("/api/settings"),
  saveSettings: (policy: unknown, note: string) =>
    call<{ version: string }>("/api/settings", { method: "PUT", body: JSON.stringify({ policy, note }) }),
  rollback: (version: string) => post<{ version: string }>("/api/settings/rollback", { version }),
  saveProviders: (body: unknown) => post<unknown>("/api/settings/providers", body),
  saveSecret: (key: string, value: string) => post<unknown>("/api/secrets", { key, value }),

  testPersonGate: (detectorId?: string) => post<unknown>("/api/integrations/person-gate/test", { detector_id: detectorId }),
  testGemini: () => post<{ ok: boolean; code?: string; message?: string; model_available?: boolean }>("/api/integrations/gemini/test"),
  testMinimax: () => post<{ ok: boolean; code?: string; message?: string; model_available?: boolean }>("/api/integrations/minimax/test"),
  cascadeTest: (scenario: string) => post<CascadeTestResult>("/api/pipeline/cascade-test", { scenario }),

  scenarios: () => call<{ scenarios: { id: string; name: string; description: string }[] }>("/api/replay/scenarios"),
  startSource: (kind: string, target: string) => post<unknown>("/api/source/start", { kind, target }),
  stopSource: () => post<unknown>("/api/source/stop"),
  runObserver: () => post<unknown>("/api/observer/run"),
  analyzeAll: (days: 1 | 3 | 7 | 30) => post<CareReviewPayload>("/api/observer/analyze-all", { days }),
  resetHistory: () => post<{ deleted: Record<string, number>; preserved: string[] }>("/api/reset/history"),
  mediaStreams: () => call<{ active: BrowserMediaHealth[]; source: Status["source"] }>("/api/media/streams"),
  sourceSnapshotUrl: () => `/api/source/snapshot?t=${Date.now()}`,
  debugStatus: () => call<DebugStatus>("/api/debug/scenarios"),
  generateDebugHistory: (days: number, profile: string, seed: number) =>
    post<Record<string, unknown>>("/api/debug/history/generate", { days, profile, seed }),
  triggerDebugScenario: (scenario: string, mode: "contract" | "evaluation") =>
    post<Record<string, unknown>>("/api/debug/scenarios/trigger", { scenario, mode }),
  startDebugStream: (profile: string, seed: number, interval_sec: number) =>
    post<Record<string, unknown>>("/api/debug/stream/start", { profile, seed, interval_sec }),
  stopDebugStream: () => post<Record<string, unknown>>("/api/debug/stream/stop"),
};
