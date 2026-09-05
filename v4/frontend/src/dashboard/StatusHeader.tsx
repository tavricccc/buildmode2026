import type { StatusSnapshot } from "../types/api";

interface Props {
  snapshot: StatusSnapshot | null;
  wsConnected: boolean;
  lastMessageType?: string;
}

export function StatusHeader({ snapshot, wsConnected, lastMessageType }: Props) {
  return (
    <header className="status-header">
      <span className={snapshot?.backend.status === "healthy" ? "ok" : "warn"}>
        backend: {snapshot?.backend.status ?? "—"}
      </span>
      <span className={snapshot?.stub_openai.status === "healthy" ? "ok" : "warn"}>
        stub: {snapshot?.stub_openai.status ?? "—"}
      </span>
      <span className={wsConnected ? "ok" : "warn"}>ws: {wsConnected ? "connected" : "disconnected"}</span>
      <span className="muted">last: {lastMessageType ?? "—"}</span>
    </header>
  );
}
