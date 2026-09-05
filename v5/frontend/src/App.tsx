import { useEffect, useMemo, useState } from "react";
import { api } from "./api/client";
import { RealtimeClient } from "./api/ws";
import { Badge, healthTone } from "./components/ui";
import { DashboardPage } from "./dashboard/Page";
import { SettingsPage } from "./settings/Page";
import { SetupPage } from "./setup/Wizard";
import type { Status } from "./types/api";

type Tab = "dashboard" | "setup" | "settings";

export default function App() {
  const realtime = useMemo(() => new RealtimeClient(), []);
  const [tab, setTab] = useState<Tab>("dashboard");
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
    // Status is polled rather than pushed: it is a snapshot of health and
    // queue depth, and a stalled pipeline is exactly the case where no
    // WebSocket frame would arrive to tell you about it.
    const timer = window.setInterval(poll, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const l1Health = status?.cascade.l1.detector.status ?? "unknown";

  return (
    <div className="app">
      <header className="top">
        <h1>Care Agent <span className="muted">v5</span></h1>
        {status && (
          <div className="row">
            <Badge tone={healthTone(l1Health)} dot>L1 {l1Health}</Badge>
            <Badge tone={status.providers.l2.stub ? "muted" : "ok"} dot>
              L2 {status.providers.l2.stub ? "stub" : status.providers.l2.model}
            </Badge>
            <Badge tone={!status.cascade.l3.enabled ? "muted" : status.providers.l3.stub ? "muted" : "ok"} dot>
              L3 {!status.cascade.l3.enabled ? "off" : status.providers.l3.stub ? "stub" : status.providers.l3.model}
            </Badge>
          </div>
        )}
        <div className="spacer" />
        {status && <span className="muted mono" style={{ fontSize: 12 }}>{status.config_version}</span>}
        <nav className="tabs">
          {(["dashboard", "setup", "settings"] as Tab[]).map((name) => (
            <button key={name} aria-current={tab === name ? "page" : undefined}
                    onClick={() => setTab(name)}>
              {name[0]!.toUpperCase() + name.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      {offline && <p className="banner bad" style={{ marginBottom: "1rem" }}>
        Backend unreachable: {offline}
      </p>}

      {tab === "dashboard" && <DashboardPage status={status} realtime={realtime} />}
      {tab === "setup" && <SetupPage onDone={() => setTab("dashboard")} />}
      {tab === "settings" && <SettingsPage />}
    </div>
  );
}
