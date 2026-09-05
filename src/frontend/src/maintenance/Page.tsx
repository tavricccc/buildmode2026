import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowClockwise, Wrench } from "@phosphor-icons/react";
import { api } from "../api/client";
import type { RealtimeClient } from "../api/ws";
import { Card, Empty, ErrorBanner, errorText } from "../components/ui";
import type { CareAction, PipelineRun, RunStats, Status } from "../types/api";
import { CascadeTrace } from "../dashboard/CascadeTrace";
import { PipelinePanel } from "../dashboard/PipelinePanel";
import { RunTable } from "../dashboard/RunTable";
import { ActionsPanel, LogPanel } from "../dashboard/SidePanels";

export function MaintenancePage({ status, realtime }: {
  status: Status | null;
  realtime: RealtimeClient;
}) {
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [stats, setStats] = useState<RunStats | null>(null);
  const [actions, setActions] = useState<CareAction[]>([]);
  const [logs, setLogs] = useState<{ log_id: string; level: string; source: string; message: string; created_at: string }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([api.runs(100), api.actions(60), api.logs(100)]);
    const [runData, actionData, logData] = results;
    if (runData.status === "fulfilled") {
      setRuns(runData.value.runs);
      setStats(runData.value.stats);
      setError(null);
    } else {
      setError(errorText(runData.reason));
    }
    if (actionData.status === "fulfilled") setActions(actionData.value.actions);
    if (logData.status === "fulfilled") setLogs(logData.value.logs);
  }, []);

  useEffect(() => {
    void refresh();
    const schedule = () => {
      if (pending.current !== null) return;
      pending.current = window.setTimeout(() => {
        pending.current = null;
        void refresh();
      }, 400);
    };
    const offMessage = realtime.onMessage(schedule);
    const offResync = realtime.onResync(() => void refresh());
    return () => {
      offMessage();
      offResync();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [realtime, refresh]);

  return <div className="page-stack">
    <header className="page-heading">
      <div><span className="eyebrow">系統管理</span><h1>系統維護</h1><p>模型管線、決策紀錄與日誌集中在這裡，不占用照護首頁。</p></div>
      <button className="action" onClick={() => void refresh()}><ArrowClockwise size={17} />重新整理</button>
    </header>

    {error && <ErrorBanner>無法讀取維護資料：{error}</ErrorBanner>}
    {!status ? <Card title="系統狀態"><Empty>正在連線至後端…</Empty></Card> : <>
      <div className="maintenance-note"><Wrench size={20} /><span>這一頁供部署與除錯使用。日常照護判讀請回到「照護總覽」。</span></div>
      {stats && <PipelinePanel status={status} stats={stats} />}
      <div className="content-grid">
        <div className="span-8"><RunTable runs={runs} onSelectEvent={setSelected} /></div>
        <div className="span-4 side-stack"><ActionsPanel actions={actions} /><LogPanel logs={logs} /></div>
      </div>
    </>}

    {selected && <div className="drawer-backdrop" onMouseDown={() => setSelected(null)}>
      <aside className="trace-drawer" onMouseDown={(event) => event.stopPropagation()} aria-label="事件決策歷程">
        <CascadeTrace eventId={selected} onClose={() => setSelected(null)} />
      </aside>
    </div>}
  </div>;
}
