import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, Empty, clock, ms, outcomeTone, riskTone } from "../components/ui";
import type { EventDetail } from "../types/api";

/**
 * The "click an event, see the whole cascade" view docs/03_API_AND_FRONTEND.md asks for.
 *
 * Everything shown here comes from `pipeline_runs`, `model_calls`,
 * `analyses` and `actions` — nothing is reconstructed in the browser, so
 * what a reviewer sees is exactly what the audit trail holds.
 */
export function CascadeTrace({ eventId, onClose }: { eventId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.event(eventId)
      .then((data) => !cancelled && setDetail(data))
      .catch((exc: Error) => !cancelled && setError(exc.message));
    return () => { cancelled = true; };
  }, [eventId]);

  if (error) return <Card title="Cascade Trace"><p className="banner bad">{error}</p></Card>;
  if (!detail) return <Card title="Cascade Trace"><Empty>載入中…</Empty></Card>;

  const { event, runs, model_calls, analyses, actions } = detail;

  return (
    <Card
      title={`Cascade Trace · ${event.event_type}`}
      aside={<button className="action" onClick={onClose}>關閉</button>}
    >
      <div className="row" style={{ marginBottom: ".9rem" }}>
        <Badge tone={event.event_type === "fall" ? "bad" : "ok"}>{event.status}</Badge>
        <span className="muted mono">{clock(event.occurred_at_ms)} → {clock(event.updated_at_ms)}</span>
        <span className="muted">信心 {event.confidence.toFixed(2)}</span>
      </div>

      <div className="stack">
        {runs.map((run) => (
          <div key={run.run_id} className="trace">
            <div className="trace-step l1">
              <div className="layer">L1 · {clock(run.window_ended_at_ms)}</div>
              <div className="outcome">{run.l1_decision}</div>
              <div className="detail">{run.l1_detector_id} · conf {run.l1_confidence.toFixed(2)}</div>
            </div>
            <div className="trace-step l2">
              <div className="layer">L2 · {ms(run.l2_latency_ms)}</div>
              <div className="outcome" style={{ color: `var(--${outcomeTone(run.l2_outcome)})` }}>
                {run.l2_outcome}
              </div>
              <div className="detail">
                {run.l2_model ?? "—"}
                {run.l2_repaired && " · repaired"}
                {run.l2_escalation_reasons.length > 0 && ` · ${run.l2_escalation_reasons.join(", ")}`}
                {run.l2_error && ` · ${run.l2_error}`}
              </div>
            </div>
            <div className="trace-step l3">
              <div className="layer">L3 · {ms(run.l3_latency_ms)}</div>
              <div className="outcome" style={{ color: `var(--${outcomeTone(run.l3_outcome)})` }}>
                {run.l3_outcome}
              </div>
              <div className="detail">
                {run.l3_risk_level ? `risk ${run.l3_risk_level} · ` : ""}
                {run.l3_reason || run.l3_error || run.l3_model || "—"}
              </div>
            </div>
          </div>
        ))}
      </div>

      {analyses.length > 0 && (
        <>
          <h2 style={{ marginTop: "1.2rem" }}>L3 深度分析</h2>
          <table>
            <thead><tr><th>觸發</th><th>風險</th><th>建議</th><th>證據</th></tr></thead>
            <tbody>
              {analyses.map((analysis) => (
                <tr key={analysis.analysis_id}>
                  <td>{analysis.trigger}</td>
                  <td><Badge tone={riskTone(analysis.risk_level)}>{analysis.risk_level ?? "—"}</Badge></td>
                  <td>{analysis.recommendation ?? "—"}</td>
                  <td>{analysis.degraded
                    ? <Badge tone="warn">僅文字，無影像</Badge>
                    : <Badge tone="ok">已附證據片段</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {actions.length > 0 && (
        <>
          <h2 style={{ marginTop: "1.2rem" }}>Policy 決策</h2>
          <table>
            <thead><tr><th>動作</th><th>規則</th><th>原因</th><th>抑制</th></tr></thead>
            <tbody>
              {actions.map((action) => (
                <tr key={action.action_id}>
                  <td><Badge tone={action.kind === "notify_telegram" ? "bad" : "muted"}>{action.kind}</Badge></td>
                  <td className="mono">{action.rule}</td>
                  <td className="muted">{action.reason}</td>
                  <td className="muted">{action.suppressed ? action.suppressed_reason : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {model_calls.length > 0 && (
        <>
          <h2 style={{ marginTop: "1.2rem" }}>模型呼叫</h2>
          <table>
            <thead><tr><th>層級</th><th>模型</th><th>狀態</th><th>嘗試</th><th>延遲</th><th>Tokens</th></tr></thead>
            <tbody>
              {model_calls.map((call) => (
                <tr key={call.call_id}>
                  <td>{call.layer.replace("_", " ")}</td>
                  <td className="mono">{call.model}</td>
                  <td><Badge tone={call.status === "ok" ? "ok" : call.status === "repaired" ? "warn" : "bad"}>
                    {call.status}{call.error_code ? ` · ${call.error_code}` : ""}
                  </Badge></td>
                  <td>{call.attempts}</td>
                  <td className="mono">{ms(call.latency_ms)}</td>
                  <td className="mono">{call.total_tokens ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Card>
  );
}
