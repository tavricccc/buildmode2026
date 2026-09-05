import type {
  ActivePipeline, CareAction, CareEvent, CareReviewPayload, CareSummary, CascadeTestResult,
  DebugStatus, EventDetail, PipelineRun,
  ObserverRecord, ObserverSchedulerStatus, RunStats, SettingsPayload, SetupState,
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
