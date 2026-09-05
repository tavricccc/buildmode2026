import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Brain, CaretRight, ShieldCheck, VideoCamera } from "@phosphor-icons/react";
import type { AppTab } from "../App";
import { api } from "../api/client";
import type { RealtimeClient } from "../api/ws";
import { Badge, Card, Empty } from "../components/ui";
import type { CareAction, CareEvent, ObserverRecord, PipelineRun, RunStats, Status } from "../types/api";
import { CascadeTrace } from "./CascadeTrace";
import { PipelinePanel } from "./PipelinePanel";
import { RunTable } from "./RunTable";
import { ActionsPanel, EventTimeline, HealthPanel, HydrationPanel, LogPanel } from "./SidePanels";

type Hydration = { sessions: number; total_ml: number; target_ml: number; progress: number };

const observerTone = (record: ObserverRecord | null) => record?.status === "anomaly" ? "bad" : record?.status === "attention" ? "warn" : record?.status === "stable" ? "ok" : "muted";

export function DashboardPage({ status, realtime, onNavigate }: {
  status: Status | null; realtime: RealtimeClient; onNavigate: (tab: AppTab) => void;
}) {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [actions, setActions] = useState<CareAction[]>([]);
  const [hydration, setHydration] = useState<Hydration | null>(null);
  const [samples, setSamples] = useState<{ metric: string; value: number; unit: string; source: string }[]>([]);
  const [findings, setFindings] = useState<{ finding_id: string; headline: string; detail: string; severity: string }[]>([]);
  const [logs, setLogs] = useState<{ log_id: string; level: string; source: string; message: string; created_at: string }[]>([]);
  const [observer, setObserver] = useState<ObserverRecord | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      api.runs(60), api.events(30), api.actions(30), api.hydration(), api.health(),
      api.logs(60), api.observerFindings(), api.observerStatus(),
    ]);
    const [runData, eventData, actionData, hydrationData, healthData, logData, observerData, observerStatus] = results;
    if (runData.status === "fulfilled") { setRuns(runData.value.runs); setStats(runData.value.stats); }
    if (eventData.status === "fulfilled") setEvents(eventData.value.events);
    if (actionData.status === "fulfilled") setActions(actionData.value.actions);
    if (hydrationData.status === "fulfilled") setHydration(hydrationData.value);
    if (healthData.status === "fulfilled") setSamples(healthData.value.samples);
    if (logData.status === "fulfilled") setLogs(logData.value.logs);
    if (observerData.status === "fulfilled") setFindings(observerData.value.findings);
    if (observerStatus.status === "fulfilled") setObserver(observerStatus.value.latest);
  }, []);

  const scheduleRefresh = useCallback(() => {
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => { pending.current = null; void refresh(); }, 400);
  }, [refresh]);

  useEffect(() => {
    void refresh();
    const offMessage = realtime.onMessage(scheduleRefresh);
    const offResync = realtime.onResync(() => void refresh());
    return () => { offMessage(); offResync(); if (pending.current !== null) window.clearTimeout(pending.current); };
  }, [refresh, scheduleRefresh, realtime]);

  if (!status) return <Card title="照護總覽"><Empty>正在連線至後端…</Empty></Card>;

  const unsafe = events.some((event) => event.event_type === "fall" && ["suspect", "confirmed"].includes(event.status));
  const browserMediaRunning = status.browser_media.some((session) => session.running);
  const sourceStarved = status.cascade.starved_since_ms !== null && !browserMediaRunning;
  const stateLabel = sourceStarved ? "目前無法判斷" : unsafe ? "需要注意" : "目前安全";
  const stateTone = sourceStarved ? "warn" : unsafe ? "bad" : "ok";
  const currentPosture = observer?.metrics.current_posture ?? "未知";
  const confidence = Math.round((observer?.confidence ?? 0) * 100);

  return <div className="page-stack dashboard-page">
    <header className="resident-header">
      <div><span className="eyebrow">單一住戶照護</span><h1>{status.subject_id}</h1></div>
      <div className={`resident-state ${stateTone}`}><ShieldCheck size={26} weight="fill" /><div><span>目前狀態</span><b>{stateLabel}</b></div></div>
      <div className="resident-meta"><span>最後成功觀察</span><b>{status.cascade.windows_seen ? `第 ${status.cascade.windows_seen} 個視窗` : "尚無觀察"}</b></div>
      <button className="source-quick" onClick={() => onNavigate("source")}><VideoCamera size={19} /><div><span>{browserMediaRunning ? "瀏覽器攝影機" : status.source.kind ?? "影像來源"}</span><b>{status.source.running || browserMediaRunning ? "分析中" : "未啟動"}</b></div><CaretRight size={16} /></button>
    </header>

    {sourceStarved && <div className="global-alert"><b>影像來源已停止提供畫面</b><span>安全狀態不可由舊資料推斷，請檢查即時影像。</span></div>}

    <section className="ai-status" aria-labelledby="ai-status-title">
      <div className="ai-icon"><Brain size={25} weight="duotone" /></div>
      <div className="ai-copy"><span className="eyebrow" id="ai-status-title">AI 身體狀況</span><h2>{observer?.headline ?? "等待 Observer 建立第一筆觀察"}</h2><p>{observer?.detail ?? "Observer 會定期讀取 SQLite 的結構化彙總，即使沒有異常也會留下紀錄。"}</p></div>
      <div className="ai-facts">
        <div><span>目前姿勢</span><b>{currentPosture}</b></div><div><span>分析信心</span><b>{confidence || "—"}{confidence ? "%" : ""}</b></div><div><span>下次分析</span><b>{status.observer.next_run_at_ms ? new Date(status.observer.next_run_at_ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</b></div>
      </div>
      <div className="ai-actions"><Badge tone={observerTone(observer)} dot>{observer?.status ?? "尚無資料"}</Badge><button className="text-action" onClick={() => onNavigate("statistics")}>查看分析紀錄 <ArrowRight size={15} /></button></div>
      <small>AI 觀察不是醫療診斷；通知與照護動作只由 Policy Gateway 授權。</small>
    </section>

    {stats && <PipelinePanel status={status} stats={stats} />}

    <div className="content-grid">
      <div className="span-8"><EventTimeline events={events} onSelect={setSelected} /></div>
      <div className="span-4 side-stack"><HydrationPanel summary={hydration} /><HealthPanel samples={samples} findings={findings} /></div>
      <div className="span-8"><RunTable runs={runs} onSelectEvent={setSelected} /></div>
      <div className="span-4 side-stack"><ActionsPanel actions={actions} /><LogPanel logs={logs} /></div>
    </div>

    {selected && <div className="drawer-backdrop" onMouseDown={() => setSelected(null)}><aside className="trace-drawer" onMouseDown={(e) => e.stopPropagation()} aria-label="事件決策歷程"><CascadeTrace eventId={selected} onClose={() => setSelected(null)} /></aside></div>}
  </div>;
}
