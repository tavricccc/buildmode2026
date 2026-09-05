import { useEffect, useState } from "react";
import { status } from "../api/status";
import type { StatusSnapshot } from "../types/api";
import { useWebSocket } from "../api/ws";
import { Card } from "../components/Card";
import { StatusHeader } from "./StatusHeader";
import { VideoPanel } from "./VideoPanel";
import { HealthPanel } from "./HealthPanel";
import { HydrationPanel } from "./HydrationPanel";
import { EventTimeline } from "./EventTimeline";
import { LogPanel } from "./LogPanel";

export default function DashboardPage() {
  const [snapshot, setSnapshot] = useState<StatusSnapshot | null>(null);
  const { last, connected } = useWebSocket();
  useEffect(() => {
    status.snapshot().then(setSnapshot).catch(() => setSnapshot(null));
    const id = setInterval(() => status.snapshot().then(setSnapshot).catch(() => undefined), 5000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="dashboard">
      <StatusHeader snapshot={snapshot} wsConnected={connected} lastMessageType={last?.type} />
      <div className="dashboard-grid">
        <VideoPanel />
        <HealthPanel />
        <HydrationPanel />
        <EventTimeline />
        <LogPanel lastMessage={last} />
      </div>
    </div>
  );
}
