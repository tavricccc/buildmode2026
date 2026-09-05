import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { RealtimeClient } from "../api/ws";
import { Card, Empty } from "../components/ui";
import type { CareAction, CareEvent, PipelineRun, RunStats, Status } from "../types/api";
import { CascadeTrace } from "./CascadeTrace";
import { PipelinePanel } from "./PipelinePanel";
import { RunTable } from "./RunTable";
import {
  ActionsPanel, EventTimeline, HealthPanel, HydrationPanel, LogPanel, SourcePanel,
} from "./SidePanels";

type Hydration = { sessions: number; total_ml: number; target_ml: number; progress: number };

export function DashboardPage({ status, realtime }: { status: Status | null; realtime: RealtimeClient }) {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [actions, setActions] = useState<CareAction[]>([]);
  const [hydration, setHydration] = useState<Hydration | null>(null);
  const [samples, setSamples] = useState<{ metric: string; value: number; unit: string; source: string }[]>([]);
  const [findings, setFindings] = useState<{ finding_id: string; headline: string; detail: string; severity: string }[]>([]);
  const [logs, setLogs] = useState<{ log_id: string; level: string; source: string; message: string; created_at: string }[]>([]);
  const [scenarios, setScenarios] = useState<{ id: string; name: string }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Coalesce bursts: a fall produces a run, an event and an action within
  // milliseconds, and refetching three times would just race itself.
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const [runData, eventData, actionData, hydrationData, healthData, logData, observerData] =
      await Promise.allSettled([
        api.runs(60), api.events(30), api.actions(30), api.hydration(),
        api.health(), api.logs(60), api.observerFindings(),
      ]);
    if (runData.status === "fulfilled") { setRuns(runData.value.runs); setStats(runData.value.stats); }
    if (eventData.status === "fulfilled") setEvents(eventData.value.events);
    if (actionData.status === "fulfilled") setActions(actionData.value.actions);
    if (hydrationData.status === "fulfilled") setHydration(hydrationData.value);
    if (healthData.status === "fulfilled") setSamples(healthData.value.samples);
    if (logData.status === "fulfilled") setLogs(logData.value.logs);
    if (observerData.status === "fulfilled") setFindings(observerData.value.findings);
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => {
      pending.current = null;
      void refresh();
    }, 400);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    void api.scenarios().then((data) => setScenarios(data.scenarios)).catch(() => undefined);
    const offMessage = realtime.onMessage(scheduleRefresh);
    // A reconnect may have missed frames, so resync over REST rather than
    // trusting an incremental stream with holes in it.
    const offResync = realtime.onResync(() => void refresh());
    return () => {
      offMessage();
      offResync();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [refresh, scheduleRefresh, realtime]);

  const control = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); await refresh(); } finally { setBusy(false); }
  };

  if (!status) return <Card title="Dashboard"><Empty>Connecting to the backend…</Empty></Card>;

  return (
    <div className="stack">
      {stats && <PipelinePanel status={status} stats={stats} />}

      <SourcePanel
        status={status}
        scenarios={scenarios}
        busy={busy}
        onStart={(id) => control(() => api.startSource("replay_scenario", id))}
        onStop={() => control(() => api.stopSource())}
      />

      {selected && <CascadeTrace eventId={selected} onClose={() => setSelected(null)} />}

      <div className="grid cols-2">
        <EventTimeline events={events} onSelect={setSelected} />
        <div className="stack">
          <HydrationPanel summary={hydration} />
          <HealthPanel samples={samples} findings={findings} />
        </div>
      </div>

      <RunTable runs={runs} onSelectEvent={setSelected} />

      <div className="grid cols-2">
        <ActionsPanel actions={actions} />
        <LogPanel logs={logs} />
      </div>
    </div>
  );
}
