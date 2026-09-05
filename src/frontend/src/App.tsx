import { useEffect, useMemo, useState } from "react";
import {
  ChartLineUp, Database, House, Pulse, SlidersHorizontal, VideoCamera, Wrench,
} from "@phosphor-icons/react";
import { api } from "./api/client";
import { RealtimeClient } from "./api/ws";
import { DashboardPage } from "./dashboard/Page";
import { SettingsPage } from "./settings/Page";
import { SetupPage } from "./setup/Wizard";
import { SourcePage } from "./source/Page";
import { StatisticsPage } from "./statistics/Page";
import type { Status } from "./types/api";

export type AppTab = "dashboard" | "source" | "statistics" | "setup" | "settings";

const NAV: { id: AppTab; label: string; icon: typeof House }[] = [
  { id: "dashboard", label: "照護總覽", icon: House },
  { id: "source", label: "即時影像", icon: VideoCamera },
  { id: "statistics", label: "趨勢與統計", icon: ChartLineUp },
  { id: "setup", label: "初始設定", icon: Wrench },
  { id: "settings", label: "系統設定", icon: SlidersHorizontal },
];

export default function App() {
  const realtime = useMemo(() => new RealtimeClient(), []);
  const [tab, setTab] = useState<AppTab>("dashboard");
  const [status, setStatus] = useState<Status | null>(null);
  const [offline, setOffline] = useState<string | null>(null);

  useEffect(() => {
    realtime.connect();
    return () => realtime.close();
  }, [realtime]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await api.status();
        if (!cancelled) { setStatus(next); setOffline(null); }
      } catch (exc) {
        if (!cancelled) setOffline((exc as Error).message);
      }
    };
    void poll();
    const timer = window.setInterval(poll, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><Pulse weight="fill" size={20} /><span>Care <b>Agent</b></span></div>
        <nav aria-label="主要導覽">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button key={id} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>
              <Icon size={19} /><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-status">
          <div><Database size={15} /><span className="mono">{status?.config_version ?? "載入中"}</span></div>
          <div><i className={`status-dot ${offline ? "bad" : "ok"}`} />{offline ? "後端未連線" : "後端已連線"}</div>
          <div><i className={`status-dot ${status?.realtime.clients ? "ok" : "muted"}`} />WebSocket 即時同步</div>
        </div>
      </aside>

      <main className="workspace">
        {offline && <div className="global-alert"><b>目前無法確認照護狀態</b><span>{offline}</span></div>}
        {tab === "dashboard" && <DashboardPage status={status} realtime={realtime} onNavigate={setTab} />}
        {tab === "source" && <SourcePage status={status} />}
        {tab === "statistics" && <StatisticsPage />}
        {tab === "setup" && <SetupPage onDone={() => setTab("dashboard")} />}
        {tab === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
