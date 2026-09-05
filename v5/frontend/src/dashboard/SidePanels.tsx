import { Badge, Card, Empty, clock, riskTone } from "../components/ui";
import type { CareAction, CareEvent, Status } from "../types/api";

export function EventTimeline({ events, onSelect }: {
  events: CareEvent[]; onSelect: (id: string) => void;
}) {
  return (
    <Card title="Events">
      {events.length === 0 ? <Empty>No events recorded.</Empty> : (
        <div className="scroll">
          <table>
            <thead><tr><th>Time</th><th>Type</th><th>Status</th><th>Conf.</th></tr></thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id} className="clickable" onClick={() => onSelect(event.event_id)}>
                  <td className="mono">{clock(event.occurred_at_ms)}</td>
                  <td>{event.event_type}</td>
                  <td><Badge tone={
                    event.status === "confirmed" ? "bad"
                      : event.status === "suspect" ? "warn"
                      : event.status === "completed" ? "ok" : "muted"
                  }>{event.status}</Badge></td>
                  <td className="mono">{event.confidence.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function HydrationPanel({ summary }: {
  summary: { sessions: number; total_ml: number; target_ml: number; progress: number } | null;
}) {
  if (!summary) return <Card title="Hydration"><Empty>Loading…</Empty></Card>;
  const percent = Math.min(100, Math.round(summary.progress * 100));
  return (
    <Card title="Hydration today">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: ".4rem" }}>
        <span style={{ fontSize: "1.35rem", fontWeight: 600 }}>
          {Math.round(summary.total_ml)}<span className="muted" style={{ fontSize: ".8rem" }}> / {summary.target_ml} ml</span>
        </span>
        <span className="muted">{summary.sessions} session{summary.sessions === 1 ? "" : "s"}</span>
      </div>
      <div className="bar"><i style={{ width: `${percent}%` }} /></div>
      <p className="muted" style={{ margin: ".5rem 0 0", fontSize: 12 }}>
        Only completed sessions are counted; a repeat inside the cooldown window is not a second drink.
      </p>
    </Card>
  );
}

export function SourcePanel({ status, onStart, onStop, scenarios, busy }: {
  status: Status;
  scenarios: { id: string; name: string }[];
  onStart: (id: string) => void;
  onStop: () => void;
  busy: boolean;
}) {
  const source = status.source;
  const browserLive = Boolean(status.browser_media?.some((item) => item.running));
  const frames = status.cascade.frames;
  const starved = status.cascade.starved_since_ms !== null && !browserLive;
  return (
    <Card title="Source" aside={<Badge tone={source.running || browserLive ? "ok" : "muted"} dot>
      {browserLive ? "browser live" : source.running ? source.kind ?? "running" : "stopped"}
    </Badge>}>
      {starved && <p className="banner" style={{ marginBottom: ".6rem" }}>
        No frames arriving — the source has stopped producing.
      </p>}
      <p className="muted" style={{ margin: "0 0 .6rem", fontSize: 12.5 }}>
        {source.scenario ? <>Scenario <b>{source.scenario}</b> · </> : null}
        buffer {frames.frames}/{frames.capacity}
        {frames.dropped > 0 && <> · {frames.dropped} dropped</>}
      </p>
      <div className="row">
        {scenarios.map((scenario) => (
          <button key={scenario.id} className="action" disabled={busy}
                  onClick={() => onStart(scenario.id)}>
            ▶ {scenario.name}
          </button>
        ))}
        <button className="action" disabled={busy || !source.running} onClick={onStop}>■ Stop replay</button>
      </div>
    </Card>
  );
}

export function ActionsPanel({ actions }: { actions: CareAction[] }) {
  return (
    <Card title="Policy decisions">
      {actions.length === 0 ? <Empty>Nothing has met a policy rule yet.</Empty> : (
        <div className="scroll">
          <table>
            <thead><tr><th>Time</th><th>Action</th><th>Rule</th><th>Note</th></tr></thead>
            <tbody>
              {actions.map((action) => (
                <tr key={action.action_id}>
                  <td className="mono">{clock(action.created_at)}</td>
                  <td><Badge tone={action.kind === "notify_telegram" ? "bad"
                    : action.kind === "dashboard_alert" ? "warn" : "muted"}>{action.kind}</Badge></td>
                  <td className="mono">{action.rule}</td>
                  <td className="muted">{action.suppressed ? action.suppressed_reason : action.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function HealthPanel({ samples, findings }: {
  samples: { metric: string; value: number; unit: string; source: string }[];
  findings: { finding_id: string; headline: string; detail: string; severity: string }[];
}) {
  return (
    <Card title="Health & observer">
      {samples.length === 0 && findings.length === 0 && <Empty>No health samples or findings yet.</Empty>}
      {samples.length > 0 && (
        <div className="stat-row" style={{ marginBottom: findings.length ? "1rem" : 0 }}>
          {samples.map((sample) => (
            <div className="stat small" key={sample.metric}>
              <div className="value">{sample.value}<span className="muted" style={{ fontSize: ".7rem" }}> {sample.unit}</span></div>
              <div className="label">{sample.metric}</div>
            </div>
          ))}
        </div>
      )}
      {findings.map((finding) => (
        <div key={finding.finding_id} style={{ marginBottom: ".5rem" }}>
          <Badge tone={riskTone(finding.severity === "warning" ? "medium" : "low")}>{finding.severity}</Badge>{" "}
          <b style={{ fontSize: 13 }}>{finding.headline}</b>
          <div className="muted" style={{ fontSize: 12 }}>{finding.detail}</div>
        </div>
      ))}
    </Card>
  );
}

export function LogPanel({ logs }: {
  logs: { log_id: string; level: string; source: string; message: string; created_at: string }[];
}) {
  return (
    <Card title="Logs">
      {logs.length === 0 ? <Empty>Quiet.</Empty> : (
        <div className="scroll">
          <table>
            <tbody>
              {logs.map((log) => (
                <tr key={log.log_id}>
                  <td className="mono" style={{ width: "5.5rem" }}>{clock(log.created_at)}</td>
                  <td style={{ width: "4rem" }}>
                    <Badge tone={log.level === "error" ? "bad" : log.level === "warn" ? "warn" : "muted"}>
                      {log.level}
                    </Badge>
                  </td>
                  <td className="mono muted" style={{ width: "5rem" }}>{log.source}</td>
                  <td>{log.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
